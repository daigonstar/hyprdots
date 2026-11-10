import json
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pulse  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"  # pactl -f json list ..., from a PC with an Arctis 7 and a PCM2902
GAME = "alsa_output.usb-SteelSeries_SteelSeries_Arctis_7-00.stereo-game"
PCM = "alsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-mono"


def fixture(name):
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


class Devices(unittest.TestCase):
    def test_outputs(self):
        sinks = pulse.outputs(pulse.parse_devices(fixture("sinks")))
        game = next(s for s in sinks if s["name"] == GAME)
        self.assertEqual(game["description"], "SteelSeries Arctis 7 Game")
        self.assertEqual(game["volume"], 48)
        self.assertEqual(game["card"], "alsa_card.usb-SteelSeries_SteelSeries_Arctis_7-00")
        self.assertEqual(game["ports"], [("usb-gaming-headset-output-stereo", "Headphones", True)])
        self.assertEqual(len(sinks), 4)

    def test_inputs_leave_out_monitors(self):
        sources = pulse.parse_devices(fixture("sources"))
        mics = pulse.inputs(sources)
        self.assertEqual([m["description"] for m in mics],
                         ["PCM2902 Audio Codec Analog Mono", "SteelSeries Arctis 7 Chat", "Ryzen HD Audio Controller Analog Stereo"])
        ryzen = mics[2]
        self.assertEqual([p[2] for p in ryzen["ports"]], [False, False, False])  # nothing plugged into it
        self.assertTrue(any(s["monitor"] for s in sources))

    def test_the_apps_own_filters_are_not_devices(self):
        text = json.dumps([{"name": "hyprdots_eq", "description": "Equaliser", "properties": {"device.class": "filter"}},
                           {"name": GAME, "description": "Game", "properties": {}}])
        self.assertEqual([s["name"] for s in pulse.outputs(pulse.parse_devices(text))], [GAME])
        self.assertEqual(pulse.parse_devices("nope"), [])
        self.assertEqual(pulse.parse_devices('{"a": 1}'), [])


class Streams(unittest.TestCase):
    def test_apps_playing(self):
        playing = pulse.parse_streams(fixture("sink-inputs"), "sink")
        self.assertEqual([(s["app"], s["device"]) for s in playing], [("vesktop", 74), ("vesktop", 73), ("Chromium", 74)])
        self.assertEqual(playing[0]["volume"], 153)
        self.assertEqual(playing[0]["title"], "")  # "Playback" says nothing

    def test_level_meters_are_not_apps(self):
        recording = pulse.parse_streams(fixture("source-outputs"), "source")  # vesktop, and ten of pavucontrol's meters
        self.assertEqual([(s["app"], s["device"]) for s in recording], [("vesktop", 72)])

    def test_our_own_streams_are_left_out(self):
        text = json.dumps([{"index": 1, "source": 72, "properties": {"application.name": "hyprdots-meter"}},
                           {"index": 2, "source": 72, "properties": {"application.name": "OBS", "media.name": "Mic/Aux"}}])
        self.assertEqual([(s["app"], s["title"]) for s in pulse.parse_streams(text, "source")], [("OBS", "Mic/Aux")])


class Cards(unittest.TestCase):
    def test_profiles(self):
        cards = {c["description"]: c for c in pulse.parse_cards(fixture("cards"))}
        arctis = cards["SteelSeries Arctis 7"]
        self.assertEqual(arctis["profile"], "output:mono-chat+output:stereo-game+input:mono-chat")
        self.assertEqual(arctis["profiles"][0][1], "Chat Output + Game Output + Chat Input")  # best first
        self.assertEqual(arctis["profiles"][-1], ("off", "Off"))
        radeon = cards["Radeon High Definition Audio Controller"]
        self.assertEqual([n for n, _d in radeon["profiles"]], ["pro-audio", "off"])  # HDMI with nothing plugged in

    def test_a_profile_in_use_stays_even_when_unavailable(self):
        text = json.dumps([{"name": "c", "active_profile": "a", "properties": {},
                            "profiles": {"a": {"description": "A", "available": False, "priority": 1},
                                         "b": {"description": "B", "available": False, "priority": 9}}}])
        self.assertEqual(pulse.parse_cards(text)[0]["profiles"], [("a", "A")])


class InUse(unittest.TestCase):
    def test_behind_a_filter(self):
        self.assertEqual(pulse.current("hyprdots_eq", "hyprdots_eq", True, GAME), GAME)
        self.assertEqual(pulse.current(GAME, "hyprdots_eq", True, "other"), GAME)
        self.assertEqual(pulse.current("hyprdots_eq", "hyprdots_eq", False, GAME), "hyprdots_eq")


class Levels(unittest.TestCase):
    def test_peak(self):
        self.assertEqual(pulse.peak(b""), 0.0)
        self.assertAlmostEqual(pulse.peak(struct.pack("<4h", 0, 100, -16384, 3)), 0.5)
        self.assertEqual(pulse.peak(struct.pack("<h", -32768)), 1.0)

    def test_meter_in_db(self):
        self.assertEqual(pulse.meter_level(0), 0.0)
        self.assertEqual(pulse.meter_level(1.0), 1.0)
        self.assertAlmostEqual(pulse.meter_level(0.001001), 0.0, places=2)  # -60 dB
        self.assertAlmostEqual(pulse.meter_level(0.1), 2 / 3, places=3)  # -20 dB


if __name__ == "__main__":
    unittest.main()
