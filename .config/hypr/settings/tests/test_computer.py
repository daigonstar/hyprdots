import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from hyprsettings import computer, computer_helper


def fake_root(files: dict[str, str]) -> Path:
    """A folder laid out like / with just these files in it."""
    root = Path(tempfile.mkdtemp(prefix="hypr-computer-test-"))
    for path, text in files.items():
        target = root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


class Names(unittest.TestCase):
    def test_network_name_is_made_from_the_name_you_type(self):
        self.assertEqual(computer.network_name("Dee's Desktop"), "dees-desktop")
        self.assertEqual(computer.network_name("  Café   Gaming PC! "), "cafe-gaming-pc")
        self.assertEqual(computer.network_name("---"), "")
        self.assertEqual(len(computer.network_name("a" * 100)), 63)

    def test_network_name_rules(self):
        self.assertEqual(computer.check_network_name("dees-desktop"), "")
        for bad in ("", "-start", "end-", "Has Caps", "under_score", "x" * 64):
            self.assertTrue(computer.check_network_name(bad), bad)

    def test_display_name_rules(self):
        self.assertEqual(computer.check_pretty_name("Dee's Desktop"), "")
        self.assertTrue(computer.check_pretty_name('say "hi"'))

    def test_rename_sends_both_names_to_the_helper(self):
        with mock.patch.object(computer, "helper", return_value=(True, "ok")) as helper:
            computer.rename("Dee's Desktop")
            helper.assert_called_with("name", "dees-desktop", "Dee's Desktop")
            computer.rename("plain-name")  # already a network name: no separate display name to keep
            helper.assert_called_with("name", "plain-name", "")
            computer.rename("Dee's Desktop", "office-pc")
            helper.assert_called_with("name", "office-pc", "Dee's Desktop")

    def test_rename_refuses_before_asking_for_a_password(self):
        with mock.patch.object(computer, "helper") as helper:
            self.assertFalse(computer.rename("!!!")[0])
            helper.assert_not_called()

    def test_identity_from_the_system_files(self):
        root = fake_root({"/etc/hostname": "dees-desktop\n",
                          "/etc/machine-info": 'PRETTY_HOSTNAME="Dee\'s Desktop"\nCHASSIS=desktop\nLOCATION="Office"\n'})
        with mock.patch.object(computer, "ROOT", root):
            ident = computer.identity()
        self.assertEqual((ident["static"], ident["pretty"], ident["chassis"], ident["location"]),
                         ("dees-desktop", "Dee's Desktop", "desktop", "Office"))
        self.assertTrue(ident["chassis_set"])
        self.assertEqual(computer.display_name(ident), "Dee's Desktop")


