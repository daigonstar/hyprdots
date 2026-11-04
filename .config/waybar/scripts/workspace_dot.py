#!/usr/bin/env python3
"""One workspace's dot on the bar: prints its state whenever a workspace or window changes. The bar's own hyprland/workspaces
module cannot switch workspace on the Lua config: it sends "dispatch workspace 2", which Hyprland now rejects. Its dots show, but
tapping or clicking them does nothing. So each dot here is a custom module whose on-click sends the Lua form (see waybar/config).
Usage: workspace_dot.py <number>"""
import json
import os
import socket
import subprocess
import sys

ACTIVE, DEFAULT = '\uf192', '\uf10c'
REDRAW_ON = (b"workspace", b"focusedmon", b"createworkspace", b"destroyworkspace", b"openwindow", b"closewindow", b"movewindow")


def state(number: int) -> dict:
    def ask(what):
        return json.loads(subprocess.run(["hyprctl", what, "-j"], capture_output=True, text=True, timeout=5).stdout or "null")
    active = (ask("activeworkspace") or {}).get("id")
    used = any(w.get("id") == number and w.get("windows") for w in ask("workspaces") or [])
    kind = "active" if active == number else "occupied" if used else "empty"
    return {"text": ACTIVE if kind == "active" else DEFAULT, "class": kind, "tooltip": f"Workspace {number}"}


def main() -> None:
    number = int(sys.argv[1])
    print(json.dumps(state(number)), flush=True)
    path = f"{os.environ['XDG_RUNTIME_DIR']}/hypr/{os.environ['HYPRLAND_INSTANCE_SIGNATURE']}/.socket2.sock"
    with socket.socket(socket.AF_UNIX) as events:
        events.connect(path)
        buffer = b""
        while chunk := events.recv(4096):
            buffer += chunk
            lines = buffer.split(b"\n")
            buffer = lines.pop()
            if any(line.startswith(REDRAW_ON) for line in lines):
                print(json.dumps(state(number)), flush=True)


if __name__ == "__main__":
    main()
