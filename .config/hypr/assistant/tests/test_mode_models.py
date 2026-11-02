"""Each mode can answer with its own model, picked on the Settings page ([assistant_modes] in user_settings.toml).

    cd ~/hyprdots/.config/hypr/assistant && python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sandbox  # noqa: E402,F401  (must come before hypr_agent)
import hypr_agent as a  # noqa: E402
import agent_modes  # noqa: E402


class ModeModels(unittest.TestCase):
    def setUp(self):
        saved = dict(agent_modes.STATE)
        self.addCleanup(agent_modes.STATE.update, saved)

    def use(self, mode):
        agent_modes.STATE.update(name=mode, arg="")

    def test_the_mode_picked_in_settings_wins(self):
        self.use("gaming")
        self.assertEqual(agent_modes.model("chat:14b", {"gaming": "fast:4b"}), "fast:4b")
        self.assertEqual(agent_modes.model("chat:14b", {"gaming": "  "}), "chat:14b")    # empty = the chat model
        self.assertEqual(agent_modes.model("chat:14b", {"external": "other:8b"}), "chat:14b")
        self.assertEqual(agent_modes.model("chat:14b", {"gaming": 3}), "chat:14b")       # not a name: ignored

    def test_a_mode_can_name_its_own_model(self):
        self.use("gaming")
        with mock.patch.dict(agent_modes.MODES["gaming"], {"model": "mode-default:8b"}):
            self.assertEqual(agent_modes.model("chat:14b", {}), "mode-default:8b")
            self.assertEqual(agent_modes.model("chat:14b", {"gaming": "picked:4b"}), "picked:4b")

    def test_local_uses_the_chat_model(self):
        self.use("local")
        self.assertEqual(agent_modes.model("chat:14b", {"external": "other:8b"}), "chat:14b")

    def test_requests_go_to_the_modes_model(self):
        self.use("external")
        seen = []
        reply = {"message": {"role": "assistant", "content": "ok"}}
        with mock.patch.dict(a.MODE_MODELS, {"external": "support:8b"}), \
                mock.patch.object(a, "chat", lambda model, *args, **kw: seen.append(model) or reply):
            a._ask([{"role": "user", "content": "hi"}], "hi")
            self.assertEqual(seen, ["support:8b"])
            self.assertIn("support:8b", a.cmd_mode("external"))
            self.use("local")
            a._ask([{"role": "user", "content": "hi"}], "hi")
            self.assertEqual(seen[-1], a.MODEL)

    def test_vision_same_still_means_the_main_chat_model(self):
        self.use("external")
        with mock.patch.dict(a.MODE_MODELS, {"external": "support:8b"}), mock.patch.object(a, "VISION_SAME", True):
            self.assertEqual(a.vision_model(), a.MODEL)


if __name__ == "__main__":
    unittest.main()