class Hardware(unittest.TestCase):
    def test_chassis_from_the_firmware_or_a_battery(self):
        for files, kind in (({"/sys/class/dmi/id/chassis_type": "10\n"}, "laptop"),
                            ({"/sys/class/dmi/id/chassis_type": "3\n"}, "desktop"),
                            ({"/sys/class/dmi/id/chassis_type": "31\n"}, "convertible"),
                            ({"/sys/class/power_supply/BAT0/type": "Battery\n"}, "laptop"),
                            ({"/sys/class/power_supply/hid-mouse/type": "Battery\n",
                              "/sys/class/power_supply/hid-mouse/scope": "Device\n"}, "desktop"),
                            ({"/sys/class/dmi/id/product_name": "VirtualBox\n"}, "vm")):
            with mock.patch.object(computer, "ROOT", fake_root(files)):
                self.assertEqual(computer.guess_chassis(), kind, files)

    def test_model_skips_what_makers_leave_unfilled(self):
        files = {"/sys/class/dmi/id/sys_vendor": "To Be Filled By O.E.M.", "/sys/class/dmi/id/product_name": "To Be Filled By O.E.M.",
                 "/sys/class/dmi/id/board_vendor": "ASUSTeK COMPUTER INC.", "/sys/class/dmi/id/board_name": "ROG STRIX X670E-E GAMING WIFI"}
        with mock.patch.object(computer, "ROOT", fake_root(files)):
            self.assertEqual(computer.model(), "ASUS ROG STRIX X670E-E GAMING WIFI")
        lenovo = {"/sys/class/dmi/id/sys_vendor": "LENOVO", "/sys/class/dmi/id/product_name": "20XW0055UK",
                  "/sys/class/dmi/id/product_version": "ThinkPad X1 Carbon Gen 9"}
        with mock.patch.object(computer, "ROOT", fake_root(lenovo)):
            self.assertEqual(computer.model(), "Lenovo ThinkPad X1 Carbon Gen 9")
        self.assertEqual(computer.vendor_name("Micro-Star International Co., Ltd."), "MSI")
        self.assertEqual(computer.vendor_name("Star Labs Systems Ltd."), "Star Labs Systems")

    def test_cpu_and_memory(self):
        text = "".join(f"processor\t: {i}\nmodel name\t: AMD Ryzen 9 7950X 16-Core Processor\n" for i in range(32))
        self.assertEqual(computer.cpu_name(text), "AMD Ryzen 9 7950X, 32 threads")
        self.assertEqual(computer.cpu_name("model name\t: Intel(R) Core(TM) i7-8550U CPU @ 1.80GHz\n"), "Intel Core i7-8550U")
        self.assertEqual(computer.memory("MemTotal:       32651712 kB\n"), "32 GB")

    def test_graphics_names_from_lspci(self):
        lspci = ('03:00.0 "VGA compatible controller" "Advanced Micro Devices, Inc. [AMD/ATI]" "Navi 31 [Radeon RX 7900 XT/7900 XTX]" -rc8 "" ""\n'
                 '00:02.0 "VGA compatible controller" "Intel Corporation" "Alder Lake-P GT2 [Iris Xe Graphics]" -r0c "" ""\n'
                 '00:1f.3 "Audio device" "Intel Corporation" "Alder Lake PCH-P High Definition Audio Controller" "" ""\n')
        self.assertEqual(computer.graphics(lspci), ["AMD Radeon RX 7900 XT/7900 XTX", "Intel Iris Xe Graphics"])

    def test_disks_leave_out_usb_sticks_and_ram_disks(self):
        files = {"/sys/block/nvme0n1/size": str(1000204886016 // 512), "/sys/block/nvme0n1/removable": "0",
                 "/sys/block/sda/size": str(2000398934016 // 512), "/sys/block/sda/removable": "0", "/sys/block/sda/queue/rotational": "1",
                 "/sys/block/sdb/size": str(32000000000 // 512), "/sys/block/sdb/removable": "1",
                 "/sys/block/zram0/size": str(8000000000 // 512)}
        with mock.patch.object(computer, "ROOT", fake_root(files)):
            self.assertEqual(computer.disks(), ["2 TB hard drive", "1 TB NVMe SSD"])

    def test_sizes_as_on_the_box(self):
        self.assertEqual(computer.size_label(512110190592), "512 GB")
        self.assertEqual(computer.size_label(4000787030016), "4 TB")
        self.assertEqual(computer.size_label(1500000000000), "1.5 TB")

    def test_copied_details_line_up(self):
        text = computer.specs_text("Dee's Desktop", [("Memory", "32 GB"), ("Processor", "AMD Ryzen 9")])
        self.assertEqual(text, "Dee's Desktop\nMemory     32 GB\nProcessor  AMD Ryzen 9\n")


class Clock(unittest.TestCase):
    def test_without_systemd_the_zone_comes_from_localtime(self):
        root = fake_root({"/etc/adjtime": "0.0 0 0\n0\nLOCAL\n"})
        os.symlink("/usr/share/zoneinfo/Europe/London", root / "etc/localtime")
        with mock.patch.object(computer, "ROOT", root), mock.patch.object(computer, "_run", return_value=""):
            clock = computer.clock()
        self.assertEqual((clock["zone"], clock["local_rtc"], clock["managed"]), ("Europe/London", True, False))

    def test_with_timedatectl(self):
        shown = "Timezone=America/New_York\nLocalRTC=no\nCanNTP=yes\nNTP=yes\nNTPSynchronized=yes\n"
        with mock.patch.object(computer, "_run", return_value=shown):
            clock = computer.clock()
        self.assertEqual((clock["zone"], clock["ntp"], clock["synced"], clock["local_rtc"]), ("America/New_York", True, True, False))

    def test_locale_names(self):
        root = fake_root({"/usr/share/i18n/locales/en_GB": 'LC_IDENTIFICATION\ntitle      "English locale for Britain"\n'
                          'language   "English"\nterritory  "United Kingdom"\nEND LC_IDENTIFICATION\n'})
        with mock.patch.object(computer, "ROOT", root):
            self.assertEqual(computer.locale_label("en_GB.UTF-8"), "English, United Kingdom (en_GB.UTF-8)")
            self.assertEqual(computer.locale_label("xx_YY.UTF-8"), "xx_YY.UTF-8")
        with mock.patch.object(computer, "_run", side_effect=lambda argv, **_: "C.utf8\nen_GB.utf8\nPOSIX\nde_DE.utf8\n" if argv[0] == "locale" else ""):
            self.assertEqual(computer.locales(), ["de_DE.UTF-8", "en_GB.UTF-8"])


class Helper(unittest.TestCase):
    def test_hosts_follows_the_new_name(self):
        text = "127.0.0.1 localhost\n::1 localhost\n127.0.1.1 oldpc.localdomain oldpc\n# oldpc was here\n10.0.0.2 oldpc-nas\n"
        self.assertEqual(computer_helper.hosts_renamed(text, "oldpc", "newpc"),
                         "127.0.0.1 localhost\n::1 localhost\n127.0.1.1 newpc.localdomain newpc\n# oldpc was here\n10.0.0.2 oldpc-nas\n")

    def test_helper_refuses_what_it_does_not_own(self):
        for argv in (["name", "Bad Name", ""], ["device", "toaster", ""], ["timezone", "../../etc/passwd"], ["ntp", "maybe"],
                     ["time", "tomorrow"], ["locale", "en_GB.UTF-8; rm -rf /"], ["anything"]):
            with mock.patch("sys.stdout"), self.assertRaises(SystemExit, msg=argv) as stop:
                computer_helper.main(argv)
            self.assertEqual(stop.exception.code, 1, argv)

    def test_helper_is_run_through_pkexec(self):
        done = mock.Mock(returncode=0, stdout="Renamed to Dee's Desktop.\n", stderr="")
        with mock.patch("shutil.which", return_value="/usr/bin/pkexec"), mock.patch("subprocess.run", return_value=done) as run:
            self.assertEqual(computer.helper("ntp", "on"), (True, "Renamed to Dee's Desktop."))
        self.assertEqual(run.call_args[0][0][0], "pkexec")
        self.assertTrue(run.call_args[0][0][2].endswith("computer_helper.py"))


if __name__ == "__main__":
    unittest.main()
