"""The wallpaper picker (Super+W, the bar's wallpaper button): the launcher's Categories layout, for wallpapers.

Pictures and animated wallpapers (GIFs and videos) each have a category. The one you are on is shown inside a little
monitor that wraps around it, with its stand rising underneath; an animated one plays a short preview on that screen.
It takes the launcher's stylesheet (launcher.css), so the Theme page's colours and every theme override restyle it too.

Setting a wallpaper goes through rofi/wallpaper/wallpaper.sh --apply, the same path as before: awww and wallust for a
picture or GIF, video-wallpaper.sh for a video. Thumbnails and previews are made with ffmpeg and kept in
~/.cache/hyprdots/wallpicker."""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import threading
import zlib
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "settings"))

HOME = Path.home()
WALLS = HOME / "Pictures" / "wallpapers"
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache") / "hyprdots" / "wallpicker"
APPLY = HOME / ".config" / "rofi" / "wallpaper" / "wallpaper.sh"
CURRENT = HOME / ".config" / "rofi" / ".current_wallpaper"
CURRENT_VIDEO = HOME / ".config" / "rofi" / ".current_video"

STILL = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
GIF = {".gif"}
VIDEO = {".mp4", ".mkv", ".mov", ".webm"}
KINDS = {"still": "Picture", "gif": "GIF", "video": "Video"}

# (name, glyph, the kinds it holds)
CATEGORIES = (("All", "\U000f02e9", ("still", "gif", "video")),
              ("Pictures", "\U000f021f", ("still",)),
              ("Animated", "\U000f0567", ("gif", "video")))
KEYS = [("Enter", "set"), ("←→↑↓", "move"), ("Tab", "category"), ("Ctrl+R", "surprise me"),
        ("Esc", "close")]
TILE_W = 252  # each little monitor's screen, in layout px; the height follows the real screen's shape


# ---- what is there ------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Wall:
    path: Path
    kind: str  # still, gif or video

    @property
    def name(self) -> str:
        return self.path.stem.replace("_", " ").replace("-", " ").strip() or self.path.name

    @property
    def animated(self) -> bool:
        return self.kind != "still"


def kind_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    return "still" if ext in STILL else "gif" if ext in GIF else "video" if ext in VIDEO else None


def scan(folder: Path = WALLS) -> list[Wall]:
    """Every wallpaper under folder (following links, as the old picker did), sorted by name."""
    found = []
    for root, _dirs, files in os.walk(folder, followlinks=True):
        for f in files:
            path = Path(root) / f
            kind = kind_of(path)
            try:
                empty = path.stat().st_size == 0
            except OSError:
                empty = True  # a broken link
            if kind and not empty:  # an empty file (a download that never finished) would only be a blank tile
                found.append(Wall(path, kind))
    return sorted(found, key=lambda w: (w.name.lower(), str(w.path)))


def in_category(walls: list[Wall], category: str) -> list[Wall]:
    kinds = next((k for name, _g, k in CATEGORIES if name == category), CATEGORIES[0][2])
    return [w for w in walls if w.kind in kinds]


def matching(walls: list[Wall], query: str) -> list[Wall]:
    """Walls whose name has every word of query, in any order ("night bliss" finds "Bliss night")."""
    words = query.lower().split()
    return [w for w in walls if all(word in w.name.lower() for word in words)]


def current() -> Path | None:
    """The wallpaper in use: the video when one is playing (its still stands in for it elsewhere), else the picture."""
    try:
        now = CURRENT.resolve(strict=True)
    except OSError:
        return None
    try:
        video = CURRENT_VIDEO.resolve(strict=True)
        if now.parent == CACHE.parent / "video-wallpapers" and now.name.startswith(video.stem + "-"):
            return video
    except OSError:
        pass
    return now


def surprise(walls: list[Wall], now: Path | None) -> Wall | None:
    """A random wallpaper, never the one already showing (unless it is the only one)."""
    others = [w for w in walls if w.path != now] or walls
    return random.choice(others) if others else None


# ---- thumbnails ---------------------------------------------------------------------------------------------------
def _key(path: Path, extra: str) -> str:
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = 0
    return f"{zlib.crc32(f'{path}|{stamp}|{extra}'.encode()):08x}"


def thumb_path(wall: Wall, w: int, h: int) -> Path:
    return CACHE / f"{_key(wall.path, f'{w}x{h}')}.jpg"


