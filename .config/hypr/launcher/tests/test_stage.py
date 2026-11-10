import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage  # noqa: E402


class OrbitTest(unittest.TestCase):
    def test_the_picked_app_sits_at_the_top_and_biggest(self):
        x, y, scale, opacity = stage.place_orbit(0, 1000, 800)
        self.assertAlmostEqual(x, 500)
        self.assertLess(y, 400)
        self.assertGreater(scale, stage.place_orbit(1, 1000, 800)[2])
        self.assertEqual(opacity, 1)

    def test_next_app_goes_clockwise(self):
        self.assertGreater(stage.place_orbit(1, 1000, 800)[0], 500)

    def test_apps_past_half_the_ring_are_left_off(self):
        self.assertIsNone(stage.place_orbit(stage.ORBIT_SLOTS / 2 + 1, 1000, 800))


class CarouselTest(unittest.TestCase):
    def test_the_picked_card_faces_you_in_the_middle(self):
        x, _y, scale, opacity, turn = stage.place_carousel(0, 1000, 800)
        self.assertEqual((x, scale, opacity, turn), (500, 1, 1, 0))

    def test_cards_either_side_turn_towards_the_middle(self):
        self.assertLess(stage.place_carousel(1, 1000, 800)[4], 0)
        self.assertGreater(stage.place_carousel(-1, 1000, 800)[4], 0)

    def test_cards_past_the_reach_are_left_off(self):
        self.assertIsNone(stage.place_carousel(stage.CAROUSEL_REACH + 1, 1000, 800))


class BubblesTest(unittest.TestCase):
    def test_first_bubble_floats_in_the_middle(self):
        x, y = stage.place_bubble(0, 50, 1000, 800)
        self.assertLess(math.hypot(x - 500, y - 400), 80)

    def test_later_bubbles_are_further_out(self):
        near = stage.place_bubble(1, 50, 1000, 800)
        far = stage.place_bubble(45, 50, 1000, 800)
        self.assertLess(math.hypot(near[0] - 500, near[1] - 400), math.hypot(far[0] - 500, far[1] - 400))

    def test_arrows_go_to_the_nearest_bubble_that_way(self):
        points = [(0, 0), (10, 0), (100, 0), (0, 10), (-10, 1)]
        self.assertEqual(stage.nearest(points, 0, "right"), 1)
        self.assertEqual(stage.nearest(points, 0, "down"), 3)
        self.assertEqual(stage.nearest(points, 0, "left"), 4)

    def test_no_bubble_that_way_stays_put(self):
        self.assertEqual(stage.nearest([(0, 0), (10, 0)], 0, "up"), 0)

    def test_burst_flies_out_and_fades(self):
        self.assertEqual(stage.burst(0, 100), (0, 1))
        self.assertEqual(stage.burst(1, 100), (100, 0))
        self.assertGreater(stage.burst(0.5, 100)[0], 50)  # fast at first, slowing as it goes

    def test_pop_in_ends_at_full_size(self):
        self.assertAlmostEqual(stage.ease_out_back(1), 1)
        self.assertAlmostEqual(stage.ease_out_back(0), 0)


if __name__ == "__main__":
    unittest.main()
