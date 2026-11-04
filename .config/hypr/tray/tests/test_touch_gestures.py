import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import touch_gestures as tg  # noqa: E402
import touch_lift  # noqa: E402

HEIGHT, BAR = 1152, 44


class Recognising(unittest.TestCase):
    def setUp(self):
        self.done = []
        self.g = tg.Gestures(lambda *a: self.done.append(a))
        self.g.height, self.g.bar = HEIGHT, BAR

    def drag(self, points, start=0.0, hold=0.0, slot=0):
        x, y = points[0]
        self.g.down(slot, x, y, start)
        self.g.frame(start)
        now = start + hold
        for x, y in points[1:]:
            now += 0.02
            self.g.move(slot, x, y)
            self.g.frame(now)
        self.g.up(slot)
        self.g.frame(now)

    def test_swipe_up_from_the_bottom_opens_the_launcher_once(self):
        self.drag([(800, HEIGHT - 5), (800, HEIGHT - 80), (800, HEIGHT - 200), (800, HEIGHT - 400)])
        self.assertEqual(self.done, [("launcher",)])

    def test_swipe_up_from_the_middle_is_scrolling(self):
        self.drag([(800, 900), (800, 700), (800, 400)])
        self.assertEqual(self.done, [])

    def test_a_short_swipe_from_the_bottom_does_nothing(self):
        self.drag([(800, HEIGHT - 5), (800, HEIGHT - 50)])
        self.assertEqual(self.done, [])

    def hold(self, seconds=1.2):
        self.g.down(0, 500, 600, 0.0)
        self.g.down(1, 600, 600, 0.05)
        self.g.frame(0.05 + seconds)

    def test_two_resting_fingers_pick_up_after_a_second(self):
        self.g.down(0, 500, 600, 0.0)
        self.g.down(1, 600, 600, 0.05)
        self.g.frame(0.5)
        self.assertEqual(self.done, [])
        self.g.frame(1.2)
        self.assertEqual(self.done, [("pickup", 550, 600)])

    def test_carrying_then_letting_go_says_where(self):
        self.hold()
        self.g.move(0, 500, 100)
        self.g.move(1, 600, 100)
        self.g.frame(1.5)
        self.g.up(0)
        self.g.up(1)
        self.assertEqual(self.done, [("pickup", 550, 600), ("carry", 550, 100), ("drop", 550, 100)])

    def test_two_fingers_that_moved_first_do_not_pick_up(self):
        self.g.down(0, 500, 600, 0.0)
        self.g.down(1, 600, 600, 0.0)
        self.g.move(0, 500, 500)
        self.g.move(1, 600, 500)
        self.g.frame(0.2)
        self.g.frame(3.0)
        self.assertEqual(self.done, [])

    def test_one_finger_held_does_nothing(self):
        self.g.down(0, 500, 600, 0.0)
        self.g.frame(5.0)
        self.g.up(0)
        self.assertEqual(self.done, [])

    def fingers(self, one, two, along=0):
        self.g.down(0, 900, 500, 0.0)
        self.g.down(1, 1000, 600, 0.01)
        self.g.frame(0.01)
        for step in (0.5, 1.0):
            self.g.move(0, 900 + one * step, 500 + along * step)
            self.g.move(1, 1000 + two * step, 600 + along * step)
            self.g.frame(0.1)
        self.g.up(0)
        self.g.up(1)

    def test_two_fingers_left_is_the_next_workspace(self):
        self.fingers(-200, -200)
        self.assertEqual(self.done, [("next",)])

    def test_two_fingers_right_is_the_previous_one(self):
        self.fingers(200, 200)
        self.assertEqual(self.done, [("previous",)])

    def test_pinching_is_not_a_swipe(self):
        self.fingers(-200, 200)
        self.assertEqual(self.done, [])

    def test_two_fingers_scrolling_up_is_not_a_swipe(self):
        self.fingers(130, 130, along=-300)
        self.assertEqual(self.done, [])


class Turning(unittest.TestCase):
    def test_each_way_up(self):
        # The panel's top left corner, on a 100 by 200 screen as turned
        self.assertEqual(tg.to_screen(0, 0, 0, 100, 200), (0, 0))
        self.assertEqual(tg.to_screen(0, 0, 1, 100, 200), (100, 0))
        self.assertEqual(tg.to_screen(0, 0, 2, 100, 200), (100, 200))
        self.assertEqual(tg.to_screen(0, 0, 3, 100, 200), (0, 200))


class Reader(unittest.TestCase):
    def test_multitouch_events_become_a_swipe(self):
        done = []
        reader = tg.TouchReader(tg.Gestures(lambda *a: done.append(a)), (0, 1000), (0, 1000))
        reader.set_screen({"transform": 0, "width": 2000, "height": 1000, "scale": 1, "reserved": [0, 44, 0, 0]})
        reader.event(tg.EV_ABS, tg.ABS_MT_SLOT, 0, 0)
        reader.event(tg.EV_ABS, tg.ABS_MT_TRACKING_ID, 7, 0)
        reader.event(tg.EV_ABS, tg.ABS_MT_POSITION_X, 500, 0)
        reader.event(tg.EV_ABS, tg.ABS_MT_POSITION_Y, 995, 0)
        reader.event(tg.EV_SYN, 0, 0, 0)
        reader.event(tg.EV_ABS, tg.ABS_MT_POSITION_Y, 700, 0.1)
        reader.event(tg.EV_SYN, 0, 0, 0.1)
        self.assertEqual(done, [("launcher",)])

    def test_turned_screen_swaps_its_sides(self):
        reader = tg.TouchReader(tg.Gestures(lambda *a: None), (0, 1), (0, 1))
        reader.set_screen({"transform": 1, "width": 2160, "height": 1440, "scale": 1.25, "reserved": [0, 44, 0, 0]})
        self.assertEqual((reader.width, reader.height), (1152, 1728))