def preview_path(wall: Wall, w: int, h: int) -> Path:
    return CACHE / f"{_key(wall.path, f'{w}x{h}-preview')}.gif"


def _cover(w: int, h: int) -> str:
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"


def thumb_command(wall: Wall, out: Path, w: int, h: int) -> list[str]:
    """ffmpeg reads every kind: one frame, scaled to fill w x h and cropped, as the wallpaper fills a screen. A video's
    frame comes from a second in, like its still (the very first is often black)."""
    seek = ["-ss", "1"] if wall.kind == "video" else []
    return ["ffmpeg", "-loglevel", "error", "-y", *seek, "-i", str(wall.path), "-frames:v", "1", "-vf", _cover(w, h),
            "-q:v", "3", str(out)]


def preview_command(wall: Wall, out: Path, w: int, h: int) -> list[str]:
    """A short looping preview for the monitor's screen: four seconds at 12 frames a second, with its own palette."""
    graph = f"fps=12,{_cover(w, h)},split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer"
    return ["ffmpeg", "-loglevel", "error", "-y", "-t", "4", "-i", str(wall.path), "-filter_complex", graph,
            "-loop", "0", str(out)]


def make(cmd: list[str], out: Path) -> Path | None:
    if out.exists() and out.stat().st_size > 0:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + f".{os.getpid()}.{threading.get_ident()}{out.suffix}")
    try:
        subprocess.run(cmd[:-1] + [str(tmp)], capture_output=True, timeout=60)
        if tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, out)
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    tmp.unlink(missing_ok=True)
    if cmd and "-ss" in cmd:  # a video shorter than a second: try its first frame
        i = cmd.index("-ss")
        return make(cmd[:i] + cmd[i + 2:], out)
    return None


def wants_set(clicks: int, selected: bool) -> bool:
    """A click on the wallpaper already picked sets it, and so does a double-click on any; a single click on another
    only moves the monitor there, to see it first."""
    return clicks >= 2 or selected


def clean_env() -> dict:
    """The picker runs with gtk4-layer-shell preloaded (wallpicker.sh): what it starts must not inherit that. The
    video player is a layer-shell program of its own."""
    return {k: v for k, v in os.environ.items() if k != "LD_PRELOAD"}


def apply_command(wall: Wall) -> list[str]:
    cmd = ["bash", str(APPLY), "--apply", str(wall.path)]
    if shutil.which("systemd-run"):  # its own scope: a video player started from here must outlive the picker
        cmd = ["systemd-run", "--user", "--scope", "--collect", "--quiet", "--", *cmd]
    return cmd


