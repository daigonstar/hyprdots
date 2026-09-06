#!/usr/bin/env python3
"""
game-autoworkspace.py

Watches Hyprland's IPC event stream for newly opened windows and, when a
window looks like it belongs to a game (launched via Steam, Lutris, Heroic,
or a bare Wine/Proton/gamescope/gamemode wrapper), moves it to workspace 3
and makes it fullscreen - regardless of what window class the game itself
reports (Wine/Proton games don't share a common class, so a plain
class-regex window rule can't catch "all games" the way it can for Steam).

Steam's own games are already handled instantly by a static window rule in
window.lua (matching class ^steam_app_.*$), so this daemon mainly exists for
Lutris/Heroic and any other launcher, but it double-checks Steam-launched
processes too since that's a harmless no-op if the static rule already did
the job.

Launcher UI windows themselves (the Steam client, the Lutris library, the
Heroic library) are explicitly excluded so only the actual game windows get
redirected.

It also remembers which workspace was active right before each game window
appeared, and switches back to it once the game closes - but only if the
user is still sitting on the games workspace at that point (if they've
already navigated elsewhere themselves, we don't yank focus away from
whatever they're doing), and only once every tracked game window has closed
(so quitting one of several simultaneously-running games doesn't switch
away while others are still up).
"""

import json
import os
import re
import socket
import subprocess
import sys
import time

# Window classes that are the launcher's own UI, not a game - never redirect these.
EXCLUDED_CLASSES = {
    "steam",
    "com.heroicgameslauncher.hgl",
    "net.lutris.lutris",
}

# Process names (exact, case-insensitive) anywhere in the parent chain that
# indicate the window belongs to a game.
COMM_HINTS = {
    "wine", "wine64", "wineserver", "wine-preloader", "wineboot",
    "lutris", "lutris-wrapper",
    "heroic", "legendary", "gogdl", "nile",
    "gamemoderun", "gamemoded",
    "umu-run", "umu_run",
    "gamescope",
    "steam",
}

# Substrings (case-insensitive) checked against the full cmdline of each
# ancestor process, for wrappers that don't set a distinctive comm (e.g.
# Proton is invoked as `python3 .../proton run ...`).
CMDLINE_HINTS = (
    "proton",
    "/steamapps/common/",
    "wineprefix",
    "compatibilitytools.d",
    "lutris",
    "heroic",
    "/.wine/",
    "legendary",
    "gogdl",
    "wine",
    "gamemoderun",
    "umu-run",
)

MAX_ANCESTRY_DEPTH = 25
TARGET_WORKSPACE = 3

# address -> workspace id the user was on right before that game window opened.
tracked_games = {}


def log(msg):
    print(f"[game-autoworkspace] {msg}", flush=True)


def get_socket_path():
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        # Fall back to discovering the (only) running instance.
        base = os.path.join(runtime_dir, "hypr")
        sigs = [d for d in os.listdir(base)] if os.path.isdir(base) else []
        if not sigs:
            raise RuntimeError("Could not determine Hyprland instance signature")
        sig = sigs[0]
    return os.path.join(runtime_dir, "hypr", sig, ".socket2.sock")


def read_proc_field(pid, field):
    try:
        with open(f"/proc/{pid}/{field}", "rb") as f:
            return f.read()
    except OSError:
        return b""


def get_ppid(pid):
    stat = read_proc_field(pid, "stat").decode(errors="replace")
    # comm can contain spaces/parens, so parse after the last ')'
    try:
        after = stat.rsplit(")", 1)[1].split()
        return int(after[1])
    except (IndexError, ValueError):
        return None


def process_looks_like_game(pid):
    """Walk up the process ancestry from pid, looking for game-launcher hints."""
    current = pid
    for _ in range(MAX_ANCESTRY_DEPTH):
        if current is None or current <= 1:
            return False

        comm = read_proc_field(current, "comm").decode(errors="replace").strip().lower()
        if comm in COMM_HINTS:
            return True

        cmdline = read_proc_field(current, "cmdline").decode(errors="replace").lower()
        if any(hint in cmdline for hint in CMDLINE_HINTS):
            return True

        current = get_ppid(current)

    return False


def find_client_by_address(address):
    try:
        out = subprocess.run(
            ["hyprctl", "-j", "clients"], capture_output=True, check=True, timeout=5
        ).stdout
        clients = json.loads(out)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return None

    for client in clients:
        if client.get("address") == address:
            return client
    return None


def get_active_workspace_id():
    try:
        out = subprocess.run(
            ["hyprctl", "-j", "activeworkspace"], capture_output=True, check=True, timeout=5
        ).stdout
        return json.loads(out).get("id")
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return None


def route_to_workspace_3(address):
    selector = f"address:{address}"
    subprocess.run(
        ["hyprctl", "dispatch", f'hl.dsp.window.move({{ workspace = {TARGET_WORKSPACE}, window = "{selector}" }})'],
        capture_output=True,
    )
    subprocess.run(
        ["hyprctl", "dispatch", f'hl.dsp.window.fullscreen({{ window = "{selector}" }})'],
        capture_output=True,
    )


def handle_open_window(payload):
    # openwindow>>ADDRESS,WORKSPACE_NAME,CLASS,TITLE (title may contain commas)
    parts = payload.split(",", 3)
    if len(parts) < 3:
        return
    address, _workspace_name, window_class = parts[0], parts[1], parts[2]

    if window_class.strip().lower() in EXCLUDED_CLASSES:
        return

    normalized_address = f"0x{address}" if not address.startswith("0x") else address
    client = find_client_by_address(normalized_address)
    if client is None:
        return

    if client.get("class", "").strip().lower() in EXCLUDED_CLASSES:
        return

    pid = client.get("pid")
    if not pid:
        return

    if process_looks_like_game(pid):
        origin_workspace = get_active_workspace_id()
        log(f"detected game window class={window_class!r} pid={pid}, routing to workspace {TARGET_WORKSPACE}"
            f" (will return to workspace {origin_workspace} on close)")
        tracked_games[client["address"]] = origin_workspace
        route_to_workspace_3(client["address"])


def handle_close_window(address):
    normalized_address = f"0x{address}" if not address.startswith("0x") else address
    if normalized_address not in tracked_games:
        return

    origin_workspace = tracked_games.pop(normalized_address)

    # Other tracked games are still open - don't switch away from workspace 3 yet.
    if tracked_games:
        return

    if origin_workspace is None:
        return

    # Only restore focus if the user is still on the games workspace; if they
    # already navigated elsewhere themselves, leave them where they are.
    if get_active_workspace_id() != TARGET_WORKSPACE:
        return

    log(f"last tracked game closed, returning to workspace {origin_workspace}")
    subprocess.run(
        ["hyprctl", "dispatch", f'hl.dsp.focus({{ workspace = {origin_workspace} }})'],
        capture_output=True,
    )


def listen_forever():
    sock_path = get_socket_path()
    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(sock_path)
                buf = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.decode(errors="replace").strip()
                        if line.startswith("openwindow>>"):
                            try:
                                handle_open_window(line[len("openwindow>>"):])
                            except Exception as exc:  # keep the daemon alive on unexpected errors
                                log(f"error handling event: {exc}")
                        elif line.startswith("closewindow>>"):
                            try:
                                handle_close_window(line[len("closewindow>>"):])
                            except Exception as exc:
                                log(f"error handling close event: {exc}")
        except (OSError, RuntimeError) as exc:
            log(f"socket error ({exc}), retrying in 3s")
            time.sleep(3)


if __name__ == "__main__":
    listen_forever()
