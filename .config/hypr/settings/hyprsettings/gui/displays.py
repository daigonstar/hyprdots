"""Displays page: a map of your screens and a card per screen. A change applies at once and then asks you to keep
it; with no answer within 10 seconds (or Esc) the previous layout comes back, so a bad mode undoes itself."""

from __future__ import annotations

import copy

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from .. import displays, theme  # noqa: E402
from ..schema import PAGE_INTRO  # noqa: E402
from . import ui  # noqa: E402

KEEP_SECONDS = 10


def build(win) -> Gtk.Widget:
    mons = displays.read()
    scroller, column = ui.page_box(PAGE_INTRO["Displays"])
    if not mons:
        column.append(Adw.StatusPage(title="No screens found", icon_name="video-display-symbolic",
                                     description="Hyprland has to be running to change screens here."))
        return scroller

    column.append(layout_map(mons))
    live = [m for m in mons if not m["disabled"]]
    for m in mons:
        column.append(screen_group(win, mons, m, can_turn_off=len(live) > 1 or m["disabled"]))
    return scroller


# ---- the map --------------------------------------------------------------------------------------------------
def layout_map(mons: list[dict]) -> Gtk.Widget:
    live = [m for m in mons if not m["disabled"]]
    c = theme.colors()
    accent, fg = theme.rgb(c["accent"]), theme.rgb(c["fg"])
    area = Gtk.DrawingArea(content_height=190, hexpand=True)

    def draw(_a, cr, width, height):
        if not live:
            return
        boxes = [(m, *logical(m)) for m in live]
        left = min(m["x"] for m, *_ in boxes)
        top = min(m["y"] for m, *_ in boxes)
        right = max(m["x"] + w for m, w, _h in boxes)
        bottom = max(m["y"] + h for m, _w, h in boxes)
        pad = 14
        k = min((width - 2 * pad) / max(1, right - left), (height - 2 * pad) / max(1, bottom - top))
        ox = (width - (right - left) * k) / 2
        oy = (height - (bottom - top) * k) / 2
        for m, w, h in boxes:
            x, y = ox + (m["x"] - left) * k + 3, oy + (m["y"] - top) * k + 3
            bw, bh = w * k - 6, h * k - 6
            rounded(cr, x, y, bw, bh, 10)
            cr.set_source_rgba(*accent, 0.16)
            cr.fill_preserve()
            cr.set_source_rgba(*accent, 0.9)
            cr.set_line_width(2)
            cr.stroke()
            layout = PangoCairo.create_layout(cr)
            layout.set_alignment(Pango.Alignment.CENTER)
            layout.set_font_description(Pango.FontDescription.from_string("Sans 10"))
            layout.set_markup(f"<b>{GLib.markup_escape_text(m['name'])}</b>\n<small>{m['width']}×{m['height']}"
                              f"{'  ·  ' + format(m['scale'], 'g') + '×' if m['scale'] != 1 else ''}</small>", -1)
            tw, th = layout.get_pixel_size()
            cr.set_source_rgba(*fg, 0.92)
            cr.move_to(x + (bw - tw) / 2, y + (bh - th) / 2)
            PangoCairo.show_layout(cr, layout)
    area.set_draw_func(draw)
    frame = Gtk.Frame(child=area, css_classes=["card"])
    return frame


def logical(m: dict) -> tuple[int, int]:
    return displays.logical_size(m)


def rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    for cx, cy, a in ((x + w - r, y + r, -1.5708), (x + w - r, y + h - r, 0), (x + r, y + h - r, 1.5708), (x + r, y + r, 3.1416)):
        cr.arc(cx, cy, r, a, a + 1.5708)
    cr.close_path()


# ---- one card per screen ----------------------------------------------------------------------------------------
def dropdown(labels: list[str], index: int) -> Gtk.DropDown:
    d = Gtk.DropDown(model=Gtk.StringList.new(labels), valign=Gtk.Align.CENTER)
    d.set_selected(max(0, index))
    return d


def choice_row(title: str, subtitle: str, labels: list[str], index: int, on_pick) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle, use_markup=False)
    d = dropdown(labels, index)

    def picked(w, _p):
        if w.get_selected() != index:
            on_pick(w.get_selected())
    d.connect("notify::selected", picked)
    row.add_suffix(d)
    return row


