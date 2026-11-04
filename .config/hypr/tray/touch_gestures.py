"""Touchscreen gestures, for tablet_mode.py (Hyprland's own gestures are for touchpads). Swipe up from the bottom edge for the
launcher; two fingers across to change workspace; hold a window with two fingers to pick it up, and let go on the bin that
appears to close it (touch_lift.py). The hold is what tells that last one from zooming or scrolling.
One finger still reaches the app as well, as this only listens. Two fingers belong to the desktop: while they are down Hyprland
stops passing touches on, or apps would open a right-click menu for the hold. install/70-hyprdots-touchscreen.rules lets your session read the
touchscreen and nothing else, so no program needs the input group, which could read every key you press."""
import fcntl
import json
import os
import struct
import subprocess
import time
from pathlib import Path

EDGE = 36           # how close to the bottom a swipe up must start
SWIPE_UP = 100      # how far it must go
SWIPE_ACROSS = 90   # how far two fingers must go
HOLD_SECONDS = 1.0  # how long two fingers must rest to pick a window up
SLOP = 40           # moving less than this is still holding: fingers wobble
BAR_DEFAULT = 44
LAUNCHER_WAIT = 2.0  # a second swipe while it is still appearing would close it again: running it twice toggles it

EV_SYN, EV_ABS = 0, 3
SYN_REPORT, SYN_DROPPED = 0, 3
ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID = 0x2f, 0x35, 0x36, 0x39
EVENT = struct.Struct("qqHHi")


def to_screen(u: float, v: float, transform: int, width: float, height: float) -> tuple[float, float]:
    """A touch on the panel (0 to 1 across its own sides) to a point on the screen as turned. width and height are the
    screen's as turned. Hyprland's transforms turn the picture anticlockwise."""
    x, y = {0: (u, v), 1: (1 - v, u), 2: (1 - u, 1 - v), 3: (v, 1 - u)}.get(transform, (u, v))
    return x * width, y * height


class Gestures:
    """Works in screen points. act(name, *where) is told what was done: "launcher", "next", "previous", then "pickup", any
number of "carry" and a "drop", each with where the fingers are."""

    def __init__(self, act):
        self.act = act
        self.apps_touch = lambda on: None  # whether apps get touches: replaced by open_touchscreen
        self.height = 0.0
        self.bar = BAR_DEFAULT
        self.fingers: dict[int, tuple[float, float]] = {}
        self.begun: dict[int, tuple[float, float]] = {}
        self.reset()

    def reset(self) -> None:
        self.most = 0
        self.done = False
        self.resting_since = 0.0
        self.moved = False
        self.carrying = False
        self.last = (0.0, 0.0)

    def down(self, slot: int, x: float, y: float, now: float) -> None:
        if not self.fingers:
            self.reset()
        self.fingers[slot] = self.begun[slot] = (x, y)
        for other, where in self.fingers.items():  # measured from when the last finger lands: the first may have shifted by then
            self.begun[other] = where
        self.resting_since = now
        if len(self.fingers) == 2:
            self.apps_touch(False)
        self.most = max(self.most, len(self.fingers))

    def move(self, slot: int, x: float, y: float) -> None:
        if slot in self.fingers:
            self.fingers[slot] = (x, y)

    def middle(self) -> tuple[float, float]:
        return sum(p[0] for p in self.fingers.values()) / len(self.fingers), sum(p[1] for p in self.fingers.values()) / len(self.fingers)

    def up(self, slot: int) -> None:
        self.fingers.pop(slot, None)
        if self.fingers:
            return
        if self.most >= 2:
            self.apps_touch(True)
        if self.carrying:
            self.carrying = False
            self.done = True
            self.act("drop", *self.last)

    def frame(self, now: float) -> None:
        """After a set of changes from the screen, and on a timer while fingers are down: resting fingers send nothing."""
        if not self.fingers:
            return
        if self.carrying:
            middle = self.middle()
            if middle != self.last:
                self.last = middle
                self.act("carry", *middle)
        elif self.done:
            return
        elif self.most == 1:
            self.one_finger(next(iter(self.fingers)))
        elif self.most == 2 and len(self.fingers) == 2:
            self.two_fingers(now)

    def one_finger(self, slot: int) -> None:
        y, start_y = self.fingers[slot][1], self.begun[slot][1]
        if start_y >= self.height - EDGE and start_y - y >= SWIPE_UP:
            self.done = True
            self.act("launcher")

    def two_fingers(self, now: float) -> None:
        across, along = [], []
        for slot, (x, y) in self.fingers.items():
            start_x, start_y = self.begun[slot]
            across.append(x - start_x)
            along.append(y - start_y)
        same_way = across[0] * across[1] > 0
        far = min(abs(a) for a in across) >= SWIPE_ACROSS
        straight = all(abs(a) > 1.5 * abs(b) for a, b in zip(across, along))
        if same_way and far and straight:
            self.done = True
            self.act("next" if across[0] < 0 else "previous")
        elif max(abs(a) for a in across + along) > SLOP:
            self.moved = True
        elif not self.moved and now - self.resting_since >= HOLD_SECONDS:
            self.carrying = True
            self.last = self.middle()
            self.act("pickup", *self.last)