class LostEvents(unittest.TestCase):
    def setUp(self):
        self.done = []
        self.reader = tg.TouchReader(tg.Gestures(lambda *a: self.done.append(a)), (0, 1000), (0, 1000))
        self.reader.set_screen({"transform": 0, "width": 1000, "height": 1000, "scale": 1, "reserved": [0, 44, 0, 0]})

    def land(self, slot, x, y, now=0.0):
        self.reader.event(tg.EV_ABS, tg.ABS_MT_SLOT, slot, now)
        self.reader.event(tg.EV_ABS, tg.ABS_MT_TRACKING_ID, slot + 1, now)
        self.reader.event(tg.EV_ABS, tg.ABS_MT_POSITION_X, x, now)
        self.reader.event(tg.EV_ABS, tg.ABS_MT_POSITION_Y, y, now)

    def test_a_lost_lift_does_not_leave_a_finger_down_for_good(self):
        self.land(0, 500, 500)
        self.reader.event(tg.EV_SYN, tg.SYN_REPORT, 0, 0.0)
        self.reader.slots_down = lambda: set()
        self.reader.event(tg.EV_SYN, tg.SYN_DROPPED, 0, 0.1)
        self.reader.event(tg.EV_ABS, tg.ABS_MT_TRACKING_ID, -1, 0.1)  # to be ignored, the kernel says
        self.reader.event(tg.EV_SYN, tg.SYN_REPORT, 0, 0.1)
        self.assertEqual(self.reader.gestures.fingers, {})
        # So the next gesture works
        self.land(0, 500, 995, 1.0)
        self.reader.event(tg.EV_SYN, tg.SYN_REPORT, 0, 1.0)
        self.reader.event(tg.EV_ABS, tg.ABS_MT_POSITION_Y, 700, 1.1)
        self.reader.event(tg.EV_SYN, tg.SYN_REPORT, 0, 1.1)
        self.assertEqual(self.done, [("launcher",)])

    def test_a_lost_lift_while_carrying_still_drops(self):
        self.land(0, 400, 500)
        self.land(1, 500, 500)
        self.reader.event(tg.EV_SYN, tg.SYN_REPORT, 0, 0.0)
        self.reader.gestures.frame(1.5)
        self.reader.slots_down = lambda: set()
        self.reader.event(tg.EV_SYN, tg.SYN_DROPPED, 0, 2.0)
        self.reader.event(tg.EV_SYN, tg.SYN_REPORT, 0, 2.0)
        self.assertEqual(self.done, [("pickup", 450, 500), ("drop", 450, 500)])


class Performing(unittest.TestCase):
    def test_swipes_can_reach_an_empty_workspace(self):
        with mock.patch.object(tg, "dispatch") as dispatch:
            tg.perform("next")
            tg.perform("previous")
        self.assertEqual([c.args[0] for c in dispatch.call_args_list],
                         ['hl.dsp.focus({ workspace = "r+1" })', 'hl.dsp.focus({ workspace = "r-1" })'])

    def test_a_second_swipe_does_not_close_a_launcher_still_appearing(self):
        with mock.patch.object(tg.subprocess, "Popen") as run, mock.patch.object(tg, "launcher_opened", [-tg.LAUNCHER_WAIT]), \
                mock.patch.object(tg.time, "monotonic", side_effect=[0.0, 0.0, 1.0, 5.0, 5.0]):
            tg.perform("launcher")
            tg.perform("launcher")
            tg.perform("launcher")
        self.assertEqual(run.call_count, 2)


class Launching(unittest.TestCase):
    def test_hyprland_starts_the_launcher_so_its_apps_are_not_ours(self):
        with mock.patch.object(tg, "dispatch") as dispatch, mock.patch.object(tg, "launcher_opened", [-tg.LAUNCHER_WAIT]):
            tg.perform("launcher")
        self.assertEqual(dispatch.call_args.args[0], 'hl.dsp.exec_cmd("~/.config/hypr/launcher/launcher.sh")')


class Windows(unittest.TestCase):
    def test_the_floating_one_on_top_on_this_workspace(self):
        def client(address, x, floating=False, workspace=1):
            return {"address": address, "at": [x, 0], "size": [100, 100], "workspace": {"id": workspace}, "floating": floating}
        clients = [client("0xa", 0), client("0xb", 0, floating=True), client("0xc", 0, workspace=2), client("0xd", 500)]
        self.assertEqual(tg.client_at(clients, 1, 50, 50)["address"], "0xb")
        self.assertIsNone(tg.client_at(clients, 1, 300, 50))


class Bin(unittest.TestCase):
    def test_the_picture_reaching_it_counts_not_the_fingers(self):
        size = (320, 200)
        self.assertTrue(touch_lift.over_bin(864, 130, size, 1728))   # fingers below the bin, the picture's top edge on it
        self.assertFalse(touch_lift.over_bin(864, 300, size, 1728))
        self.assertFalse(touch_lift.over_bin(100, 20, size, 1728))

    def test_a_tall_window_still_fits_under_the_fingers(self):
        self.assertEqual(touch_lift.copy_size(1000, 500), (320, 160))
        self.assertEqual(touch_lift.copy_size(500, 1000), (160, 320))


if __name__ == "__main__":
    unittest.main()