# ---- the window ---------------------------------------------------------------------------------------------------
def css(c: dict, mix) -> str:
    """The picker's own parts, on top of the launcher's stylesheet: the tiles, and the monitor that is the cursor."""
    accent, text = c["accent"], c["base_text"]
    bezel = mix(c["base"], "#000000", 0.55)
    edge = mix(c["base"], text, 0.18)
    soft = lambda colour, a: f"alpha({colour}, {a})"  # noqa: E731
    return f"""
.wall {{ padding: 10px 6px 6px 6px; border-radius: 14px; transition: background-color 140ms ease-out; }}
.wall:hover {{ background: {soft(text, 0.05)}; }}
.monitor {{
    padding: 7px 7px 3px 7px; border-radius: 11px; border: 1px solid transparent; background: transparent;
    transition: background-color 200ms ease-out, border-color 200ms ease-out, box-shadow 220ms ease-out, transform 200ms ease-out;
}}
.screen picture {{ border-radius: 4px; }}
.chin {{ min-height: 9px; }}
.led {{ min-width: 5px; min-height: 5px; border-radius: 99px; margin-top: 2px; background: transparent;
        transition: background-color 200ms ease-out, box-shadow 200ms ease-out; }}
.neck {{ min-width: 30px; min-height: 13px; background: transparent; opacity: 0; transform: translateY(-10px);
         transition: opacity 180ms ease-out 60ms, transform 220ms cubic-bezier(0.2, 0.9, 0.3, 1.2) 60ms, background-color 200ms; }}
.foot {{ min-width: 104px; min-height: 6px; border-radius: 6px 6px 3px 3px; background: transparent; opacity: 0;
         transform: translateY(-14px) scaleX(0.6);
         transition: opacity 180ms ease-out 90ms, transform 240ms cubic-bezier(0.2, 0.9, 0.3, 1.2) 90ms, background-color 200ms; }}
.wall .name {{ margin-top: 6px; font-weight: 600; opacity: 0.75; }}
.badge {{
    margin: 6px; padding: 1px 7px; border-radius: 99px; font-size: 10px; font-weight: 800; letter-spacing: 1px;
    color: #ffffff; background: rgba(0, 0, 0, 0.55);
}}
.badge.using {{ color: {c['base']}; background: {accent}; }}
@keyframes wrap {{
    0% {{ transform: scale(0.93); box-shadow: 0px 0px 0px 0px {soft(accent, 0.0)}; }}
    60% {{ transform: scale(1.015); }}
    100% {{ transform: scale(1.0); }}
}}
.wall.selected .monitor {{
    background: {bezel}; border-color: {edge};
    box-shadow: 0px 14px 34px rgba(0, 0, 0, 0.5), 0px 0px 0px 1px {soft(accent, 0.35)}, 0px 0px 22px {soft(accent, 0.18)};
    animation: wrap 260ms cubic-bezier(0.2, 0.8, 0.2, 1);
}}
.wall.selected .led {{ background: {accent}; box-shadow: 0px 0px 6px {accent}; }}
.wall.selected .neck {{ opacity: 1; transform: none; background-image: linear-gradient(to bottom, {mix(bezel, '#000000', 0.3)}, {edge});
                       box-shadow: inset 1px 0px {soft(text, 0.08)}, inset -1px 0px {soft(text, 0.08)}; }}
.wall.selected .foot {{ opacity: 1; transform: none; background: {edge}; box-shadow: inset 0px 1px {soft(text, 0.25)},
                       0px 4px 10px rgba(0, 0, 0, 0.45), 0px 0px 12px {soft(accent, 0.15)}; }}
.unreadable {{ opacity: 0.55; font-size: 12px; }}
.screen {{ background: {soft(text, 0.04)}; border-radius: 4px; }}
.wall.selected .name {{ color: {accent}; opacity: 1; }}
.empty {{ opacity: 0.5; margin: 40px; }}
"""