def client_at(clients: list[dict], workspace: int, x: float, y: float) -> dict | None:
    """The top window under a point on that workspace."""
    under = [c for c in clients if c.get("workspace", {}).get("id") == workspace and c.get("mapped", True) and not c.get("hidden")
             and c["at"][0] <= x < c["at"][0] + c["size"][0] and c["at"][1] <= y < c["at"][1] + c["size"][1]]
    under.sort(key=lambda c: (not c.get("floating"), c.get("focusHistoryID", 0)))
    return under[0] if under else None


def hypr_json(what: str):
    try:
        return json.loads(subprocess.run(["hyprctl", what, "-j"], capture_output=True, text=True, timeout=5).stdout or "null")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def dispatch(lua: str) -> None:
    subprocess.Popen(["hyprctl", "dispatch", lua], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def built_in(monitors) -> dict | None:
    return next((m for m in monitors or [] if m.get("name", "").startswith(("eDP", "LVDS", "DSI"))), None)


launcher_opened = [-LAUNCHER_WAIT]


def set_apps_touch(on: bool) -> None:
    """Whether Hyprland passes touches on to apps. This reads the device itself, so it carries on seeing them either way."""
    names = [d["name"] for d in (hypr_json("devices") or {}).get("touch", [])]
    for name in names:
        subprocess.Popen(["hyprctl", "eval", f'hl.device({{ name = "{name}", enabled = {"true" if on else "false"} }})'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def perform(action: str) -> None:
    print(f"Gesture: {action}", flush=True)  # journalctl --user -u hyprdots-tablet
    if action == "launcher":
        if time.monotonic() - launcher_opened[0] < LAUNCHER_WAIT:
            return
        launcher_opened[0] = time.monotonic()
        # Hyprland starts it, as for Super+Space: started from here, every app opened from it would belong to this service
        # and go when it restarts
        dispatch('hl.dsp.exec_cmd("~/.config/hypr/launcher/launcher.sh")')
    elif action in ("next", "previous"):
        # r, not the e of Super+scroll: e only visits workspaces with windows, so with them all on one a swipe would do nothing
        dispatch(f'hl.dsp.focus({{ workspace = "r{"+" if action == "next" else "-"}1" }})')


def find_touchscreen() -> str | None:
    for path in sorted(Path("/sys/class/input").glob("event*")):
        node = f"/dev/input/{path.name}"
        info = subprocess.run(["udevadm", "info", "-q", "property", node], capture_output=True, text=True).stdout
        if "ID_INPUT_TOUCHSCREEN=1" in info:
            return node
    return None


class TouchReader:
    """Reads the touchscreen's multi-touch events and feeds Gestures. feed() takes what came out of the device."""

    def __init__(self, gestures: Gestures, x_range: tuple[int, int], y_range: tuple[int, int]):
        self.gestures = gestures
        self.x_range, self.y_range = x_range, y_range
        self.transform, self.width, self.height = 0, 0.0, 0.0
        self.slot = 0
        self.raw: dict[int, list[int]] = {}
        self.changed: dict[int, str] = {}
        self.lost = False
        self.slots_down = set  # replaced by open_touchscreen with a question to the screen

    def set_screen(self, screen: dict) -> None:
        self.transform = screen.get("transform", 0)
        width, height = screen["width"] / screen["scale"], screen["height"] / screen["scale"]
        self.width, self.height = (height, width) if self.transform % 2 else (width, height)
        self.gestures.height = self.height
        self.gestures.bar = (screen.get("reserved") or [0, BAR_DEFAULT])[1] or BAR_DEFAULT

    def point(self, slot: int) -> tuple[float, float]:
        raw_x, raw_y = self.raw[slot]
        u = (raw_x - self.x_range[0]) / max(1, self.x_range[1] - self.x_range[0])
        v = (raw_y - self.y_range[0]) / max(1, self.y_range[1] - self.y_range[0])
        return to_screen(u, v, self.transform, self.width, self.height)

    def catch_up(self) -> None:
        """Events were lost, perhaps a finger leaving, which would leave it down here for good and every gesture stuck."""
        down = self.slots_down()
        print("Gesture: touch events were lost, caught up", flush=True)
        for slot in [s for s in self.gestures.fingers if s not in down]:
            self.gestures.up(slot)
        for slot in [s for s in self.raw if s not in down]:
            self.raw.pop(slot)

    def event(self, kind: int, code: int, value: int, now: float) -> None:
        if kind == EV_SYN and code == SYN_DROPPED:
            self.lost = True
            self.changed.clear()
        elif self.lost:  # the kernel says to ignore all up to the next report
            if kind == EV_SYN and code == SYN_REPORT:
                self.lost = False
                self.catch_up()
        elif kind == EV_ABS:
            if code == ABS_MT_SLOT:
                self.slot = value
            elif code == ABS_MT_TRACKING_ID:
                self.changed[self.slot] = "up" if value < 0 else "down"
                if value >= 0:
                    self.raw.setdefault(self.slot, [0, 0])
            elif code in (ABS_MT_POSITION_X, ABS_MT_POSITION_Y) and self.slot in self.raw:
                self.raw[self.slot][code - ABS_MT_POSITION_X] = value
                self.changed.setdefault(self.slot, "move")
        elif kind == EV_SYN and code == SYN_REPORT:
            for slot, change in self.changed.items():
                if change == "up":
                    self.gestures.up(slot)
                    self.raw.pop(slot, None)
                elif change == "down":
                    self.gestures.down(slot, *self.point(slot), now)
                else:
                    self.gestures.move(slot, *self.point(slot))
            self.changed.clear()
            self.gestures.frame(now)


def axis_range(fd: int, code: int) -> tuple[int, int]:
    request = (2 << 30) | (24 << 16) | (ord("E") << 8) | (0x40 + code)  # EVIOCGABS
    _value, low, high, *_rest = struct.unpack("6i", fcntl.ioctl(fd, request, bytes(24)))
    return low, high


def slots_down(fd: int) -> set[int]:
    """Which fingers the screen says are on it now."""
    slots = axis_range(fd, ABS_MT_SLOT)[1] + 1
    size = 4 * (slots + 1)
    request = (2 << 30) | (size << 16) | (ord("E") << 8) | 0x0a  # EVIOCGMTSLOTS
    data = fcntl.ioctl(fd, request, struct.pack("i", ABS_MT_TRACKING_ID) + bytes(4 * slots))
    return {slot for slot, tracking in enumerate(struct.unpack(f"{slots}i", data[4:])) if tracking >= 0}


def open_touchscreen() -> tuple[int, TouchReader] | None:
    """None when there is none, or this session may not read it (the udev rule is not installed)."""
    node = find_touchscreen()
    if not node:
        return None
    try:
        fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    reader = TouchReader(Gestures(perform), axis_range(fd, ABS_MT_POSITION_X), axis_range(fd, ABS_MT_POSITION_Y))
    reader.slots_down = lambda: slots_down(fd)
    reader.gestures.apps_touch = set_apps_touch
    set_apps_touch(True)  # in case the last run ended with two fingers down
    return fd, reader


def read_events(fd: int, reader: TouchReader) -> bool:
    """What the main loop calls when the device has something. False to stop watching it."""
    try:
        data = os.read(fd, EVENT.size * 64)
    except BlockingIOError:
        return True
    except OSError:
        return False
    now = time.time()  # the same clock as the timer in tablet_mode.py, not the event's own
    for _seconds, _micros, kind, code, value in EVENT.iter_unpack(data[:len(data) - len(data) % EVENT.size]):
        reader.event(kind, code, value, now)
    return True
