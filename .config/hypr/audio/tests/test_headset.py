import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import headset  # noqa: E402

ARCTIS = {"device": "SteelSeries Arctis (7/Pro)", "vendor": "SteelSeries", "product": "SteelSeries Arctis 7",
          "id_vendor": "0x1038", "id_product": "0x12ad", "status": "success",
          "capabilities": ["CAP_SIDETONE", "CAP_BATTERY_STATUS", "CAP_INACTIVE_TIME", "CAP_CHATMIX_STATUS", "CAP_LIGHTS"],
          "capabilities_str": ["sidetone", "battery", "inactive time", "chatmix", "lights"],
          "battery": {"status": "BATTERY_AVAILABLE", "level": 72, "time_to_empty_min": 705}, "chatmix": 64}


def output(*devices):
    return json.dumps({"name": "HeadsetControl", "version": "4.1.0", "device_count": len(devices), "devices": list(devices)})


class Parse(unittest.TestCase):
    def test_arctis_7(self):
        [d] = headset.parse(output(ARCTIS))
        self.assertEqual(d["battery"], 72)
        self.assertEqual(d["status"], "on")
        self.assertIsNone(d["charging"])  # the Arctis 7 never says
        self.assertEqual(d["id"], "1038:12ad")
        self.assertEqual(d["chatmix"], 64)
        self.assertIn("lights", d["capabilities"])
        self.assertEqual(d["minutes_left"], 705)
        self.assertEqual(headset.time_left_text(705), "About 11 h 45 min left")
        self.assertEqual(headset.time_left_text(45), "About 45 min left")
        self.assertEqual(headset.time_left_text(None), "")

    def test_real_output_from_headsetcontrol_4_2(self):
        text = (Path(__file__).parent / "arctis7_4.2.0.json").read_text(encoding="utf-8")
        [d] = headset.parse(text)
        self.assertEqual((d["battery"], d["chatmix"], d["status"]), (98, 56, "on"))
        self.assertEqual(d["capabilities"], ["sidetone", "battery", "lights", "inactive time", "chatmix"])

    def test_headset_off_has_no_level(self):
        off = {**ARCTIS, "battery": {"status": "BATTERY_UNAVAILABLE", "level": -1}}
        [d] = headset.parse(output(off))
        self.assertIsNone(d["battery"])
        self.assertEqual(d["status"], "off")

    def test_a_headset_that_reports_charging(self):
        [d] = headset.parse(output({**ARCTIS, "battery": {"status": "BATTERY_CHARGING", "level": 40}}))
        self.assertTrue(d["charging"])
        self.assertEqual(d["status"], "charging")

    def test_hid_error(self):
        [d] = headset.parse(output({**ARCTIS, "battery": {"status": "BATTERY_HIDERROR", "level": -1}}))
        self.assertEqual(d["status"], "error")
        self.assertIsNone(d["battery"])

    def test_older_versions_only_list_cap_names(self):
        old = {k: v for k, v in ARCTIS.items() if k != "capabilities_str"}
        [d] = headset.parse(output(old))
        self.assertEqual(d["capabilities"], ["sidetone", "battery status", "inactive time", "chatmix status", "lights"])

    def test_rubbish_and_no_devices(self):
        self.assertEqual(headset.parse("not json"), [])
        self.assertEqual(headset.parse("[]"), [])
        self.assertEqual(headset.parse(output()), [])

    def test_out_of_range_values_are_dropped(self):
        [d] = headset.parse(output({**ARCTIS, "battery": {"status": "BATTERY_AVAILABLE", "level": 255}, "chatmix": 300}))
        self.assertIsNone(d["battery"])
        self.assertIsNone(d["chatmix"])


class ChatMix(unittest.TestCase):
    def test_text(self):
        self.assertEqual(headset.chatmix_text(64), "Even")
        self.assertEqual(headset.chatmix_text(128), "Game 100% · Chat 0%")
        self.assertEqual(headset.chatmix_text(0), "Game 0% · Chat 100%")
        self.assertEqual(headset.chatmix_text(None), "Unknown")


