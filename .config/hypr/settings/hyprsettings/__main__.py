import os
import sys

# The GTK window when there is a desktop to show it on; the terminal version with --tui, or over SSH.
if "--tui" in sys.argv or not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    from .tui import main

    sys.exit(main())

from .gui.app import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
