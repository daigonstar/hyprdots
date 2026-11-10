import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import filters as audio  # noqa: E402
import pulse  # noqa: E402

GAME = "alsa_output.usb-SteelSeries_SteelSeries_Arctis_7-00.stereo-game"
CHAT = "alsa_output.usb-SteelSeries_SteelSeries_Arctis_7-00.mono-chat"
MIC = "alsa_input.usb-SteelSeries_SteelSeries_Arctis_7-00.mono-chat"


def device(name, percents, mute=False, cls="sound"):
    channels = {f"ch{i}": {"value": 0, "value_percent": f"{p}%", "db": "0 dB"} for i, p in enumerate(percents)}
    return {"name": name, "description": name.split(".")[-1], "mute": mute, "volume": channels,
            "properties": {"device.class": cls}}


SINKS = json.dumps([device("alsa_output.pci-0000_13_00.6.iec958-stereo", [40, 40]), device(CHAT, [20]),
                    device(GAME, [48, 50], mute=True)])
SOURCES = json.dumps([device(GAME + ".monitor", [100], cls="monitor"), device(MIC, [100]),
                      device("alsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-mono", [90])])


class Devices(unittest.TestCase):
    def test_parse(self):
        found = pulse.parse_devices(SINKS)
        self.assertEqual([d["volume"] for d in found], [40, 20, 49])
        self.assertTrue(found[2]["mute"])
        self.assertTrue(pulse.parse_devices(SOURCES)[0]["monitor"])
        self.assertEqual(pulse.parse_devices("nope"), [])
        self.assertEqual(pulse.parse_devices("{}"), [])

    def test_the_arctis_has_game_chat_and_a_mic(self):
        parts = audio.headset_parts(pulse.parse_devices(SINKS), pulse.parse_devices(SOURCES), "SteelSeries Arctis 7")
        self.assertEqual(parts, {"game": GAME, "chat": CHAT, "mic": MIC})

    def test_a_headset_with_one_output(self):
        sinks = pulse.parse_devices(json.dumps([device("alsa_output.usb-Logitech_G435-00.analog-stereo", [50])]))
        parts = audio.headset_parts(sinks, [], "Logitech G435")
        self.assertEqual(parts, {"game": "alsa_output.usb-Logitech_G435-00.analog-stereo", "chat": None, "mic": None})

    def test_another_device_is_not_mistaken_for_it(self):
        self.assertEqual(audio.headset_parts(pulse.parse_devices(SINKS), [], "Corsair Void"),
                         {"game": None, "chat": None, "mic": None})
        self.assertEqual(audio.headset_parts(pulse.parse_devices(SINKS), [], ""), {"game": None, "chat": None, "mic": None})


class Equaliser(unittest.TestCase):
    def test_clamp_and_preamp(self):
        self.assertEqual(audio.clamp([20, -20, 3]), [12, -12, 3] + [0] * 7)
        self.assertEqual(audio.preamp([0] * 10), 1.0)
        self.assertEqual(audio.preamp([-6] * 10), 1.0)  # cuts need no headroom
        self.assertAlmostEqual(audio.preamp([6] + [0] * 9), 0.7079, places=3)  # half the boost: -3 dB
        self.assertEqual(audio.headroom_db([6, 12]), 6)

    def test_presets(self):
        for name, gains in audio.PRESETS.items():
            self.assertEqual(len(gains), len(audio.BANDS), name)
            self.assertEqual(audio.preset_of(gains), name)
        self.assertEqual(audio.preset_of([1, 2, 3]), audio.CUSTOM)

    def test_params_for_pw_cli(self):
        params = audio.eq_params([6] + [0] * 9)
        self.assertEqual(params["b1:Gain"], 6)
        self.assertEqual(params["pre:Mult"], audio.preamp([6]))
        text = audio.set_param_text({"b1:Gain": 6.0, "pre:Gain 1": 0.5})
        self.assertEqual(text, '{ params = [ "b1:Gain" 6.0 "pre:Gain 1" 0.5 ] }')

    def test_conf(self):
        text = audio.eq_conf(audio.PRESETS["Bass boost"], GAME, 'Arctis "7" EQ')
        self.assertIn(f'target.object = "{GAME}"', text)
        self.assertIn('node.description = "Arctis \\"7\\" EQ"', text)  # quotes cannot break out of the string
        self.assertEqual(text.count("label = bq_peaking"), len(audio.BANDS))
        self.assertEqual(text.count("output = "), len(audio.BANDS))  # pre -> b1 -> ... -> b10
        self.assertIn('label = linear control = { "Mult" = 0.7079', text)
        self.assertNotIn("mixer", text)  # eight inputs: the filter would play silence
        self.assertIn('inputs = [ "pre:In" ]', text)
        self.assertIn('outputs = [ "b10:Out" ]', text)
        self.assertEqual(text.count("{"), text.count("}"))
        self.assertEqual(text.count("["), text.count("]"))

    def test_response_follows_the_bands(self):
        flat = audio.PRESETS["Flat"]
        self.assertAlmostEqual(audio.response(flat, 1000), 0.0, places=6)
        bass = audio.PRESETS["Bass boost"]
        self.assertGreater(audio.response(bass, 40), audio.response(bass, 1000) + 5)  # bass well above the rest
        self.assertAlmostEqual(audio.response(bass, 4000), -3, delta=0.2)  # the rest down by the preamp
        one = [0] * 5 + [6] + [0] * 4
        self.assertAlmostEqual(audio.response(one, 1000), 3.0, delta=0.05)  # +6 at 1k, minus the 3 dB preamp
        treble = audio.PRESETS["Treble"]
        self.assertGreater(audio.response(treble, 16000), audio.response(treble, 100))


class Microphone(unittest.TestCase):
    def test_conf(self):
        text = audio.mic_conf(MIC, 150)
        self.assertIn(f'target.object = "{MIC}"', text)
        self.assertIn('"VAD Threshold (%)" = 99.0', text)
        self.assertIn("media.class = Audio/Source", text)
        self.assertIn(str(audio.RNNOISE), text)
        self.assertEqual(text.count("{"), text.count("}"))


if __name__ == "__main__":
    unittest.main()
