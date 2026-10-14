"""Imported first by every test module: points $HOME and the state directory at a scratch folder
*before* hypr_agent is imported, because the agent reads both at import time. Refuses to continue if the
agent still sees the real home, so a test can never touch the user's files."""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

REAL_HOME = os.path.realpath(os.path.expanduser("~"))
FAKE_HOME = os.path.realpath(tempfile.mkdtemp(prefix="hypr-agent-home-"))
if "hypr_agent" not in sys.modules:
    atexit.register(shutil.rmtree, FAKE_HOME, ignore_errors=True)
    os.environ["HOME"] = FAKE_HOME
    os.environ["XDG_STATE_HOME"] = os.path.join(FAKE_HOME, "state")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hypr_agent  # noqa: E402

if hypr_agent.HOME == REAL_HOME or not hypr_agent.HOME.startswith(tempfile.gettempdir()):
    raise SystemExit(f"Refusing to run: hypr_agent sees HOME={hypr_agent.HOME}, not a scratch directory. "
                     "Import _sandbox before hypr_agent.")