def screen_group(win, mons: list[dict], m: dict, can_turn_off: bool) -> Adw.PreferencesGroup:
    name = m["name"]
    group = Adw.PreferencesGroup(title=name + ("  (built-in)" if displays.is_internal(m) else ""), description=m["description"])
    on = Gtk.Switch(active=not m["disabled"], valign=Gtk.Align.CENTER, sensitive=can_turn_off,
                    tooltip_text="Turn this screen on or off" if can_turn_off else "The only screen that is on cannot be turned off")
    group.set_header_suffix(on)

    def switched(w, _p):
        if w.get_active() == (not m["disabled"]):
            return
        if not w.get_active():
            body = f"{name} goes dark and its windows move to another screen."
            if displays.is_internal(m):
                body += " This is the built-in screen, so it comes back on at your next login in case nothing else is plugged in."
            ui.confirm(win, "Turn off this screen?", body, "Turn off", lambda: change(win, mons, name, disabled=True),
                       destructive=True)
            w.set_active(True)
        else:
            change(win, mons, name, disabled=False)
    on.connect("notify::active", switched)
    if m["disabled"]:
        group.add(Adw.ActionRow(title="Turned off", subtitle="Switch it on above to use it again.", use_markup=False))
        return group

    # Resolution and refresh rate
    res = displays.resolutions(m["modes"]) or [(m["width"], m["height"])]
    current_res = (m["width"], m["height"])
    group.add(choice_row("Resolution", "Only modes this screen supports are listed.", [f"{w} × {h}" for w, h in res],
                         res.index(current_res) if current_res in res else 0,
                         lambda i: pick_resolution(win, mons, m, res[i])))
    rates = displays.refresh_rates(m["modes"], current_res) or [m["refresh"]]
    rate_index = min(range(len(rates)), key=lambda i: abs(rates[i] - m["refresh"]))
    group.add(choice_row("Refresh rate", "Higher is smoother.", [f"{r:.2f} Hz".replace(".00 Hz", " Hz") for r in rates], rate_index,
                         lambda i: change(win, mons, name, width=m["width"], height=m["height"], refresh=rates[i])))

    scales = list(displays.SCALES)
    if not any(abs(s - m["scale"]) < 0.01 for s in scales):
        scales.append(m["scale"])
        scales.sort()
    group.add(choice_row("Scale", "Size of text and windows. 1.5 or 2 suits a high-resolution screen.",
                         [f"{s:g}×" for s in scales], next(i for i, s in enumerate(scales) if abs(s - m["scale"]) < 0.01),
                         lambda i: change(win, mons, name, scale=scales[i])))
    group.add(choice_row("Rotation", "", [label for _v, label in displays.TRANSFORMS],
                         m["transform"] if m["transform"] < 4 else 0,
                         lambda i: change(win, mons, name, transform=displays.TRANSFORMS[i][0])))

    # Position: beside another screen, or exact numbers
    others = [x for x in mons if x["name"] != name and not x["disabled"]]
    spots = [(x, side) for x in others for side in ("right", "left", "above", "below")]
    labels = [f"{side.capitalize()} of {x['name']}" for x, side in spots]
    here = next((i for i, (x, side) in enumerate(spots) if displays.place_beside(m, x, side) == (m["x"], m["y"])), None)
    if here is None:
        labels.insert(0, f"At {m['x']}, {m['y']}")
        spots.insert(0, None)
        here = 0
    labels.append("Exact position…")

    def place(i):
        if i == len(spots):
            def got(text):
                try:
                    xs, ys = (int(p) for p in text.replace("x", ",").split(","))
                except ValueError:
                    raise ValueError("Enter two whole numbers like 2560,0") from None
                change(win, mons, name, x=xs, y=ys)
            ui.ask(win, "Position", got, [("x,y in pixels", f"{m['x']},{m['y']}")],
                   body="Top-left corner of this screen on the shared desktop. 0,0 is the top-left of the first screen.")
            win.refresh()
        elif spots[i] is not None:
            x, y = displays.place_beside(m, spots[i][0], spots[i][1])
            change(win, mons, name, x=x, y=y)
    if others:
        group.add(choice_row("Position", f"Now at {m['x']}, {m['y']} on the shared desktop.", labels, here, place))

    vrr = Adw.SwitchRow(title="Variable refresh rate", subtitle="FreeSync / G-Sync: smoother games on screens that support it.",
                        active=m["vrr"])
    vrr.connect("notify::active", lambda r, _p: r.get_active() != m["vrr"] and change(win, mons, name, vrr=r.get_active()))
    group.add(vrr)
    return group


def pick_resolution(win, mons, m, res):
    rates = displays.refresh_rates(m["modes"], res)
    change(win, mons, m["name"], width=res[0], height=res[1], refresh=rates[0] if rates else m["refresh"])


# ---- applying, with a way back -------------------------------------------------------------------------------------
def change(win, mons: list[dict], name: str, **edits) -> None:
    before = copy.deepcopy(mons)
    after, problem = displays.plan_change(before, name, **edits)
    if problem:
        ui.message(win, "Screens would overlap" if "overlap" in problem else "Not possible", problem)
        win.refresh()
        return
    ok, why = displays.apply(after)
    if not ok:
        displays.apply(before)
        ui.message(win, "Hyprland did not accept that", why)
        win.refresh()
        return
    ask_keep(win, before)


def ask_keep(win, before: list[dict]) -> None:
    left = {"n": KEEP_SECONDS, "timer": 0, "done": False}
    dialog = Adw.AlertDialog(heading="Keep these screen settings?")
    dialog.add_response("revert", "Put back")
    dialog.add_response("keep", "Keep")
    dialog.set_response_appearance("keep", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_close_response("revert")  # Esc, or closing the dialog, puts the old layout back

    def text():
        dialog.set_body(f"The previous settings come back in {left['n']} second{'s' if left['n'] != 1 else ''} "
                        "unless you choose Keep.")

    def answered(_d, response):
        if left["done"]:
            return
        left["done"] = True
        if left["timer"]:
            GLib.source_remove(left["timer"])
            left["timer"] = 0
        if response == "keep":
            fresh = displays.read()
            if not fresh:
                win.toast("Applied, but Hyprland did not report the screens, so monitors.lua was not changed.")
            else:
                try:
                    displays.write(win.store.dir / "monitors.lua", fresh)
                    win.toast("Screen settings applied and saved.")
                except OSError as e:
                    win.toast(f"Applied, but could not save monitors.lua: {e}")
        else:
            displays.apply(before)
            win.toast("Screen settings put back." if response == "revert" else "No answer, so the previous screen settings were restored.")
        win.refresh()

    def tick():
        left["n"] -= 1
        if left["n"] <= 0:
            left["timer"] = 0
            answered(dialog, "timeout")
            dialog.force_close()
            return False
        text()
        return True
    text()
    dialog.connect("response", answered)
    left["timer"] = GLib.timeout_add_seconds(1, tick)
    dialog.present(win)