class Charging(unittest.TestCase):
    def test_reported_wins(self):
        self.assertEqual(headset.charging([], True), "charging")

    def test_rising_level_is_charging(self):
        self.assertEqual(headset.charging([[0, 50], [600, 51], [1200, 53]], now=1200), "charging")

    def test_falling_level_is_on_battery(self):
        self.assertEqual(headset.charging([[0, 60], [900, 57]], now=900), "discharging")

    def test_too_little_change_is_unknown(self):
        self.assertEqual(headset.charging([[0, 60], [900, 59]], now=900), "unknown")
        self.assertEqual(headset.charging([], now=900), "unknown")

    def test_full(self):
        self.assertEqual(headset.charging([[0, 100]], now=0), "full")

    def test_switching_off_starts_over(self):
        # It climbed before it was switched off; since it came back on, nothing is known
        self.assertEqual(headset.charging([[0, 40], [600, 60], [700, None], [800, 60]], now=800), "unknown")

    def test_only_the_recent_trend_counts(self):
        # Fell long ago, climbing for the last 20 minutes
        history = [[0, 80], [3000, 50], [3600, 51], [4200, 53]]
        self.assertEqual(headset.charging(history, now=4200), "charging")


class Memory(unittest.TestCase):
    def test_readings_are_kept_for_a_while_and_not_duplicated(self):
        data = {}
        headset.add_reading(data, "A7", 50, now=0)
        headset.add_reading(data, "A7", 50, now=30)  # same level, too soon: not kept again
        headset.add_reading(data, "A7", 51, now=60)
        self.assertEqual(data["history"]["A7"], [[0, 50], [60, 51]])
        headset.add_reading(data, "A7", 51, now=headset.HISTORY_SECONDS + 61)
        self.assertEqual(data["history"]["A7"], [[headset.HISTORY_SECONDS + 61, 51]])

    def test_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h/headset.json"
            data = headset.remember_setting({}, "A7", "sidetone", 40)
            headset.save(data, path)
            loaded = headset.load(path)
            self.assertEqual(headset.setting(loaded, "A7", "sidetone"), 40)
            self.assertEqual(headset.setting(loaded, "A7", "inactive time"), headset.DEFAULTS["inactive time"])
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(headset.load(path), {})

    def test_tray_reading_remembers_and_guesses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "headset.json"
            self.assertIsNone(headset.peripheral([], path))
            at = lambda level: headset.parse(output({**ARCTIS, "battery": {"status": "BATTERY_AVAILABLE", "level": level}}))  # noqa: E731
            headset.peripheral(at(50), path, now=0)
            chip = headset.peripheral(at(53), path, now=600)
            self.assertEqual(chip, {"model": ARCTIS["product"], "capacity": 53, "headset": True, "charging": "charging"})
            off = headset.parse(output({**ARCTIS, "battery": {"status": "BATTERY_UNAVAILABLE", "level": -1}}))
            self.assertIsNone(headset.peripheral(off, path, now=700))
            self.assertEqual(headset.load(path)["history"][ARCTIS["product"]][-1], [700, None])

    def test_saving_own_parts_keeps_the_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "headset.json"
            window = {"eq": {"gains": [1] * 10}, "history": {"A7": [[0, 10]]}}  # its history is out of date
            headset.record("A7", 50, path, now=100)  # the tray adds a reading meanwhile
            headset.save_own(window, path=path)
            data = headset.load(path)
            self.assertEqual(data["eq"], {"gains": [1] * 10})
            self.assertEqual(data["history"]["A7"], [[100, 50]])

    def test_every_control_has_a_flag_and_a_label(self):
        self.assertEqual(set(headset.CONTROLS), set(headset.FLAGS))
        self.assertTrue(set(headset.RANGES) <= set(headset.FLAGS))


if __name__ == "__main__":
    unittest.main()
