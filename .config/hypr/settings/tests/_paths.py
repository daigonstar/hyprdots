import shutil
import sys
import tempfile
from pathlib import Path

SETTINGS = Path(__file__).resolve().parent.parent
HYPR = SETTINGS.parent
sys.path.insert(0, str(SETTINGS))


def scratch_hypr_dir() -> Path:
    """A throwaway copy of the files the app reads, so tests never touch the real config."""
    d = Path(tempfile.mkdtemp(prefix="hypr-settings-test-"))
    for name in ("user_settings.toml", "autostart.lua"):
        shutil.copy(HYPR / name, d / name)
    return d