def build(app, Gtk, Gdk, GLib, GdkPixbuf, Pango, Gtk4LayerShell):
    import launcher
    from hyprsettings import design, theme
    from hyprsettings.store import Store

    opts = launcher.settings()
    walls = scan()
    now = current()
    state = {"category": "All", "shown": [], "widgets": [], "index": 0, "pictures": {}, "playing": None}

    win = Gtk.ApplicationWindow(application=app)
    if Gtk4LayerShell.is_supported():
        Gtk4LayerShell.init_for_window(win)
        Gtk4LayerShell.set_namespace(win, "wallpicker")
        Gtk4LayerShell.set_layer(win, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_keyboard_mode(win, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
        Gtk4LayerShell.set_exclusive_zone(win, -1)
        for edge in (Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM, Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT):
            Gtk4LayerShell.set_anchor(win, edge, True)
    else:
        win.set_default_size(1300, 860)

    # the screen's shape decides the thumbnails' shape: each tile is that screen in miniature
    display = Gdk.Display.get_default()
    monitors = display.get_monitors()
    geo = monitors.get_item(0).get_geometry() if monitors.get_n_items() else None
    for i in range(monitors.get_n_items()):
        m = monitors.get_item(i)
        if m.get_connector() and os.environ.get("HYPRDOTS_MONITOR") == m.get_connector():
            geo = m.get_geometry()
    ratio = (geo.height / geo.width) if geo and geo.width else 9 / 16
    shown_w, shown_h = TILE_W, round(TILE_W * ratio)
    # the files are made at the size they are shown (GTK sizes a picture by its file), times the screen's scale
    zoom = max(1, monitors.get_item(0).get_scale_factor()) if monitors.get_n_items() else 1
    tw, th = shown_w * zoom, shown_h * zoom

    backdrop = Gtk.Box(css_classes=["backdrop"])
    win.set_child(backdrop)
    panel = Gtk.Box(css_classes=["panel", "categories", "surface"], overflow=Gtk.Overflow.HIDDEN,
                    halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, hexpand=True, vexpand=True)
    backdrop.append(panel)
    sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["sidebar"], width_request=210,
                      hexpand=False)
    panel.append(sidebar)
    main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["main"], hexpand=True, vexpand=True)
    panel.append(main)
    header = Gtk.Box(spacing=10, css_classes=["head"])
    entry = Gtk.SearchEntry(css_classes=["search"], hexpand=True, placeholder_text="Search wallpapers")
    header.append(entry)
    count = Gtk.Label(css_classes=["mode"], valign=Gtk.Align.CENTER)
    header.append(count)
    main.append(header)
    main.append(Gtk.Box(css_classes=["rule"]))
    view = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, valign=Gtk.Align.START,
                       min_children_per_line=2, max_children_per_line=4, column_spacing=8, row_spacing=8)
    scroller = Gtk.ScrolledWindow(child=view, hexpand=True, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    main.append(scroller)
    empty = Gtk.Label(css_classes=["empty"], label=f"No wallpapers here yet. Add pictures, GIFs or videos to {WALLS}.",
                      wrap=True, visible=False)
    main.append(empty)
    footer = Gtk.Box(spacing=5)
    action = Gtk.Label(css_classes=["action"], xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
    footer.append(action)
    for key, word in KEYS:
        footer.append(Gtk.Label(label=key, css_classes=["key"]))
        footer.append(Gtk.Label(label=word, css_classes=["hint"]))
    main.append(footer)
    footer.set_visible(bool(opts["hints"]))

    def size_panel(*_):
        surface = win.get_surface()
        mon = display.get_monitor_at_surface(surface) if surface else None
        g = (mon or monitors.get_item(0)).get_geometry()
        panel.set_size_request(min(max(int(g.width * 0.74), 1100), int(g.width * 0.96)), int(g.height * 0.74))
    win.connect("realize", size_panel)

    # ---- thumbnails, made in the background ----
    jobs = {"queue": [], "busy": 0}
    lock = threading.Lock()

    def worker():
        while True:
            with lock:
                if not jobs["queue"]:
                    jobs["busy"] -= 1
                    return
                wall = jobs["queue"].pop(0)
            out = make(thumb_command(wall, thumb_path(wall, tw, th), tw, th), thumb_path(wall, tw, th))
            GLib.idle_add(show_thumb, wall, out)

    def want_thumbs(items):
        with lock:
            jobs["queue"] = [w for w in items if not thumb_path(w, tw, th).exists()] + \
                [w for w in jobs["queue"] if w not in items]
            start = min(4, len(jobs["queue"])) - jobs["busy"]
            jobs["busy"] += max(0, start)
        for _ in range(max(0, start)):
            threading.Thread(target=worker, daemon=True).start()

    def show_thumb(wall, path):
        picture = state["pictures"].get(wall.path)
        if picture is None or state["playing"] == wall.path:
            return False
        if path:
            picture.set_filename(str(path))
        else:  # ffmpeg could not read it: say so on the screen instead of leaving it blank
            screen = picture.get_parent()
            if screen is not None:
                screen.add_overlay(Gtk.Label(label="Can't read this file", css_classes=["unreadable"],
                                             halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER))
        return False

    # ---- the animated preview on the selected monitor ----
    anim = {"iter": None, "timer": 0, "for": None}

    def stop_preview():
        if anim["timer"]:
            GLib.source_remove(anim["timer"])
        anim.update(iter=None, timer=0, **{"for": None})
        playing = state["playing"]
        state["playing"] = None
        if playing and playing in state["pictures"]:
            thumb = next((w for w in walls if w.path == playing), None)
            if thumb and thumb_path(thumb, tw, th).exists():
                state["pictures"][playing].set_filename(str(thumb_path(thumb, tw, th)))

    def play_preview(wall):
        stop_preview()
        if not wall.animated:
            return

        def made():
            out = make(preview_command(wall, preview_path(wall, tw, th), tw, th), preview_path(wall, tw, th))
            GLib.idle_add(start, out)

        def start(out):
            selected = state["shown"][state["index"]] if state["shown"] else None
            if not out or selected != wall:
                return False
            try:
                animation = GdkPixbuf.PixbufAnimation.new_from_file(str(out))
            except GLib.Error:
                return False
            state["playing"] = wall.path
            anim["iter"] = animation.get_iter(None)
            anim["for"] = wall.path
            frame()
            return False
        threading.Thread(target=made, daemon=True).start()

    def frame():
        it, picture = anim["iter"], state["pictures"].get(anim["for"])
        if it is None or picture is None:
            return False
        picture.set_paintable(Gdk.Texture.new_for_pixbuf(it.get_pixbuf()))
        delay = it.get_delay_time()
        it.advance(None)
        anim["timer"] = GLib.timeout_add(max(40, delay if delay > 0 else 83), frame)
        return False

    # ---- tiles ----
    def tile(wall):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["wall"], halign=Gtk.Align.CENTER)
        monitor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["monitor"], halign=Gtk.Align.CENTER)
        screen = Gtk.Overlay(css_classes=["screen"])
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, width_request=shown_w,
                              height_request=shown_h)
        if thumb_path(wall, tw, th).exists():
            picture.set_filename(str(thumb_path(wall, tw, th)))
        screen.set_child(picture)
        if wall.animated:
            screen.add_overlay(Gtk.Label(label=KINDS[wall.kind].upper(), css_classes=["badge"],
                                         halign=Gtk.Align.START, valign=Gtk.Align.START))
        if wall.path == now:
            screen.add_overlay(Gtk.Label(label="IN USE", css_classes=["badge", "using"],
                                         halign=Gtk.Align.END, valign=Gtk.Align.START))
        monitor.append(screen)
        chin = Gtk.Box(css_classes=["chin"], halign=Gtk.Align.CENTER)
        chin.append(Gtk.Box(css_classes=["led"]))
        monitor.append(chin)
        box.append(monitor)
        box.append(Gtk.Box(css_classes=["neck"], halign=Gtk.Align.CENTER))
        box.append(Gtk.Box(css_classes=["foot"], halign=Gtk.Align.CENTER))
        box.append(Gtk.Label(label=wall.name, css_classes=["name"], ellipsize=Pango.EllipsizeMode.END,
                             max_width_chars=22))
        state["pictures"][wall.path] = picture
        click = Gtk.GestureClick()
        click.connect("released", lambda _g, n, _x, _y, w=wall: choose(w) if wants_set(n, selected_is(w)) else pick(w))
        box.add_controller(click)
        return box

    def selected_is(wall):
        return bool(state["shown"]) and state["shown"][state["index"]] == wall

    def pick(wall):
        if wall in state["shown"]:
            select(state["shown"].index(wall))

    # ---- sidebar ----
    def draw_sidebar():
        child = sidebar.get_first_child()
        while child:
            sidebar.remove(child)
            child = sidebar.get_first_child()
        sidebar.append(Gtk.Label(label="WALLPAPERS", xalign=0, css_classes=["section"]))
        for name, glyph, _kinds in CATEGORIES:
            active = name == state["category"]
            button = Gtk.Button(css_classes=["flat", "cat"] + (["active"] if active else []), focusable=False)
            inner = Gtk.Box(spacing=10)
            inner.append(Gtk.Label(label=glyph, css_classes=["glyph"]))
            inner.append(Gtk.Label(label=name, xalign=0, hexpand=True))
            inner.append(Gtk.Label(label=str(len(in_category(walls, name))), css_classes=["count"]))
            button.set_child(inner)
            button.connect("clicked", lambda _b, n=name: pick_category(n))
            sidebar.append(button)
        sidebar.append(Gtk.Box(vexpand=True))
        for label, glyph, do in (("Surprise me", "\U000f049d", lambda _b: random_one()),
                                 ("Open the folder", "\U000f024b", lambda _b: open_folder())):
            button = Gtk.Button(css_classes=["flat", "cat"], focusable=False)
            inner = Gtk.Box(spacing=10)
            inner.append(Gtk.Label(label=glyph, css_classes=["glyph"]))
            inner.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            button.set_child(inner)
            button.connect("clicked", do)
            sidebar.append(button)

    def pick_category(name):
        state["category"] = name
        refresh()

    # ---- the list ----
    def refresh(keep=None):
        stop_preview()
        items = matching(in_category(walls, state["category"]), entry.get_text())
        state["shown"] = items
        state["pictures"] = {}
        child = view.get_first_child()
        while child:
            view.remove(child)
            child = view.get_first_child()
        state["widgets"] = []
        for wall in items:
            w = tile(wall)
            view.append(w)
            state["widgets"].append(w)
        empty.set_visible(not items)
        scroller.set_visible(bool(items))
        count.set_label(f"{len(items)} {'WALLPAPER' if len(items) == 1 else 'WALLPAPERS'}")
        draw_sidebar()
        want_thumbs(items)
        target = keep if keep in items else (now_wall() if now_wall() in items else None)
        state["index"] = 0
        if items:
            select(items.index(target) if target else 0)
        else:
            action.set_label("")

    def now_wall():
        return next((w for w in walls if w.path == now), None)

    def select(i, scroll=True):
        widgets = state["widgets"]
        if not widgets:
            return
        if state["index"] < len(widgets):
            widgets[state["index"]].remove_css_class("selected")
        state["index"] = i = max(0, min(i, len(widgets) - 1))
        widgets[i].add_css_class("selected")
        wall = state["shown"][i]
        action.set_label(f"Set {wall.name} as your wallpaper" + (f"  ·  {KINDS[wall.kind].lower()}" if wall.animated else ""))
        play_preview(wall)
        if scroll:
            GLib.idle_add(scroll_to, widgets[i])

    def scroll_to(widget):
        ok, rect = widget.compute_bounds(scroller.get_child())
        if not ok:
            return False
        adj = scroller.get_vadjustment()
        top = rect.origin.y + adj.get_value()
        if top < adj.get_value():
            adj.set_value(top - 8)
        elif top + rect.size.height > adj.get_value() + adj.get_page_size():
            adj.set_value(top + rect.size.height - adj.get_page_size() + 8)
        return False

    def columns():
        widgets = state["widgets"]
        if len(widgets) < 2:
            return 1
        ok, first = widgets[0].compute_bounds(view)
        return max(1, sum(1 for w in widgets if w.compute_bounds(view)[1].origin.y == first.origin.y))

    # ---- doing it ----
    def choose(wall):
        stop_preview()
        try:
            subprocess.Popen(apply_command(wall), start_new_session=True, stdin=subprocess.DEVNULL, env=clean_env(),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
        app.quit()

    def random_one():
        wall = surprise(walls, now)
        if wall:
            choose(wall)

    def open_folder():
        WALLS.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(launcher.own_scope(["xdg-open", str(WALLS)]), start_new_session=True, env=clean_env(),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        app.quit()

    arrows = {Gdk.KEY_Left: "left", Gdk.KEY_Right: "right", Gdk.KEY_Up: "up", Gdk.KEY_Down: "down"}

    def on_key(_ctl, keyval, _code, mods):
        if keyval == Gdk.KEY_Escape:
            if entry.get_text():
                entry.set_text("")
            else:
                app.quit()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if state["shown"]:
                choose(state["shown"][state["index"]])
            return True
        if mods & Gdk.ModifierType.CONTROL_MASK and keyval in (Gdk.KEY_r, Gdk.KEY_R):
            random_one()
            return True
        if keyval in arrows and not mods & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK):
            if arrows[keyval] in ("left", "right") and entry.get_text() and len(state["shown"]) < 2:
                return False
            import search
            select(search.step(state["index"], len(state["widgets"]), columns(), arrows[keyval]))
            return True
        if keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            names = [n for n, _g, _k in CATEGORIES]
            here = names.index(state["category"])
            back = keyval == Gdk.KEY_ISO_Left_Tab or mods & Gdk.ModifierType.SHIFT_MASK
            pick_category(names[(here + (-1 if back else 1)) % len(names)])
            return True
        return False
    keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    keys.connect("key-pressed", on_key)
    win.add_controller(keys)
    entry.connect("search-changed", lambda _e: refresh(keep=state["shown"][state["index"]] if state["shown"] else None))
    click = Gtk.GestureClick()  # a click outside the panel closes it
    click.connect("pressed", lambda _g, _n, x, y: backdrop.pick(x, y, Gtk.PickFlags.DEFAULT) is backdrop and app.quit())
    backdrop.add_controller(click)

    o = design.theme_options(Store())
    colours = design.resolved(o)
    provider = Gtk.CssProvider()
    provider.load_from_string(launcher.css("categories", opts) + css(colours, theme.mix))
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
    refresh()
    win.present()
    entry.grab_focus()
    return win


def main() -> int:
    if "--list" in sys.argv:  # what the picker would show, without a window
        for wall in scan():
            print(wall.kind, wall.path)
        return 0
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Gtk4LayerShell, Pango

    app = Gtk.Application(application_id="com.hyprdots.wallpicker")

    def activate(a):
        if a.get_windows():  # opened again while open: close
            a.quit()
            return
        build(a, Gtk, Gdk, GLib, GdkPixbuf, Pango, Gtk4LayerShell)
    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
