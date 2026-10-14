"""Tests for setup.sh (model choice, enable/disable) and the agent without a vision model."""

import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ASSISTANT = Path(__file__).resolve().parent.parent


class SetupScript(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="setup-test-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        self.local = self.home / "user_settings.local.toml"
        self.env = {**os.environ, "HOME": str(self.home), "XDG_STATE_HOME": str(self.home / "state"),
                    "ASSISTANT_LOCAL_SETTINGS": str(self.local)}
        self.env.pop("HYPR_ASSISTANT", None)
        self.marker = self.home / "state" / "hypr_agent" / "disabled"
        # Run a copy so the machine's own agent_context.md is never touched
        self.assistant = self.home / "assistant"
        self.assistant.mkdir()
        for name in ("setup.sh", "agent_context.example.md"):
            shutil.copy(ASSISTANT / name, self.assistant / name)

    def setup(self, *args, env=None):
        return subprocess.run(
            ["bash", str(self.assistant / "setup.sh"), "--no-pull", "--no-packages", "--no-services", *args],
            env={**self.env, **(env or {})}, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
        )

    def settings(self):
        return tomllib.loads(self.local.read_text())

    def test_tiers_write_models(self):
        for tier, chat, vision in (("full", "gpt-oss:20b", "qwen2.5vl:7b"),
                                   ("balanced", "qwen3:8b", "qwen2.5vl:3b"),
                                   ("light", "qwen3:4b", "")):
            result = self.setup("--tier", tier)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.settings()["assistant"], {"model": chat, "vision_model": vision}, tier)

    def test_custom_models_and_existing_content_preserved(self):
        self.local.write_text('# mine\n[calendar]\nsources = ["A|http://x"]\n\n[assistant]\naccent = "35"\nmodel = "old"\n')
        result = self.setup("--model", "qwen3:14b", "--vision-model", "none")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.settings()
        self.assertEqual(data["assistant"], {"accent": "35", "model": "qwen3:14b", "vision_model": ""})
        self.assertEqual(data["calendar"]["sources"], ["A|http://x"])
        self.assertIn("# mine", self.local.read_text())
        self.assertEqual(oct(self.local.stat().st_mode & 0o777), "0o600")

    def test_none_disables_and_enabling_reverses(self):
        self.assertEqual(self.setup("--none").returncode, 0)
        self.assertTrue(self.marker.exists())
        self.assertFalse(self.local.exists(), "disabling must not write model settings")
        self.assertEqual(self.setup("--tier", "light").returncode, 0)
        self.assertFalse(self.marker.exists())

    def test_unattended_env_choice(self):
        self.assertEqual(self.setup(env={"HYPR_ASSISTANT": "none"}).returncode, 0)
        self.assertTrue(self.marker.exists())

    def test_dry_run_changes_nothing(self):
        result = self.setup("--tier", "full", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dry-run", result.stdout)
        self.assertFalse(self.local.exists())
        self.assertFalse(self.marker.exists())

    def test_context_template_is_installed_once_and_never_overwritten(self):
        mine = self.assistant / "agent_context.md"
        self.assertEqual(self.setup("--tier", "light").returncode, 0)
        self.assertEqual(mine.read_text(), (self.assistant / "agent_context.example.md").read_text())
        mine.write_text("my own machine details\n")
        self.assertEqual(self.setup("--tier", "balanced").returncode, 0)
        self.assertEqual(mine.read_text(), "my own machine details\n")

    def test_no_context_when_assistant_is_off(self):
        self.assertEqual(self.setup("--none").returncode, 0)
        self.assertFalse((self.assistant / "agent_context.md").exists())

    def test_bad_input_is_rejected(self):
        self.assertNotEqual(self.setup("--tier", "huge").returncode, 0)
        self.assertNotEqual(self.setup("--bogus").returncode, 0)


class ContextFile(unittest.TestCase):
    def profile(self, with_own):
        root = Path(tempfile.mkdtemp(prefix="agent-context-"))
        self.addCleanup(shutil.rmtree, root, True)
        assistant = root / "assistant"
        assistant.mkdir()
        for name in ("hypr_agent.py", "usersettings.py"):
            shutil.copy(ASSISTANT / name, assistant / name)
        (assistant / "agent_context.example.md").write_text("TEMPLATE TEXT")
        if with_own:
            (assistant / "agent_context.md").write_text("MY OWN TEXT")
        code = "import hypr_agent as a;print(a.build_context())"
        result = subprocess.run([sys.executable, "-I", "-c", f"import sys;sys.path.insert(0,{str(assistant)!r});" + code],
                                capture_output=True, text=True, timeout=60,
                                env={**os.environ, "HOME": str(root), "XDG_STATE_HOME": str(root / "state")})
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_own_file_wins_and_template_is_the_fallback(self):
        own = self.profile(True)
        self.assertIn("MY OWN TEXT", own)
        self.assertNotIn("TEMPLATE TEXT", own)
        self.assertIn("TEMPLATE TEXT", self.profile(False))


class AgentWithoutVision(unittest.TestCase):
    """Run the agent against a settings file with and without a vision model."""

    def names(self, vision):
        root = Path(tempfile.mkdtemp(prefix="agent-settings-"))
        self.addCleanup(shutil.rmtree, root, True)
        assistant = root / "assistant"
        assistant.mkdir()
        for name in ("hypr_agent.py", "usersettings.py"):
            shutil.copy(ASSISTANT / name, assistant / name)
        (root / "user_settings.toml").write_text(f'[assistant]\nvision_model = "{vision}"\n')
        code = ("import hypr_agent as a;"
                "print(sorted(t['function']['name'] for t in a.TOOL_SCHEMAS));"
                "print(sorted(a.tools));print(a.VISION_ENABLED);"
                "print('ask_about_image' in a.SYSTEM_PROMPT);"
                "print(a.cmd_paste())")
        result = subprocess.run([sys.executable, "-I", "-c", f"import sys;sys.path.insert(0,{str(assistant)!r});" + code],
                                capture_output=True, text=True, timeout=60,
                                env={**os.environ, "HOME": str(root), "XDG_STATE_HOME": str(root / "state")})
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_vision_off(self):
        for value in ("", "none"):
            schemas, tools, enabled, prompt_mentions, paste = self.names(value)
            self.assertNotIn("screenshot_analysis", schemas)
            self.assertNotIn("ask_about_image", schemas)
            self.assertNotIn("ask_about_image", tools)
            self.assertEqual(enabled, "False")
            self.assertEqual(prompt_mentions, "False")
            self.assertIn("No vision model", paste)

    def test_vision_on(self):
        schemas, tools, enabled, prompt_mentions, _ = self.names("qwen2.5vl:3b")
        self.assertIn("screenshot_analysis", schemas)
        self.assertEqual(enabled, "True")
        self.assertEqual(prompt_mentions, "True")


if __name__ == "__main__":
    unittest.main()
