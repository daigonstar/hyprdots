#!/usr/bin/env python3
"""Hearthling, the PC assistant, as a GTK4 window (Super+C). Same agent as hypr_agent.py, which still runs in a terminal:
this file only replaces how it shows its work. Chat bubbles, live reasoning (dimmed, folds away when the answer
comes), Allow/Deny buttons for anything that changes the system, code blocks with Copy and Run in terminal, and a
terminal inside the window (needs vte4; without it the buttons open your own terminal).

Colours and font come from the settings Theme page. Keys: Enter sends, Shift+Enter starts a new line, Up recalls
the last question, Tab completes a /command, Ctrl+` shows the terminal, Esc stops the current answer.
Attach pictures and files with the paperclip, by pasting them (Ctrl+V) or by dropping them on the window: pictures are
read by the vision model, text files go into the question, anything else is passed by path for the agent to inspect.
Run with --check to test whether the window can start (assistant-toggle.sh falls back to the terminal if not)."""

from __future__ import annotations

import ctypes
import html
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "settings"))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk, Pango  # noqa: E402
import cairo  # noqa: E402

try:
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte  # noqa: E402
except (ValueError, ImportError):
    Vte = None

APP_ID = "com.hyprdots.assistant"  # also the window class the scratchpad rule in window.lua matches

if "--check" in sys.argv:
    import usersettings
    sys.exit(1 if usersettings._load_all().get("assistant", {}).get("interface") == "terminal" else 0)

import hypr_agent as agent  # noqa: E402
import agent_modes  # noqa: E402
import dnd_mode  # noqa: E402
import dnd_ui  # noqa: E402
from hyprsettings import livetheme  # noqa: E402
import dnd_library  # noqa: E402


# --- Colours: the Theme page roles, so the window matches the bar and launcher ---
FALLBACK = {"base": "#0b1218", "base_text": "#e4f5f6", "surface": "#1c2a33", "surface_alt": "#24343f",
            "text": "#e4f5f6", "accent": "#3fb8e0", "secondary": "#2f7fd0", "muted": "#6b7f8c",
            "icons": "#e4f5f6", "attention": "#e0a060"}


def theme():
    try:
        from hyprsettings import design
        from hyprsettings.store import Store
        o = design.theme_options(Store())
        colours = {**FALLBACK, **design.resolved(o)}
        return colours, design.font_list({**design.DEFAULTS, **o}), design.palette()
    except Exception:
        return dict(FALLBACK), '"CaskaydiaCove Nerd Font Propo", "CaskaydiaCove Nerd Font", sans-serif', {}


def rgb(hex_colour):
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgba(hex_colour, a):
    r, g, b = rgb(hex_colour)
    return f"rgba({round(r * 255)}, {round(g * 255)}, {round(b * 255)}, {a:g})"


def mix(a, b, t):
    ra, rb = rgb(a), rgb(b)
    return "#" + "".join(f"{round((x + (y - x) * t) * 255):02x}" for x, y in zip(ra, rb))


def luminance(hex_colour):
    r, g, b = rgb(hex_colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


C, FONT, PALETTE = theme()
DARK = luminance(C["base"]) < 0.5
# A bright wallpaper colour on a role meant for panels would wash the text out, so panels are tinted from the base
PANEL = mix(C["base"], C["surface"], 0.14 if DARK else 0.10)
PANEL_HI = mix(C["base"], C["surface"], 0.24 if DARK else 0.18)
ON_ACCENT = "#0b0f12" if luminance(C["accent"]) > 0.5 else "#ffffff"
GREEN, RED = "#5fd38d", "#ef6f6c"
# The tavern look of Dungeon Master mode, the one place that does not follow the Theme page
DM_LEATHER, DM_PANEL, DM_TEXT, DM_GOLD, DM_EMBER = "#17100a", "#241a11", "#f0e4cf", "#dcaa4a", "#e2622b"
DM_SERIF = '"Liberation Serif", "Noto Serif", Georgia, serif'
# ANSI colour of a /command -> the colour its chip gets here
ANSI = {"36": C["accent"], "35": "#c77dda", "33": C["attention"], "32": GREEN, "34": C["secondary"], "31": RED}


CSS = f"""
window.assistant, window.assistant.background {{ background: {rgba(C['base'], 0.94)}; color: {C['base_text']}; }}
window.assistant {{ font-family: {FONT}; }}
@define-color accent_bg_color {C['accent']};
@define-color accent_color {C['accent']};
@define-color accent_fg_color {ON_ACCENT};
@define-color window_bg_color {C['base']};
@define-color window_fg_color {C['base_text']};
@define-color view_bg_color {PANEL};
@define-color popover_bg_color {PANEL_HI};
@define-color card_bg_color {PANEL};
@define-color headerbar_bg_color transparent;

headerbar.assistant-header {{ background: transparent; box-shadow: none; border-bottom: 1px solid {rgba(C['accent'], 0.12)}; }}
.title-main {{ font-weight: 800; font-size: 15px; }}
.title-sub {{ font-size: 11px; color: {rgba(C['base_text'], 0.55)}; }}

/* Chat */
.chat {{ padding: 24px 20px 12px 20px; }}
.bottom {{ padding: 0 20px 14px 20px; }}
@keyframes bubble-in {{
    from {{ opacity: 0; transform: translateY(14px) scale(0.96); }}
    to {{ opacity: 1; transform: none; }}
}}
@keyframes fade-up {{
    from {{ opacity: 0; transform: translateY(6px); }}
    to {{ opacity: 1; transform: none; }}
}}
@keyframes pop {{
    0% {{ transform: scale(1); }}
    40% {{ transform: scale(1.18); }}
    100% {{ transform: scale(1); }}
}}
@keyframes breathe {{
    0% {{ box-shadow: 0 0 0 0 {rgba(C['attention'], 0.45)}; }}
    70% {{ box-shadow: 0 0 0 10px {rgba(C['attention'], 0)}; }}
    100% {{ box-shadow: 0 0 0 0 {rgba(C['attention'], 0)}; }}
}}
@keyframes dot {{
    0%, 80%, 100% {{ opacity: 0.25; transform: translateY(0); }}
    40% {{ opacity: 1; transform: translateY(-4px); }}
}}
.animate-in {{ animation: bubble-in 360ms cubic-bezier(0.2, 0.9, 0.3, 1.15); }}
.fade-up {{ animation: fade-up 260ms ease-out; }}

.bubble {{ border-radius: 20px; padding: 11px 15px; }}
.bubble.user {{
    background-image: linear-gradient(135deg, {C['accent']}, {mix(C['accent'], C['secondary'], 0.55)});
    color: {ON_ACCENT};
    border-bottom-right-radius: 6px;
    box-shadow: 0 6px 18px {rgba(C['accent'], 0.25)};
}}
.bubble.user label {{ color: {ON_ACCENT}; }}
.bubble.bot {{
    background: {PANEL};
    border: 1px solid {rgba(C['accent'], 0.14)};
    border-bottom-left-radius: 6px;
    box-shadow: 0 6px 22px rgba(0, 0, 0, 0.25);
}}
.bubble.bot.failed {{ border-color: {rgba(RED, 0.55)}; }}
.bubble.system {{ background: {rgba(PANEL_HI, 0.8)}; border-radius: 16px; }}
.chip {{ border-radius: 999px; padding: 2px 10px; font-weight: 700; font-size: 12px; }}
""" + "".join(f".tint-{code} {{ background: {rgba(colour, 0.2)}; color: {colour}; }}\n" for code, colour in ANSI.items()) + f"""

.answer label {{ color: {C['base_text']}; }}
.answer .heading {{ font-weight: 800; font-size: 15px; color: {C['accent']}; margin-top: 4px; }}
.answer .marker {{ color: {C['accent']}; font-weight: 800; }}
.answer link, .answer label link {{ color: {C['accent']}; }}

/* Reasoning: dimmer than the answer */
.reasoning {{ border-left: 2px solid {rgba(C['accent'], 0.35)}; padding-left: 10px; margin: 2px 0 6px 2px; }}
.reasoning-head {{ padding: 2px 6px; min-height: 0; border-radius: 8px; }}
.reasoning-head label {{ font-size: 12px; font-weight: 600; color: {rgba(C['base_text'], 0.6)}; }}
.reasoning-head:hover {{ background: {rgba(C['accent'], 0.08)}; }}
.reasoning-text {{ font-size: 12.5px; color: {rgba(C['base_text'], 0.45)}; font-style: italic; }}
.reasoning-text, .reasoning-text text {{ background: transparent; }}

/* Typing indicator */
.typing {{ padding: 4px 2px; }}
.typing .dot {{ min-width: 7px; min-height: 7px; border-radius: 99px; background: {C['accent']}; }}
.typing .dot.d1 {{ animation: dot 1.2s infinite ease-in-out; }}
.typing .dot.d2 {{ animation: dot 1.2s 0.15s infinite ease-in-out; }}
.typing .dot.d3 {{ animation: dot 1.2s 0.3s infinite ease-in-out; }}
.typing label {{ font-size: 12px; color: {rgba(C['base_text'], 0.55)}; }}

/* Tool activity */
.tool {{ border-radius: 10px; padding: 4px 10px; background: {rgba(C['accent'], 0.07)}; }}
.tool label {{ font-size: 12px; }}
.tool .name {{ font-weight: 700; color: {C['accent']}; }}
.tool .args {{ color: {rgba(C['base_text'], 0.55)}; font-family: monospace; }}
.tool.write .name {{ color: {C['attention']}; }}

/* Code blocks */
.code {{ border-radius: 12px; background: {rgba('#000000', 0.38 if DARK else 0.06)}; border: 1px solid {rgba(C['accent'], 0.18)}; }}
.code-head {{ padding: 3px 6px 3px 12px; border-bottom: 1px solid {rgba(C['accent'], 0.12)}; }}
.code-head .lang {{ font-size: 11px; font-weight: 700; letter-spacing: 1px; color: {rgba(C['base_text'], 0.5)}; }}
.code-body {{ padding: 10px 12px; font-family: "CaskaydiaCove Nerd Font Mono", monospace; font-size: 12.5px; }}
.code.command {{ border-color: {rgba(GREEN, 0.3)}; }}
.code.command .lang {{ color: {GREEN}; }}
button.mini {{ min-height: 24px; min-width: 24px; padding: 2px 8px; border-radius: 8px; font-size: 12px; transition: all 160ms ease; }}
button.mini:hover {{ background: {rgba(C['accent'], 0.18)}; }}
button.mini.done {{ animation: pop 300ms ease; color: {GREEN}; }}

/* Approval */
.approval {{ border-radius: 14px; padding: 10px 10px 10px 14px; background: {rgba(C['attention'], 0.10)};
             border: 1px solid {rgba(C['attention'], 0.45)}; animation: breathe 1.8s infinite; }}
.approval.sensitive {{ background: {rgba(RED, 0.10)}; border-color: {rgba(RED, 0.55)}; }}
.approval.answered {{ animation: none; background: transparent; border-color: {rgba(C['base_text'], 0.12)}; }}
.approval .question {{ font-weight: 600; }}
button.allow, button.deny {{ border-radius: 999px; padding: 6px 18px; font-weight: 800; transition: all 180ms cubic-bezier(0.2, 0.9, 0.3, 1.2); }}
button.allow {{ background: {GREEN}; color: #08140d; box-shadow: 0 4px 14px {rgba(GREEN, 0.35)}; }}
button.allow:hover {{ background: {mix(GREEN, '#ffffff', 0.15)}; transform: translateY(-1px) scale(1.04); box-shadow: 0 6px 18px {rgba(GREEN, 0.5)}; }}
button.deny {{ background: {rgba(RED, 0.15)}; color: {RED}; border: 1px solid {rgba(RED, 0.5)}; }}
button.deny:hover {{ background: {RED}; color: #1a0707; transform: translateY(-1px) scale(1.04); }}
button.allow:active, button.deny:active {{ transform: scale(0.95); }}
.verdict {{ font-weight: 800; animation: pop 320ms ease; }}
.verdict.yes {{ color: {GREEN}; }}
.verdict.no {{ color: {RED}; }}

.footer {{ font-size: 11px; color: {rgba(C['base_text'], 0.4)}; }}

/* Welcome */
.welcome {{ padding: 12px 0 28px 0; }}
.greeting {{ font-size: 28px; font-weight: 800; margin-top: 6px; }}
.tagline {{ font-size: 14px; color: {rgba(C['base_text'], 0.6)}; }}
.status-line {{ font-size: 12.5px; color: {rgba(C['base_text'], 0.7)}; }}
.status-line.warn {{ color: {C['attention']}; }}
.status-pill {{ border-radius: 999px; padding: 4px 12px; font-size: 12px; background: {rgba(C['base_text'], 0.05)};
                border: 1px solid {rgba(C['base_text'], 0.08)}; color: {rgba(C['base_text'], 0.75)}; }}
.status-pill.ok {{ color: {C['base_text']}; }}
.status-pill.warn {{ color: {C['attention']}; border-color: {rgba(C['attention'], 0.35)}; background: {rgba(C['attention'], 0.08)}; }}
button.status-pill {{ transition: all 160ms ease; }}
button.status-pill:hover {{ background: {rgba(C['attention'], 0.18)}; }}
.section-label {{ font-size: 11px; font-weight: 800; letter-spacing: 2px; color: {rgba(C['base_text'], 0.4)}; margin-top: 22px; }}
button.suggestion {{ border-radius: 14px; padding: 10px 16px; background: {rgba(C['accent'], 0.08)};
                     border: 1px solid {rgba(C['accent'], 0.25)}; transition: all 200ms ease; }}
button.suggestion:hover {{ background: {rgba(C['accent'], 0.2)}; border-color: {C['accent']}; transform: translateY(-2px); }}

/* Input */
.composer {{ margin: 6px 0 8px 0; padding: 6px; border-radius: 22px; background: {PANEL};
             border: 1px solid {rgba(C['accent'], 0.2)}; transition: all 200ms ease; }}
.composer:focus-within {{ border-color: {C['accent']}; box-shadow: 0 0 0 3px {rgba(C['accent'], 0.18)}; }}
.composer textview, .composer textview text {{ background: transparent; color: {C['base_text']}; font-size: 14px; }}
.placeholder {{ color: {rgba(C['base_text'], 0.4)}; font-size: 14px; }}
button.send {{ border-radius: 999px; min-width: 38px; min-height: 38px; padding: 0;
               background-image: linear-gradient(135deg, {C['accent']}, {C['secondary']}); color: {ON_ACCENT};
               transition: all 220ms cubic-bezier(0.2, 0.9, 0.3, 1.3); }}
button.send:hover {{ transform: scale(1.08) rotate(-8deg); box-shadow: 0 4px 16px {rgba(C['accent'], 0.45)}; }}
button.send:disabled {{ opacity: 0.4; }}
button.send.stop {{ background-image: none; background: {RED}; color: #1a0707; }}
.slash-menu {{ margin: 0; }}
button.slash {{ border-radius: 10px; padding: 3px 10px; font-size: 12px; transition: all 150ms ease; margin-bottom: 6px; }}
button.slash .name {{ font-weight: 800; }}
button.slash .desc {{ color: {rgba(C['base_text'], 0.6)}; }}
button.slash:hover {{ transform: translateY(-1px); }}
.statusbar {{ margin: 0 4px; }}
menubutton.pill > button, button.pill {{ border-radius: 999px; min-height: 22px; padding: 1px 10px; font-size: 11.5px; font-weight: 600;
               background: {rgba(C['base_text'], 0.06)}; transition: all 160ms ease; }}
menubutton.pill > button:hover, button.pill:hover {{ background: {rgba(C['accent'], 0.18)}; }}
button.pill.warn {{ color: {C['attention']}; }}
button.pill.good {{ color: {GREEN}; }}

/* Attachments */
@keyframes chip-in {{
    from {{ opacity: 0; transform: scale(0.6); }}
    to {{ opacity: 1; transform: none; }}
}}
.attach-tray {{ margin: 0; }}
.attachment {{ border-radius: 14px; background: {PANEL_HI}; border: 1px solid {rgba(C['accent'], 0.22)};
               animation: chip-in 260ms cubic-bezier(0.2, 0.9, 0.3, 1.3); margin: 6px 0; }}
.attachment.file {{ padding: 6px 4px 6px 10px; }}
.attachment .name {{ font-size: 12px; font-weight: 700; }}
.attachment .size {{ font-size: 11px; color: {rgba(C['base_text'], 0.5)}; }}
.thumb {{ border-radius: 14px; }}
button.remove {{ min-width: 20px; min-height: 20px; padding: 0; border-radius: 99px; background: {rgba('#000000', 0.6)};
                 color: #ffffff; margin: 4px; transition: all 150ms ease; }}
button.remove:hover {{ background: {RED}; transform: scale(1.12); }}
.attachment.file button.remove {{ background: transparent; color: {C['base_text']}; }}
.attachment.file button.remove:hover {{ background: {RED}; color: #1a0707; }}
button.attach {{ border-radius: 999px; min-width: 38px; min-height: 38px; padding: 0; transition: all 200ms ease; }}
button.attach:hover {{ background: {rgba(C['accent'], 0.18)}; transform: rotate(-12deg) scale(1.06); }}
button.sent-attachment {{ padding: 0; min-height: 0; min-width: 0; background: none; transition: transform 160ms ease; }}
button.sent-attachment:hover {{ transform: translateY(-2px); }}
.sent-file {{ border-radius: 12px; padding: 7px 12px; background: {PANEL_HI}; border: 1px solid {rgba(C['accent'], 0.22)}; }}
.sent-file label {{ font-size: 12px; font-weight: 700; }}
@keyframes drop-pulse {{
    0%, 100% {{ border-color: {rgba(C['accent'], 0.5)}; }}
    50% {{ border-color: {C['accent']}; }}
}}
.drop-zone {{ margin: 14px; border-radius: 24px; border: 3px dashed {C['accent']}; background: {rgba(C['base'], 0.82)};
              animation: drop-pulse 1.2s infinite ease-in-out; }}
.drop-zone .big {{ font-size: 22px; font-weight: 800; color: {C['accent']}; }}
.drop-zone .small {{ color: {rgba(C['base_text'], 0.65)}; }}

/* Terminal */
.terminal-pane {{ margin: 0 0 8px 0; border-radius: 14px; border: 1px solid {rgba(C['accent'], 0.25)};
                  background: {rgba('#000000', 0.45 if DARK else 0.85)}; }}
.terminal-head {{ padding: 4px 6px 4px 12px; }}
.terminal-head label {{ font-size: 12px; font-weight: 700; color: {rgba(C['base_text'], 0.7)}; }}
.user-run .why {{ color: {rgba(C['base_text'], 0.72)}; font-size: 13px; }}
.user-run .running {{ color: {rgba(C['base_text'], 0.8)}; font-weight: 600; }}
.user-run .code {{ margin: 0; }}
button.later {{ border-radius: 999px; padding: 6px 16px; font-weight: 700; background: {rgba(C['base_text'], 0.08)}; }}
.web-panel {{ background: {rgba(PANEL, 0.6)}; border-left: 1px solid {rgba(C['base_text'], 0.08)}; }}
.web-head {{ padding: 10px 8px 10px 16px; }}
.web-head .title {{ font-weight: 800; }}
@keyframes web-pulse {{ 50% {{ opacity: 0.35; }} }}
.web-live {{ color: {C['accent']}; font-size: 12px; font-weight: 800; animation: web-pulse 1.4s ease-in-out infinite; }}
.web-empty {{ color: {rgba(C['base_text'], 0.55)}; padding: 24px; }}
.web-list {{ padding: 0 10px 12px 10px; }}
.web-entry {{ border-radius: 12px; background: {rgba(C['base_text'], 0.04)}; border: 1px solid {rgba(C['base_text'], 0.07)}; }}
.web-entry.failed {{ border-color: {rgba(RED, 0.4)}; }}
.web-entry button.web-title {{ padding: 8px 10px; border-radius: 12px; }}
.web-entry .target {{ font-weight: 600; font-size: 13px; }}
.web-entry .kind {{ color: {rgba(C['base_text'], 0.6)}; font-size: 11px; font-weight: 700; }}
.web-entry .took {{ color: {rgba(C['base_text'], 0.55)}; font-size: 11px; }}
.web-entry .seen {{ padding: 2px 12px 12px 12px; font-size: 12px; color: {rgba(C['base_text'], 0.78)}; }}
.web-entry .seen-head {{ padding: 0 8px 2px 12px; }}
.web-entry .seen-head label {{ color: {rgba(C['base_text'], 0.55)}; font-size: 11px; font-weight: 700; }}
button.web-toggle.live {{ color: {C['accent']}; animation: web-pulse 1.4s ease-in-out infinite; }}

/* The table: Dungeon Master mode */
window.assistant.dnd, window.assistant.dnd.background {{ background: {DM_LEATHER}; color: {DM_TEXT}; }}
window.dnd .assistant-header {{ background: {DM_PANEL}; border-bottom: 1px solid {rgba(DM_GOLD, 0.25)}; }}
window.dnd .title-main {{ color: {DM_GOLD}; font-family: {DM_SERIF}; font-size: 17px; }}
window.dnd .bubble.user {{ background: linear-gradient(135deg, {DM_GOLD}, {DM_EMBER}); box-shadow: 0 4px 14px {rgba(DM_EMBER, 0.25)}; }}
window.dnd .bubble.user label {{ color: #1c1208; font-weight: 600; }}
window.dnd .bubble.bot {{ background: {DM_PANEL}; border: 1px solid {rgba(DM_GOLD, 0.18)}; }}
window.dnd .answer label {{ font-family: {DM_SERIF}; font-size: 16.5px; color: {DM_TEXT}; }}
window.dnd .answer .heading, window.dnd .answer .marker {{ color: {DM_GOLD}; }}
window.dnd .composer {{ background: {DM_PANEL}; border-color: {rgba(DM_GOLD, 0.3)}; }}
window.dnd .composer:focus-within {{ border-color: {DM_GOLD}; box-shadow: 0 0 0 3px {rgba(DM_GOLD, 0.18)}; }}
window.dnd .composer textview, window.dnd .composer textview text {{ color: {DM_TEXT}; font-size: 15px; }}
window.dnd .reasoning {{ border-left-color: {rgba(DM_GOLD, 0.3)}; }}
window.dnd button.send {{ background: {DM_GOLD}; color: #1c1208; }}
@keyframes dnd-land {{ 0% {{ transform: scale(1.5) rotate(-14deg); }} 60% {{ transform: scale(0.92) rotate(3deg); }} 100% {{ transform: none; }} }}
@keyframes dnd-hurt {{ 0%, 100% {{ transform: none; }} 20% {{ transform: translateX(-5px); background: {rgba(RED, 0.3)}; }} 60% {{ transform: translateX(4px); }} }}
@keyframes dnd-glint {{ 40% {{ transform: scale(1.14); color: #fff2c4; }} }}
.dnd-roll {{ border-radius: 14px; padding: 8px 14px 8px 8px; background: {rgba(DM_GOLD, 0.08)}; border: 1px solid {rgba(DM_GOLD, 0.3)}; }}
.dnd-roll.against {{ background: {rgba(RED, 0.07)}; border-color: {rgba(RED, 0.3)}; }}
.dnd-die {{ min-width: 46px; min-height: 46px; border-radius: 12px; background: {DM_LEATHER}; border: 2px solid {DM_GOLD}; color: {DM_GOLD}; font-size: 20px; font-weight: 800; }}
.dnd-die.landed {{ animation: dnd-land 300ms ease-out; }}
.dnd-die.crit {{ background: {DM_GOLD}; color: #1c1208; box-shadow: 0 0 18px {rgba(DM_GOLD, 0.7)}; }}
.dnd-die.fumble {{ border-color: {RED}; color: {RED}; }}
.dnd-roll .what {{ font-weight: 700; }}
.dnd-roll .sum {{ font-size: 12.5px; color: {rgba(DM_TEXT, 0.7)}; }}
.dnd-verdict {{ font-weight: 800; padding: 3px 12px; border-radius: 999px; animation: pop 320ms ease; }}
.dnd-verdict.good {{ background: {rgba(GREEN, 0.15)}; color: {GREEN}; }}
.dnd-verdict.bad {{ background: {rgba(RED, 0.15)}; color: {RED}; }}
.dnd-verdict.crit {{ background: {DM_GOLD}; color: #1c1208; }}
.dnd-note {{ color: {rgba(DM_GOLD, 0.8)}; font-size: 12px; font-style: italic; }}
.sheet {{ background: {DM_PANEL}; border-right: 1px solid {rgba(DM_GOLD, 0.22)}; color: {DM_TEXT}; }}
.sheet-page {{ padding: 12px 14px 20px 14px; }}
.sheet-crest {{ min-width: 54px; min-height: 54px; border-radius: 999px; background: linear-gradient(135deg, {DM_GOLD}, {DM_EMBER}); color: #1c1208; font-family: {DM_SERIF}; font-size: 28px; font-weight: 800; }}
.sheet-name {{ font-family: {DM_SERIF}; font-size: 22px; font-weight: 800; color: {DM_GOLD}; }}
.sheet-class {{ font-size: 12.5px; color: {rgba(DM_TEXT, 0.72)}; }}
.sheet-label {{ font-size: 11px; font-weight: 800; letter-spacing: 1px; color: {rgba(DM_GOLD, 0.75)}; }}
.sheet-section {{ margin-top: 14px; }}
.sheet-hp {{ border-radius: 12px; padding: 8px 10px; background: {rgba(DM_LEATHER, 0.7)}; }}
.sheet-hp.hurt {{ animation: dnd-hurt 420ms ease; }}
.sheet-hp .value {{ font-size: 20px; font-weight: 800; }}
progressbar.hp trough {{ min-height: 9px; border-radius: 6px; background: {rgba(DM_TEXT, 0.12)}; }}
progressbar.hp progress {{ min-height: 9px; border-radius: 6px; background: {GREEN}; }}
progressbar.hp.bloodied progress {{ background: {DM_GOLD}; }}
progressbar.hp.dying progress {{ background: {RED}; }}
progressbar.xp trough {{ min-height: 4px; border-radius: 3px; background: {rgba(DM_TEXT, 0.1)}; }}
progressbar.xp progress {{ min-height: 4px; border-radius: 3px; background: {DM_GOLD}; }}
.sheet-tile {{ border-radius: 10px; padding: 6px 4px; background: {rgba(DM_LEATHER, 0.7)}; }}
.sheet-tile .value {{ font-size: 18px; font-weight: 800; }}
.sheet-tile .name {{ font-size: 10px; font-weight: 700; color: {rgba(DM_TEXT, 0.6)}; }}
.sheet-tile.glint .value {{ animation: dnd-glint 600ms ease; }}
button.sheet-ability {{ border-radius: 10px; padding: 6px 2px; background: {rgba(DM_LEATHER, 0.7)}; color: {DM_TEXT}; transition: all 150ms ease; }}
button.sheet-ability:hover {{ background: {rgba(DM_GOLD, 0.2)}; }}
button.sheet-ability .value {{ font-size: 18px; font-weight: 800; color: {DM_GOLD}; }}
button.sheet-ability .name {{ font-size: 10px; font-weight: 800; }}
button.sheet-ability .score {{ font-size: 10px; color: {rgba(DM_TEXT, 0.55)}; }}
button.sheet-action {{ border-radius: 10px; padding: 6px 10px; background: {rgba(DM_EMBER, 0.14)}; color: {DM_TEXT}; font-weight: 700; transition: all 150ms ease; }}
button.sheet-action:hover {{ background: {rgba(DM_EMBER, 0.32)}; }}
button.sheet-action .detail {{ font-weight: 500; font-size: 12px; color: {rgba(DM_TEXT, 0.65)}; }}
button.sheet-ability-use {{ border-radius: 10px; padding: 6px 10px; background: {rgba(GREEN, 0.14)}; color: {DM_TEXT}; font-weight: 700; transition: all 150ms ease; }}
button.sheet-ability-use:hover {{ background: {rgba(GREEN, 0.3)}; }}
button.sheet-ability-use:disabled {{ opacity: 0.4; }}
button.sheet-ability-use .detail {{ font-weight: 500; font-size: 12px; color: {rgba(DM_TEXT, 0.65)}; }}
button.sheet-chip {{ border-radius: 999px; padding: 2px 10px; min-height: 0; font-size: 12px; background: {rgba(DM_TEXT, 0.08)}; color: {DM_TEXT}; }}
button.sheet-chip:hover {{ background: {rgba(DM_GOLD, 0.25)}; }}
.sheet-condition {{ border-radius: 999px; padding: 2px 10px; font-size: 12px; font-weight: 700; background: {rgba(RED, 0.18)}; color: {RED}; }}
.sheet-star {{ color: {DM_GOLD}; font-weight: 800; font-size: 12.5px; }}
.sheet-pip {{ min-width: 13px; min-height: 13px; border-radius: 999px; border: 2px solid {DM_GOLD}; background: {DM_GOLD}; }}
.sheet-pip.spent {{ background: transparent; opacity: 0.45; }}
.sheet-row {{ padding: 6px 2px; border-bottom: 1px solid {rgba(DM_TEXT, 0.07)}; }}
.sheet-row .equipped {{ color: {DM_GOLD}; }}
.sheet-row .note, .sheet-note {{ font-size: 12px; color: {rgba(DM_TEXT, 0.62)}; }}
.sheet-entry-name {{ font-weight: 700; color: {DM_GOLD}; }}
.sheet-combat {{ border-radius: 12px; padding: 8px 10px; background: {rgba(RED, 0.08)}; border: 1px solid {rgba(RED, 0.3)}; }}
.sheet-foe {{ padding: 3px 6px; border-radius: 8px; }}
.sheet-foe.now {{ background: {rgba(DM_GOLD, 0.22)}; font-weight: 800; }}
.sheet-foe.fallen {{ opacity: 0.4; }}
.sheet-eco {{ border-radius: 999px; padding: 2px 10px; font-size: 11px; font-weight: 700; background: {rgba(GREEN, 0.15)}; color: {GREEN}; }}
.sheet-eco.used {{ background: {rgba(DM_TEXT, 0.06)}; color: {rgba(DM_TEXT, 0.35)}; }}
.sheet-empty {{ font-family: {DM_SERIF}; font-size: 16px; color: {rgba(DM_TEXT, 0.65)}; padding: 40px 18px; }}
.dice-scrim {{ background: rgba(8, 5, 2, 0.72); }}
.dice-card {{ padding: 22px 30px; border-radius: 22px; background: {DM_PANEL}; border: 1px solid {rgba(DM_GOLD, 0.4)}; box-shadow: 0 18px 60px rgba(0, 0, 0, 0.6); min-width: 480px; animation: bubble-in 260ms cubic-bezier(0.2, 0.9, 0.3, 1.2); }}
.dice-title {{ font-family: {DM_SERIF}; font-size: 25px; font-weight: 800; color: {DM_GOLD}; }}
.dice-detail {{ font-size: 13px; color: {rgba(DM_TEXT, 0.68)}; }}
.dice-result {{ font-size: 24px; font-weight: 800; color: {DM_TEXT}; animation: pop 320ms ease; }}
.dice-result.crit {{ color: {DM_GOLD}; }}
.dice-result.fumble {{ color: {RED}; }}
button.dice-roll {{ border-radius: 999px; padding: 10px 44px; font-size: 18px; font-weight: 800; background: linear-gradient(135deg, {DM_GOLD}, {DM_EMBER}); color: #1c1208; transition: all 150ms ease; }}
button.dice-roll:hover {{ transform: translateY(-1px) scale(1.05); box-shadow: 0 6px 22px {rgba(DM_EMBER, 0.5)}; }}
.build {{ background: {DM_PANEL}; color: {DM_TEXT}; }}
.build-page {{ padding: 18px 26px 22px 26px; }}
.build-title {{ font-family: {DM_SERIF}; font-size: 26px; font-weight: 800; color: {DM_GOLD}; }}
.build-hero {{ font-family: {DM_SERIF}; font-size: 30px; font-weight: 800; }}
.build-note {{ color: {rgba(DM_TEXT, 0.72)}; font-size: 13.5px; }}
.build-over {{ color: {RED}; font-weight: 700; }}
.build-section {{ font-size: 12px; font-weight: 800; letter-spacing: 1px; color: {rgba(DM_GOLD, 0.85)}; margin-top: 6px; }}
.build-final {{ font-weight: 800; }}
.build-where {{ color: {rgba(DM_TEXT, 0.55)}; font-size: 12px; }}
.build-bar {{ padding: 10px 18px; border-top: 1px solid {rgba(DM_GOLD, 0.2)}; }}
.build-error {{ color: {RED}; padding: 6px 18px 0 18px; }}
button.build-card {{ border-radius: 12px; padding: 10px 12px; background: {rgba(DM_LEATHER, 0.75)}; color: {DM_TEXT}; border: 1px solid {rgba(DM_GOLD, 0.15)}; transition: all 150ms ease; }}
button.build-card:hover {{ border-color: {rgba(DM_GOLD, 0.55)}; }}
button.build-card:checked {{ background: {rgba(DM_GOLD, 0.2)}; border-color: {DM_GOLD}; }}
button.build-card .name {{ font-weight: 800; font-size: 15px; }}
button.build-card .detail {{ font-size: 12px; color: {rgba(DM_TEXT, 0.68)}; }}
button.build-pick {{ border-radius: 10px; padding: 6px 8px; background: {rgba(DM_LEATHER, 0.75)}; color: {DM_TEXT}; }}
button.build-pick:checked {{ background: {DM_GOLD}; color: #1c1208; font-weight: 800; }}
"""


def ui(fn, *args):
    """Runs fn on the GTK thread; the agent calls the hooks below from its worker thread."""
    GLib.idle_add(lambda: (fn(*args), False)[1])


def ease_out(p):
    return 1 - (1 - p) ** 3


# --- The logo: a hearth with a fire burning in it, drawn as vectors so it is sharp at any size ---
# The stonework takes the Theme page colours; the fire stays fire-coloured whatever the theme.
FIRE_OUTER, FIRE_MID, FIRE_CORE = (1.0, 0.36, 0.12), (1.0, 0.62, 0.16), (1.0, 0.9, 0.55)
EMBER = (1.0, 0.55, 0.15)
HEARTH_FLOOR = 0.86                           # where the logs sit, in logo units (y grows downwards)
OPENING_HALF, OPENING_SPRING = 0.56, 0.18     # half width of the fire opening, and where its arch starts


def _noise(t, seed):
    """Smooth, never-repeating wobble in [-1, 1], from a few sines at unrelated speeds."""
    return (math.sin(t * 1.7 + seed) * 0.5 + math.sin(t * 2.9 + seed * 2.3) * 0.3 + math.sin(t * 5.3 + seed * 4.1) * 0.2)


def _opening_path(cr, half=OPENING_HALF, floor=HEARTH_FLOOR + 0.12):
    cr.move_to(-half, floor)
    cr.line_to(-half, OPENING_SPRING)
    cr.arc(0, OPENING_SPRING, half, math.pi, 2 * math.pi)
    cr.line_to(half, floor)
    cr.close_path()


def _rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _flame_path(cr, cx, base, width, height, lean, t, seed):
    """One tongue of flame: a round bottom that narrows to a flickering tip."""
    tip_x = cx + lean * height + 0.10 * width * _noise(t * 2.2, seed)
    tip_y = base - height * (1 + 0.10 * _noise(t * 3.1, seed + 1))
    bulge_l = 1 + 0.12 * _noise(t * 2.6, seed + 2)
    bulge_r = 1 + 0.12 * _noise(t * 2.4, seed + 3)
    cr.move_to(cx, base + width * 0.55)
    cr.curve_to(cx - width * 1.15 * bulge_l, base + width * 0.5, cx - width * 1.05 * bulge_l, base - height * 0.4,
                tip_x, tip_y)
    cr.curve_to(cx + width * 1.05 * bulge_r, base - height * 0.4, cx + width * 1.15 * bulge_r, base + width * 0.5,
                cx, base + width * 0.55)
    cr.close_path()


class Logo(Gtk.DrawingArea):
    """A hearth whose fire lights up on start, flickers gently when idle, and roars, throwing embers, while the
    assistant works."""

    stone = None  # replaces the Theme page's stone colours (Dungeon Master mode)

    def __init__(self, size, intro=True, particles=True):
        super().__init__(content_width=size, content_height=round(size * 1.15))
        self.size = size
        self.particles = particles
        self.busy, self.busy_level = False, 0.0
        self.lit = 0.0 if intro else 1.0      # 0 = cold hearth, 1 = fire burning
        self.started = time.monotonic() if intro else None
        self.last = time.monotonic()
        self.clock = random.uniform(0, 100)   # so the avatars down the chat do not flicker in step
        self.embers = []
        self.set_draw_func(self._draw)
        self.tick = self.add_tick_callback(self._tick)

    def set_busy(self, busy):
        if busy and not self.tick:
            self.last = time.monotonic()
            self.tick = self.add_tick_callback(self._tick)
        self.busy = busy

    def stoke(self):
        """A poke at the fire: it flares up for a moment."""
        self.set_busy(True)
        GLib.timeout_add(700, lambda: (self.set_busy(False), False)[1])

    def freeze(self):
        """Stops animating (old answers keep a still logo); the fire dies down to a calm flame first."""
        self.set_busy(False)
        self._freeze = True

    def _tick(self, _widget, _clock):
        now = time.monotonic()
        dt, self.last = min(now - self.last, 0.1), now
        self.busy_level += ((1.0 if self.busy else 0.0) - self.busy_level) * min(1.0, dt * 3)
        self.clock += dt * (1 + 0.9 * self.busy_level)
        if self.started is not None:
            # Lighting the fire: a spark catches, flares past full, then settles
            p = min(1.0, (now - self.started) / 1.6)
            self.lit = ease_out(p) + 0.35 * math.sin(p * math.pi) * (1 - p)
            if p >= 1:
                self.started, self.lit = None, 1.0
        if self.particles:
            self._move_embers(dt)
        if getattr(self, "_freeze", False) and self.started is None and self.busy_level < 0.02 and not self.embers:
            self.busy_level = 0.0
            self.queue_draw()
            self.tick = None
            return GLib.SOURCE_REMOVE
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _move_embers(self, dt):
        rate = (0.8 + 9 * self.busy_level) * self.lit if not getattr(self, "_freeze", False) else 0
        if random.random() < rate * dt:
            self.embers.append([random.uniform(-0.18, 0.18), HEARTH_FLOOR - 0.25, random.uniform(-0.12, 0.12),
                                -random.uniform(0.45, 0.8) * (1 + 0.6 * self.busy_level), 0.0,
                                random.uniform(1.1, 2.0), random.uniform(0, 6)])
        for e in self.embers:
            e[0] += (e[2] + 0.18 * math.sin(e[4] * 4 + e[6])) * dt
            e[1] += e[3] * dt
            e[4] += dt
        self.embers = [e for e in self.embers if e[4] < e[5]]

    def _draw(self, _area, cr, w, h):
        s = min(w / 2.5, h / 2.6)
        cr.translate(w / 2, h / 2 - 0.12 * s)
        cr.scale(s, s)
        t, lit, busy = self.clock, self.lit, self.busy_level
        small = self.size < 60
        a1, a2 = Logo.stone or (rgb(C["accent"]), rgb(C["secondary"]))
        flicker = 0.85 + 0.15 * _noise(t * 2, 7)
        warmth = lit * (0.55 + 0.45 * busy) * flicker

        # Warm glow around the whole hearth, stronger while working
        g = cairo.RadialGradient(0, 0.55, 0.05, 0, 0.55, 1.3)
        g.add_color_stop_rgba(0, *FIRE_MID, 0.30 * warmth)
        g.add_color_stop_rgba(0.5, *FIRE_OUTER, 0.10 * warmth)
        g.add_color_stop_rgba(1, *FIRE_OUTER, 0)
        cr.set_source(g)
        cr.arc(0, 0.55, 1.3, 0, 2 * math.pi)
        cr.fill()

        # Stonework: the chimney breast with the opening cut out, then the mantel shelf on top
        cr.save()
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        _rounded_rect(cr, -0.95, -0.52, 1.9, 1.5, 0.08)
        _opening_path(cr)
        stone = cairo.LinearGradient(0, -0.52, 0, 0.98)
        stone.add_color_stop_rgb(0, *a1)
        stone.add_color_stop_rgb(1, *(c * 0.7 for c in a2))
        cr.set_source(stone)
        cr.fill_preserve()
        cr.clip()
        if not small:
            # Mortar lines between the stones, staggered like real brickwork
            cr.set_source_rgba(0, 0, 0, 0.22)
            cr.set_line_width(0.025)
            rows = [(-0.52 + i * 0.3) for i in range(6)]
            for i, y in enumerate(rows):
                cr.move_to(-1, y)
                cr.line_to(1, y)
                for x in [-0.95 + j * 0.42 + (0.21 if i % 2 else 0) for j in range(6)]:
                    cr.move_to(x, y)
                    cr.line_to(x, y + 0.3)
            cr.stroke()
        # Firelight on the stones around the opening
        light = cairo.RadialGradient(0, 0.7, 0.2, 0, 0.7, 1.1)
        light.add_color_stop_rgba(0, *FIRE_MID, 0.75 * warmth)
        light.add_color_stop_rgba(1, *FIRE_MID, 0)
        cr.set_source(light)
        cr.paint()
        cr.restore()

        # The hearthstone the fire sits on, and the mantel: a shelf a little wider than the chimney breast
        _rounded_rect(cr, -1.05, 0.94, 2.1, 0.14, 0.05)
        cr.set_source_rgb(*(c * 0.55 for c in a2))
        cr.fill()
        _rounded_rect(cr, -1.12, -0.7, 2.24, 0.2, 0.06)
        mantel = cairo.LinearGradient(0, -0.7, 0, -0.5)
        mantel.add_color_stop_rgb(0, *(min(1, c * 1.15 + 0.08) for c in a1))
        mantel.add_color_stop_rgb(1, *(c * 0.75 for c in a1))
        cr.set_source(mantel)
        cr.fill()

        # Inside the opening: dark soot, lit from below by the fire
        cr.save()
        _opening_path(cr)
        cr.clip()
        cr.set_source_rgb(0.05, 0.03, 0.03)
        cr.paint()
        inside = cairo.RadialGradient(0, HEARTH_FLOOR, 0.05, 0, HEARTH_FLOOR, 0.9)
        inside.add_color_stop_rgba(0, *FIRE_OUTER, 0.65 * warmth)
        inside.add_color_stop_rgba(1, *FIRE_OUTER, 0)
        cr.set_source(inside)
        cr.paint()

        # Two crossed logs, with glowing ends
        for angle, x in ((-0.2, -0.12), (0.2, 0.12)):
            cr.save()
            cr.translate(x, HEARTH_FLOOR - 0.02)
            cr.rotate(angle)
            _rounded_rect(cr, -0.4, -0.07, 0.8, 0.14, 0.07)
            cr.set_source_rgb(0.36, 0.2, 0.11)
            cr.fill()
            cr.set_source_rgba(*EMBER, 0.5 + 0.4 * lit * flicker)
            cr.arc(0.33 if angle > 0 else -0.33, 0, 0.045, 0, 2 * math.pi)
            cr.fill()
            cr.restore()

        # The fire: three tongues, each drawn in three layers from the deep red edge to the bright core
        if lit > 0.01:
            roar = lit * (1 + 0.3 * busy)
            base = HEARTH_FLOOR - 0.12
            tongues = ((0.0, 0.2, 0.62, 0.0, 0), (-0.2, 0.13, 0.4, -0.25, 10), (0.2, 0.13, 0.42, 0.25, 20))
            for colour, scale, alpha in ((FIRE_OUTER, 1.0, 0.95), (FIRE_MID, 0.72, 0.95), (FIRE_CORE, 0.42, 1.0)):
                for cx, width, height, lean, seed in tongues:
                    h_now = height * roar * scale * (0.92 + 0.08 * _noise(t * 4, seed + 5))
                    _flame_path(cr, cx, base, width * scale * min(1, 0.4 + lit), h_now, lean * 0.4, t, seed)
                fire = cairo.LinearGradient(0, base + 0.1, 0, base - 0.8)
                fire.add_color_stop_rgba(0, *colour, alpha)
                fire.add_color_stop_rgba(1, *colour, alpha * 0.75)
                cr.set_source(fire)
                cr.fill()
        cr.restore()

        # Embers drifting up out of the fire
        for x, y, _vx, _vy, age, life, _phase in self.embers:
            fade = (1 - age / life) * min(1, age * 4)
            r = 0.022 + 0.018 * (1 - age / life)
            halo = cairo.RadialGradient(x, y, 0, x, y, r * 3)
            halo.add_color_stop_rgba(0, *FIRE_MID, 0.5 * fade)
            halo.add_color_stop_rgba(1, *FIRE_MID, 0)
            cr.set_source(halo)
            cr.arc(x, y, r * 3, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(*FIRE_CORE, fade)
            cr.arc(x, y, r, 0, 2 * math.pi)
            cr.fill()


# --- Light markdown to widgets ---
FENCE_RE = re.compile(r"^\s*```\s*([\w+#.-]*)\s*$")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
BOLD_LINE_RE = re.compile(r"^\*\*([^*]+)\*\*:?$")
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
URL_RE = re.compile(r"(?<![\"'=>])\bhttps?://[^\s<>()]+[^\s<>().,;:!?'\"]")
SHELL_LANGS = {"", "bash", "sh", "zsh", "shell", "console", "fish", "terminal"}


def inline_markup(text):
    """**bold**, `code`, [links](url) and bare URLs as Pango markup; everything else escaped."""
    out = []
    for part in re.split(r"(`[^`]+`)", text):
        if len(part) > 2 and part.startswith("`") and part.endswith("`"):
            out.append(f'<span font_family="monospace" background="{C["accent"]}" bgalpha="16%" '
                       f'foreground="{mix(C["accent"], C["base_text"], 0.35)}"> {html.escape(part[1:-1], quote=False)} </span>')
            continue
        links = []

        def keep(label, url):
            links.append(f'<a href="{html.escape(url)}">{html.escape(label, quote=False)}</a>')
            return f"\x00{len(links) - 1}\x00"
        part = LINK_RE.sub(lambda m: keep(m.group(1), m.group(2)), part)
        part = URL_RE.sub(lambda m: keep(m.group(0), m.group(0)), part)
        part = html.escape(part, quote=False)
        part = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", part)
        part = re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], part)
        out.append(part)
    return "".join(out)


def parse_blocks(text):
    """Splits an answer into ("text", lines) and ("code", lang, body) blocks. Runs of "$ command" lines outside a
    fence become a bash block too, so a suggested command is always copyable."""
    text = agent._prepare_markdown(text)
    blocks, lines, code, lang = [], [], None, ""
    for raw in text.splitlines():
        fence = FENCE_RE.match(raw)
        if code is not None:
            if fence and not fence.group(1):
                blocks.append(("code", lang, "\n".join(code)))
                code = None
            else:
                code.append(raw)
            continue
        if fence:
            if lines:
                blocks.append(("text", lines))
                lines = []
            code, lang = [], fence.group(1).lower()
            continue
        if raw.startswith("$ ") and raw[2:].strip():
            if blocks and blocks[-1][0] == "code" and blocks[-1][1] == "bash" and not lines:
                blocks[-1] = ("code", "bash", blocks[-1][2] + "\n" + raw[2:])
            else:
                if lines:
                    blocks.append(("text", lines))
                    lines = []
                blocks.append(("code", "bash", raw[2:]))
            continue
        lines.append(raw)
    if code is not None:
        blocks.append(("code", lang, "\n".join(code)))
    if lines:
        blocks.append(("text", lines))
    return [b for b in blocks if b[0] == "code" or any(l.strip() for l in b[1])]


HL_STRING = re.compile(r"(\"(?:[^\"\\]|\\.)*\"|'[^']*')")


def highlight(code, lang):
    """A light touch of colour: comments dim, strings tinted, the command word of each shell line in the accent."""
    comment = "--" if lang == "lua" else ("//" if lang in ("js", "c", "cpp", "rust", "go", "css", "json") else "#")
    out = []
    for line in code.split("\n"):
        idx = -1
        for m in re.finditer(re.escape(comment), line):
            if m.start() == 0 or line[m.start() - 1].isspace():
                if not (lang in SHELL_LANGS and line[:m.start()].count('"') % 2):
                    idx = m.start()
                    break
        body, note = (line, "") if idx < 0 else (line[:idx], line[idx:])
        pieces = []
        for i, part in enumerate(HL_STRING.split(body)):
            esc = html.escape(part, quote=False)
            if i % 2:
                pieces.append(f'<span foreground="{C["attention"]}">{esc}</span>')
            elif i == 0 and lang in SHELL_LANGS:
                m = re.match(r"^(\s*)(sudo\s+)?([\w./+-]+)", part)
                if m:
                    lead = html.escape(m.group(1) + (m.group(2) or ""), quote=False)
                    rest = html.escape(part[m.end():], quote=False)
                    pieces.append(f'{lead}<span foreground="{C["accent"]}" weight="bold">{html.escape(m.group(3))}</span>{rest}')
                else:
                    pieces.append(esc)
            else:
                pieces.append(esc)
        if note:
            pieces.append(f'<span foreground="{C["base_text"]}" fgalpha="45%" style="italic">{html.escape(note, quote=False)}</span>')
        out.append("".join(pieces))
    return "\n".join(out)


def text_label(markup, css=None):
    label = Gtk.Label(use_markup=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, xalign=0, selectable=True,
                      hexpand=True, css_classes=css or [])
    label.set_markup(markup)
    return label


def mini_button(icon, tooltip, on_click, text=None):
    button = Gtk.Button(css_classes=["flat", "mini"], tooltip_text=tooltip)
    box = Gtk.Box(spacing=5)
    box.append(Gtk.Image(icon_name=icon))
    if text:
        box.append(Gtk.Label(label=text))
    button.set_child(box)
    if on_click:
        button.connect("clicked", on_click)
    return button


def flash_done(button, icon="object-select-symbolic"):
    box = button.get_child()
    image = box.get_first_child()
    old = image.get_icon_name()
    image.set_from_icon_name(icon)
    button.add_css_class("done")

    def back():
        image.set_from_icon_name(old)
        button.remove_css_class("done")
    GLib.timeout_add(1400, lambda: (back(), False)[1])


class CodeBlock(Gtk.Box):
    def __init__(self, app, lang, code, command=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["code"] + (["command"] if command else []))
        self.code = code.rstrip("\n")
        head = Gtk.Box(spacing=4, css_classes=["code-head"])
        head.append(Gtk.Label(label=("$ command" if command else (lang or "code")).upper(), css_classes=["lang"],
                              hexpand=True, xalign=0))
        copy = mini_button("edit-copy-symbolic", "Copy", None, "Copy")
        copy.connect("clicked", lambda b: (app.copy(self.code), flash_done(b)))
        head.append(copy)
        if lang in SHELL_LANGS and not command:
            paste = mini_button("edit-paste-symbolic", "Put it in the terminal without running it", None, "Paste")
            paste.connect("clicked", lambda b: (app.paste_in_terminal(self.code), flash_done(b)))
            head.append(paste)
            run = mini_button("utilities-terminal-symbolic", "Run it now in the terminal", None, "Run")
            run.connect("clicked", lambda b: (app.run_in_terminal(self.code), flash_done(b)))
            head.append(run)
        self.head = head
        self.append(head)
        body = Gtk.Label(use_markup=True, xalign=0, selectable=True, css_classes=["code-body"])
        body.set_markup(highlight(self.code, lang))
        scroller = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                      hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(body)
        self.append(scroller)


class Answer(Gtk.Box):
    """The rendered reply. Blocks slide in one after another and text is revealed word by word."""

    def __init__(self, app, text, animate=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["answer"])
        self.app = app
        self.queue = []
        for block in parse_blocks(text):
            if block[0] == "code":
                self.queue.append(CodeBlock(app, block[1], block[2]))
            else:
                self.queue.extend(self._text_widgets(block[1]))
        if not animate:
            for widget in self.queue:
                self.append(widget)
            return
        for widget in self.queue:
            widget.set_visible(False)
            self.append(widget)
        total = sum(len(w.typed.words) for w in self.queue if hasattr(w, "typed"))
        self.per_tick = max(2, math.ceil(total / 45))  # the whole answer appears in about 0.75 s
        self.index = 0
        GLib.timeout_add(16, self._reveal)

    def _text_widgets(self, lines):
        out, para = [], []

        def flush():
            if para:
                out.append(self._typed(" ".join(l.strip() for l in para)))
                para.clear()
        for line in lines:
            if not line.strip():
                flush()
                continue
            heading = HEADING_RE.match(line) or BOLD_LINE_RE.match(line.strip())
            item = agent._LIST_RE.match(line)
            if heading:
                flush()
                out.append(self._typed(heading.group(1).strip().rstrip(":"), ["heading"]))
            elif item:
                flush()
                indent = len(item.group(1).expandtabs(4))
                marker = "•" if item.group(2) in ("-", "*", "•") else item.group(2)
                row = Gtk.Box(spacing=8, margin_start=4 + min(indent, 8) * 6)
                row.append(Gtk.Label(label=marker, css_classes=["marker"], valign=Gtk.Align.START, yalign=0))
                label = self._typed(item.group(3))
                row.append(label)
                row.typed = label
                out.append(row)
            else:
                para.append(line)
        flush()
        return out

    def _typed(self, text, css=None):
        label = text_label(inline_markup(text), css)
        label.typed, label.words, label.full, label.shown = label, text.split(" "), text, 0
        return label

    def _reveal(self):
        budget = self.per_tick
        while self.index < len(self.queue) and budget > 0:
            widget = self.queue[self.index]
            if not widget.get_visible():
                widget.set_visible(True)
                widget.add_css_class("fade-up")
            label = getattr(widget, "typed", None)
            if label is None:  # a code block appears whole and holds the next text back a moment
                self.index += 1
                budget -= 6
                continue
            take = min(budget, len(label.words) - label.shown)
            label.shown += take
            budget -= take
            done = label.shown >= len(label.words)
            label.set_markup(inline_markup(label.full if done else " ".join(label.words[:label.shown])))
            if done:
                self.index += 1
        return self.index < len(self.queue)


class Draft(Gtk.Box):
    """The answer while it is still being written. Finished paragraphs are rendered once, like the final answer, and
    only the paragraph being written is rebuilt, so each update costs the same however long the answer gets.
    Text that looks like a tool call written out as text is never shown."""

    DECIDE_AT = 40  # characters: enough to tell prose from a tool call written as text
    TOOL_CALL_START = re.compile(r"\s*(?:`{3}\s*json\s*)?[{\[]|\s*`*\s*TOOL_USE")

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["answer"], visible=False)
        self.app, self.text, self.done, self.decided = app, "", 0, False
        self.tail = None

    def add(self, piece):
        self.text += piece
        if not self.decided:
            head = self.text.strip()
            if len(head) < self.DECIDE_AT and "\n" not in head:
                return
            self.decided = True
            if self.TOOL_CALL_START.match(self.text) or agent.parse_text_tool_call(head):
                self.text = ""
                return
            self.set_visible(True)
        elif not self.get_visible():
            return
        cut = self.text.rfind("\n\n", self.done)
        while cut > self.done:  # the last empty line outside a code block
            segment = self.text[self.done:cut]
            if sum(1 for line in segment.splitlines() if FENCE_RE.match(line)) % 2 == 0:
                if segment.strip():
                    finished = Answer(self.app, segment, animate=False)
                    self.insert_child_after(finished, self.tail.get_prev_sibling() if self.tail else self.get_last_child())
                self.done = cut + 2
                break
            cut = self.text.rfind("\n\n", self.done, cut)
        tail = Answer(self.app, self.text[self.done:], animate=False)
        if self.tail:
            self.remove(self.tail)
        self.append(tail)
        self.tail = tail


# --- Attachments ---
UPLOAD_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir(), f"hypr_agent_uploads_{os.getpid()}")
IMAGE_MAX_SIDE = 1600        # bigger pictures are scaled down: the vision model gains little and gets much slower
IMAGE_MAX_BYTES = 60_000_000
TEXT_READ_BYTES = 200_000    # a text file is read up to this size...
TEXT_CHARS = 12_000          # ...and this much of all attached text goes into the question
FILE_ICON = "text-x-generic-symbolic"


class Attachment:
    """A picture (kind "image", path is a PNG copy in UPLOAD_DIR) or any other file (kind "file", its own path)."""

    def __init__(self, kind, path, name, original=None):
        self.kind, self.path, self.name = kind, path, name
        self.original = original or path
        try:
            self.size = os.path.getsize(self.original)
        except OSError:
            self.size = 0


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def mime_of(path):
    if os.path.isdir(path):
        return "inode/directory"
    guess, _uncertain = Gio.content_type_guess(path, None)
    return Gio.content_type_get_mime_type(guess) or "application/octet-stream"


def upload_path(stem):
    os.makedirs(UPLOAD_DIR, mode=0o700, exist_ok=True)
    stem = re.sub(r"[^\w.-]+", "_", stem)[:40] or "image"
    fd, path = tempfile.mkstemp(prefix=stem + "-", suffix=".png", dir=UPLOAD_DIR)
    os.close(fd)
    return path


def save_image(src, stem):
    """Copies a picture as a PNG the vision model can read: any format GdkPixbuf knows, turned upright, at most
    IMAGE_MAX_SIDE pixels across. Returns the new path; raises GLib.Error for something that is not a picture."""
    _fmt, width, height = GdkPixbuf.Pixbuf.get_file_info(src)
    if not width:
        raise GLib.Error(f"{os.path.basename(src)} is not a picture")
    if max(width, height) > IMAGE_MAX_SIDE:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(src, IMAGE_MAX_SIDE, IMAGE_MAX_SIDE, True)
    else:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(src)
    pixbuf = pixbuf.apply_embedded_orientation() or pixbuf
    dst = upload_path(stem)
    pixbuf.savev(dst, "png", [], [])
    return dst


def read_text(path):
    """The file's text, or None if it is binary, not UTF-8 or unreadable."""
    try:
        with open(path, "rb") as f:
            data = f.read(TEXT_READ_BYTES + 1)
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    try:
        text = data[:TEXT_READ_BYTES].decode("utf-8")
    except UnicodeDecodeError:
        try:  # cut in the middle of a character at the size limit
            text = data[:TEXT_READ_BYTES].decode("utf-8", errors="strict" if len(data) <= TEXT_READ_BYTES else "ignore")
        except UnicodeDecodeError:
            return None
    return text + ("\n...[file is longer; read the rest with your tools]" if len(data) > TEXT_READ_BYTES else "")


def attachment_prompt(text, attachments, vision):
    """The question as the agent sees it: the user's words, then a note per attachment. vision maps an image
    attachment to the vision model's answer (or why it could not be read)."""
    notes, budget = [], TEXT_CHARS
    inline_images = not agent_modes.uses_pc_state()  # this mode does not list IMAGES SHARED THIS SESSION
    for a in attachments:
        where = a.original.replace(os.path.expanduser("~"), "~", 1)
        if a.kind == "image":
            seen = vision.get(a, "")
            if seen.startswith("Vision Analysis: "):
                body = seen[len("Vision Analysis: "):].strip()
                note = (f"[Attached image: {where}. The vision model's description is under IMAGES SHARED THIS SESSION; "
                        f"call ask_about_image for details it does not cover.]")
                if inline_images:
                    note = f"[Attached image: {where}. What the vision model saw:]\n{body}"
            else:
                note = f"[Attached image: {where}. It could not be read: {seen or 'no vision model is set up'}]"
            notes.append(note)
            continue
        mime = mime_of(a.original)
        if mime == "inode/directory":
            notes.append(f"[Attached folder: {where}. Look inside it with your tools if needed.]")
            continue
        if agent._touches_blocked_path(["cat", a.original]):
            notes.append(f"[Attached file: {where} ({mime}). It is in a protected location (keys or credentials), "
                         "so its contents were not included.]")
            continue
        content = read_text(a.original)
        if content is not None and budget > 0:
            shown = content if len(content) <= budget else content[:budget] + "\n...[cut here; read the rest with your tools]"
            budget -= len(shown)
            lang = os.path.splitext(a.name)[1].lstrip(".").lower()
            notes.append(f"[Attached file: {where} ({human_size(a.size)})]\n```{lang}\n{shown}\n```")
        else:
            why = "not shown here" if content is None else "not shown, the attached text limit was reached"
            notes.append(f"[Attached file: {where} ({mime}, {human_size(a.size)}); {why}. Inspect it with your tools if needed.]")
    request = text.strip() or ("Describe the attached image." if all(a.kind == "image" for a in attachments)
                               else "Look at the attached file and tell me what it is and anything notable about it.")
    return request + "\n\n" + "\n\n".join(notes)


def thumbnail(path, size):
    """A square picture of size px, cropped to fill like a phone gallery; drawn from 2x pixels so it stays sharp."""
    image = Gtk.Image(pixel_size=size, css_classes=["thumb"], overflow=Gtk.Overflow.HIDDEN)
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        w, h, side = pixbuf.get_width(), pixbuf.get_height(), size * 2
        scale = side / min(w, h)
        pixbuf = pixbuf.scale_simple(max(side, round(w * scale)), max(side, round(h * scale)), GdkPixbuf.InterpType.BILINEAR)
        pixbuf = pixbuf.new_subpixbuf((pixbuf.get_width() - side) // 2, (pixbuf.get_height() - side) // 2, side, side)
        png = pixbuf.save_to_bufferv("png", [], [])[1]
        image.set_from_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(png)))
    except GLib.Error:
        image.set_from_icon_name("image-missing-symbolic")
    return image


def file_icon(path):
    if os.path.isdir(path):
        return Gtk.Image(icon_name="folder-symbolic")
    content_type = Gio.content_type_from_mime_type(mime_of(path))
    return Gtk.Image(gicon=Gio.content_type_get_symbolic_icon(content_type)) if content_type else Gtk.Image(icon_name=FILE_ICON)


def open_with_default(path):
    try:
        subprocess.Popen(["xdg-open", path], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


# --- One question and its answer ---
class Typing(Gtk.Box):
    def __init__(self):
        super().__init__(spacing=5, css_classes=["typing"])
        for i in (1, 2, 3):
            self.append(Gtk.Box(css_classes=["dot", f"d{i}"], valign=Gtk.Align.CENTER))
        self.label = Gtk.Label(margin_start=6)
        self.append(self.label)
        self.started = time.monotonic()
        self.text = "Thinking"
        self.alive = True
        GLib.timeout_add(500, self._timer)

    def set_text(self, text):
        self.text = text.rstrip(".")
        self.started = time.monotonic()
        self._timer()

    def _timer(self):
        elapsed = int(time.monotonic() - self.started)
        self.label.set_label(f"{self.text}…" + (f"  {elapsed}s" if elapsed >= 2 else ""))
        return self.alive


class Reasoning(Gtk.Box):
    """The model's thinking: streamed in dim italics, folded away with a summary once it moves on.
    The text goes into an append-only TextView: a Label would lay out all of it again on every frame, so a long
    stretch of reasoning made each frame slower and the window fell further and further behind the stream."""

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["reasoning", "fade-up"])
        self.app = app
        self.started, self.parts = time.monotonic(), []
        self.space = ""  # whitespace held back until more text follows it
        self.head = Gtk.Button(css_classes=["flat", "reasoning-head"], halign=Gtk.Align.START)
        self.head_label = Gtk.Label(label="◔  Reasoning…")
        self.head.set_child(self.head_label)
        self.head.connect("clicked", lambda *_: self.revealer.set_reveal_child(not self.revealer.get_reveal_child()))
        self.append(self.head)
        self.body = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                 css_classes=["reasoning-text"])
        self.buffer = self.body.get_buffer()
        self.end = self.buffer.create_mark(None, self.buffer.get_end_iter(), False)
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                           max_content_height=200)
        self.scroller.set_child(self.body)
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=320,
                                     reveal_child=True)
        self.revealer.set_child(self.scroller)
        self.append(self.revealer)

    @property
    def text(self):
        return "".join(self.parts)

    def add(self, text):
        self.parts.append(text)
        self.buffer.insert(self.buffer.get_end_iter(), self._tidy(text))
        self.body.scroll_to_mark(self.end, 0, False, 0, 1)

    def _tidy(self, text):
        """The new piece as it should be shown: no blank space at either end and never more than one empty line in a
        row. Whitespace is held back until text follows it, so each update costs the same however long the text is."""
        out = []
        for part in re.split(r"(\s+)", text):
            if part.isspace():
                self.space += part
            elif part:
                if self.buffer.get_char_count() or out:
                    out.append(re.sub(r"\n{3,}", "\n\n", self.space))
                self.space = ""
                out.append(part)
        return "".join(out)

    def finish(self):
        took = time.monotonic() - self.started
        words = len(self.text.split())
        self.head_label.set_label(f"✓  Reasoned for {took:.1f}s · {words} words  ›")
        self.revealer.set_reveal_child(False)


class Turn(Gtk.Box):
    """A question (right) and the assistant's work and answer (left)."""

    def __init__(self, app, question=None, slash=None, attachments=()):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app
        if question is not None:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.END, margin_start=80,
                          css_classes=["animate-in"])
            if attachments:
                row.append(self._sent_attachments(attachments))
            if question:
                bubble = Gtk.Box(css_classes=["bubble", "user"], halign=Gtk.Align.END)
                bubble.append(text_label(html.escape(question, quote=False)))
                row.append(bubble)
            self.append(row)
        self.bot_row = Gtk.Box(spacing=12, halign=Gtk.Align.FILL, css_classes=["animate-in"])
        self.avatar = Logo(30, intro=False, particles=False)
        self.avatar.set_valign(Gtk.Align.START)
        self.bot_row.append(self.avatar)
        self.bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True,
                              css_classes=["bubble", "bot"])
        self.bot_row.append(self.bubble)
        if slash:
            name, colour = slash
            chip = Gtk.Label(label=f"/{name}", halign=Gtk.Align.START, css_classes=["chip"])
            app.tint(chip, colour)
            self.bubble.append(chip)
        self.typing = Typing()
        self.bubble.append(self.typing)
        self.append(self.bot_row)
        self.reasoning = self.draft = None
        self.last_command = None
        self.avatar.set_busy(True)

    @staticmethod
    def _sent_attachments(attachments):
        """Pictures as thumbnails and files as chips above the question; clicking one opens it."""
        flow = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        for a in attachments:
            button = Gtk.Button(css_classes=["flat", "sent-attachment"], tooltip_text=f"Open {a.name}", valign=Gtk.Align.END)
            if a.kind == "image":
                button.set_child(thumbnail(a.path, 120))
            else:
                chip = Gtk.Box(spacing=6, css_classes=["sent-file"])
                chip.append(file_icon(a.original))
                chip.append(Gtk.Label(label=a.name, ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=28))
                button.set_child(chip)
            button.connect("clicked", lambda _b, p=a.original: open_with_default(p))
            flow.append(button)
        return flow

    def _add(self, widget):
        """Activity goes above the typing dots, in the order it happened."""
        widget.add_css_class("fade-up")
        self.bubble.insert_child_after(widget, self.typing.get_prev_sibling()) if self.typing.get_prev_sibling() \
            else self.bubble.prepend(widget)
        self.app.follow()

    def status(self, text):
        if self.typing.get_parent():
            self.typing.set_text(text)
            self.typing.set_visible(True)

    def think(self, text):
        if self.reasoning is None:
            self.reasoning = Reasoning(self.app)
            self._add(self.reasoning)
            self.typing.set_visible(False)
        self.reasoning.add(text)
        self.app.follow()

    def think_done(self):
        if self.reasoning:
            self.reasoning.finish()
            self.reasoning = None
        self.typing.set_visible(True)

    def tool(self, name, args):
        box = Gtk.Box(spacing=8, css_classes=["tool"], halign=Gtk.Align.START)
        box.append(Gtk.Label(label="⚙", css_classes=["name"]))
        box.append(Gtk.Label(label=name, css_classes=["name"]))
        args = (args or "").strip()
        if args:
            box.append(Gtk.Label(label=args if len(args) < 140 else args[:137] + "…", css_classes=["args"],
                                 ellipsize=Pango.EllipsizeMode.END, max_width_chars=70, xalign=0))
        self.last_command = None
        self._add(box)

    def command(self, command):
        block = CodeBlock(self.app, "bash", agent._visible(command), command=True)
        self.last_command = block
        self._add(block)

    def write(self, action, target):
        box = Gtk.Box(spacing=8, css_classes=["tool", "write"], halign=Gtk.Align.START)
        box.append(Gtk.Label(label="✎", css_classes=["name"]))
        box.append(Gtk.Label(label=action, css_classes=["name"]))
        box.append(Gtk.Label(label=agent._visible(target), css_classes=["args"], ellipsize=Pango.EllipsizeMode.MIDDLE,
                             max_width_chars=70))
        self.last_command = None
        self._add(box)

    def ask(self, question, sensitive, answer):
        """Allow/Deny card; answer(bool) is called once. Sits inside the command it is about when there is one."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                       css_classes=["approval"] + (["sensitive"] if sensitive else []))
        top = Gtk.Box(spacing=12)
        top.append(Gtk.Image(icon_name="dialog-warning-symbolic", valign=Gtk.Align.CENTER))
        question_label = text_label(html.escape(question, quote=False), ["question"])
        question_label.set_valign(Gtk.Align.CENTER)
        top.append(question_label)
        card.append(top)
        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=250,
                          halign=Gtk.Align.END, valign=Gtk.Align.CENTER, hhomogeneous=False, interpolate_size=True)
        buttons = Gtk.Box(spacing=8)
        deny = Gtk.Button(label="Deny", css_classes=["deny"])
        allow = Gtk.Button(label="Allow", css_classes=["allow"])
        buttons.append(deny)
        buttons.append(allow)
        stack.add_named(buttons, "ask")
        verdict = Gtk.Label(css_classes=["verdict"])
        stack.add_named(verdict, "done")
        top.append(stack)

        def choose(ok):
            if card.has_css_class("answered"):
                return
            card.add_css_class("answered")
            verdict.set_label("✓  Allowed" if ok else "✕  Denied")
            verdict.add_css_class("yes" if ok else "no")
            stack.set_visible_child_name("done")
            self.app.pending_answer = None
            self.status("Working")
            answer(ok)
        allow.connect("clicked", lambda *_: choose(True))
        deny.connect("clicked", lambda *_: choose(False))
        self.app.pending_answer = choose
        self.status("Waiting for your approval")
        target = self.last_command
        if target is not None:
            card.set_margin_start(8)
            card.set_margin_end(8)
            card.set_margin_bottom(8)
            card.add_css_class("fade-up")
            target.append(card)
            self.app.follow()
        else:
            self._add(card)
        GLib.idle_add(lambda: (allow.grab_focus(), False)[1])

    def dice(self, e):
        """A roll from the record: the die tumbles, then lands on what was actually rolled."""
        d20 = bool(e.get("d20"))
        card = Gtk.Box(spacing=12, css_classes=["dnd-roll"] + (["against"] if e.get("against") else []), halign=Gtk.Align.START)
        face = Gtk.Label(css_classes=["dnd-die"], valign=Gtk.Align.CENTER, justify=Gtk.Justification.CENTER)
        card.append(face)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        words.append(Gtk.Label(label=e["label"], xalign=0, css_classes=["what"]))
        detail = Gtk.Label(xalign=0, css_classes=["sum"], label="…")
        words.append(detail)
        card.append(words)
        landed = e["kept"] if e["kept"] is not None else e["total"]
        if d20:
            rolled = " / ".join(str(r) for r in e["dice"])
            target = f" vs {'AC' if 'crit' in e else 'DC'} {e['dc']}" if e.get("dc") is not None else ""
            sum_text = f"{rolled} {e['mod']:+d} = {e['total']}{target}"
        else:
            sum_text = (" + ".join(str(r) for r in e["dice"]) or "") + (f" {e['mod']:+d}" if e["mod"] else "") + f" = {e['total']}"
        if e.get("damage") is not None:
            sum_text += f" · {e['damage']} damage"
        # What the player threw on the big dice has already been seen landing; only the enemy's still tumble here
        ticks = [10 if d20 and dnd_mode.ROLLER[0] and not e.get("against") else 0]

        def tumble():
            ticks[0] += 1
            if ticks[0] < 12:
                face.set_label(str(random.randint(1, 20)))
                return GLib.SOURCE_CONTINUE
            face.set_label(str(landed))
            face.add_css_class("landed")
            detail.set_label(sum_text)
            if d20 and e["kept"] == 20:
                face.add_css_class("crit")
            elif d20 and e["kept"] == 1:
                face.add_css_class("fumble")
            if e.get("ok") is not None:
                attack = "crit" in e
                word = "Critical!" if e.get("crit") else ("Hit" if e["ok"] else "Miss") if attack else ("Success" if e["ok"] else "Failure")
                good = e["ok"] != bool(e.get("against"))
                card.append(Gtk.Label(label=word, valign=Gtk.Align.CENTER, css_classes=["dnd-verdict", "crit" if e.get("crit") else "good" if good else "bad"]))
            return GLib.SOURCE_REMOVE
        face.set_label("?")
        GLib.timeout_add(55, tumble)
        self._add(card)

    def dnd_note(self, text):
        self._add(Gtk.Label(label=f"✦ {text}", xalign=0, css_classes=["dnd-note"], halign=Gtk.Align.START))

    def user_command(self, command, reason, answer):
        """A command only the user can run. answer() is called once, with ("finished" or "said", output) or None."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["approval", "user-run", "fade-up"])
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        words.append(text_label("Your turn: this needs you to run it", ["question"]))
        if reason:
            words.append(text_label(html.escape(reason, quote=False), ["why"]))
        top = Gtk.Box(spacing=12)
        top.append(Gtk.Image(icon_name="utilities-terminal-symbolic", valign=Gtk.Align.START))
        top.append(words)
        card.append(top)
        card.append(CodeBlock(self.app, "bash", command, command=True))
        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=250, halign=Gtk.Align.END,
                          hhomogeneous=False, interpolate_size=True)
        buttons = Gtk.Box(spacing=8)
        skip = Gtk.Button(label="Skip", css_classes=["deny"])
        said = Gtk.Button(label="I did it myself", css_classes=["later"])
        run = Gtk.Button(label="Run in terminal", css_classes=["allow"])
        for button in (skip, said, run):
            buttons.append(button)
        stack.add_named(buttons, "ask")
        running = Gtk.Box(spacing=10)
        spinner = Gtk.Spinner()
        running.append(spinner)
        running.append(Gtk.Label(label="Running in the terminal", css_classes=["running"]))
        finished_early = Gtk.Button(label="It's finished", css_classes=["later"])
        running.append(finished_early)
        stack.add_named(running, "running")
        verdict = Gtk.Label(css_classes=["verdict"])
        stack.add_named(verdict, "done")
        card.append(stack)
        since = [None]

        def choose(outcome):
            if card.has_css_class("answered"):
                return
            card.add_css_class("answered")
            spinner.stop()
            verdict.set_label("✓  Done" if outcome else "✕  Not run")
            verdict.add_css_class("yes" if outcome else "no")
            stack.set_visible_child_name("done")
            self.app.pending_answer = None
            self.status("Working")
            answer(outcome or None)

        def output(how):
            lines = agent.TERMINAL_MAX_LINES
            choose((how, self.app._terminal_text(lines if since[0] is not None else agent.TERMINAL_LINES, since[0])))

        def started(row):
            if card.has_css_class("answered"):
                return
            if row is None:  # the terminal was busy: back to the buttons
                stack.set_visible_child_name("ask")
                spinner.stop()
                return
            since[0] = row
            self.app.when_finished(lambda: card.has_css_class("answered"), lambda: output("finished"))

        def press_run(_b):
            stack.set_visible_child_name("running")
            spinner.start()
            self.app.run_in_terminal(command, started)
        skip.connect("clicked", lambda *_: choose(None))
        said.connect("clicked", lambda *_: output("said"))
        finished_early.connect("clicked", lambda *_: output("said"))
        run.connect("clicked", press_run)
        self.app.pending_answer = lambda _ok: choose(None)
        self.status("Waiting for you to run a command")
        self._add(card)

    def draft_add(self, text):
        if self.draft is None:
            self.draft = Draft(self.app)
            self._add(self.draft)
        self.draft.add(text)
        self.app.follow()

    def draft_clear(self):
        """A new model call starts: what the last one wrote was not the answer (or is about to be rewritten)."""
        if self.draft is not None:
            self.bubble.remove(self.draft)
            self.draft = None

    def finish(self, reply, took=None, steps=0, failed=False):
        self.think_done()
        self.typing.alive = False
        self.bubble.remove(self.typing)
        if failed:
            self.bubble.add_css_class("failed")
        watched = self.draft is not None and self.draft.get_visible()
        self.draft_clear()
        self.bubble.append(Answer(self.app, reply, animate=not watched))  # no second reveal of text already read
        if took is not None:
            self.bubble.append(Gtk.Label(label=f"{took:.1f}s · {steps} tool call{'s' if steps != 1 else ''}",
                                         xalign=0, css_classes=["footer", "fade-up"]))
        self.avatar.freeze()
        self.app.follow()


# --- The agent's hooks, called from the worker thread ---
class GuiSpinner:
    def __init__(self, label="Thinking"):
        self._label = label

    @property
    def label(self):
        return self._label

    @label.setter
    def label(self, value):
        self._label = value
        if APP.turn:
            ui(APP.turn.status, value)

    def start(self):
        if APP.turn:
            ui(APP.turn.status, self._label)

    def stop(self):
        pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


class GuiReasoning:
    def __init__(self):
        self.active = False
        self.buffer, self.lock, self.scheduled = [], threading.Lock(), False

    def feed(self, text):
        self.active = True
        with self.lock:
            self.buffer.append(text)
            if self.scheduled:
                return
            self.scheduled = True
        GLib.timeout_add(50, self._flush)

    def _flush(self):
        with self.lock:
            text, self.buffer, self.scheduled = "".join(self.buffer), [], False
        if text and APP.turn:
            APP.turn.think(text)
        return False

    def finish(self):
        if self.active:
            self.active = False
            GLib.timeout_add(60, lambda: (self._flush(), APP.turn and APP.turn.think_done(), False)[2])


class GuiAnswer:
    """The answer text, streamed into the window. Called from the worker thread for every few characters; the pieces
    are gathered and handed to the window at most every 50 ms, in order, whatever the stream's speed."""
    pending, lock, scheduled = [], threading.Lock(), False
    DELAY = 50

    def start(self):
        self._push(None)  # None clears the last call's draft

    def feed(self, text):
        self._push(text)

    def finish(self):
        pass

    @classmethod
    def _push(cls, item):
        with cls.lock:
            cls.pending.append(item)
            if cls.scheduled:
                return
            cls.scheduled = True
        GLib.timeout_add(cls.DELAY, cls._flush)

    @classmethod
    def _flush(cls):
        with cls.lock:
            items, cls.pending, cls.scheduled = cls.pending, [], False
        turn = APP.turn
        if turn is None:
            return False
        text = []
        for item in items:
            if item is None:  # a new call: text gathered before it is already out of date
                text = []
                turn.draft_clear()
            else:
                text.append(item)
        if text:
            turn.draft_add("".join(text))
        return False


def gui_confirm(question, sensitive=False, auto_ok=True):
    if agent.AUTO_APPROVE[0] and not sensitive and auto_ok:
        return True
    if APP.cancelled.is_set() or not APP.turn:
        return False
    done, result = threading.Event(), [False]

    def answer(ok):
        result[0] = ok
        done.set()
    APP.waiting = (done, result)
    ui(APP.turn.ask, question, sensitive, answer)
    ui(APP.attention, "The assistant needs your approval", question)
    done.wait()
    APP.waiting = None
    return result[0]


def gui_run_for_user(command, reason):
    """Worker thread: puts the command in front of the user and waits. None if they did not run it."""
    if APP.cancelled.is_set() or not APP.turn:
        return None
    done, result = threading.Event(), [None]

    def answer(outcome):
        result[0] = outcome
        done.set()
    APP.waiting = (done, result)
    ui(APP.turn.user_command, command, reason, answer)
    ui(APP.attention, "Hearthling needs you to run a command", command)
    done.wait()
    APP.waiting = None
    return result[0] or None


def gui_player_roll(request, make):
    """Worker thread: the dice go in front of the player, and the game waits for their throw. None if they stop."""
    if APP.cancelled.is_set() or not APP.turn:
        return None
    done, result = threading.Event(), [None]

    def answer(value):
        APP.pending_answer = None
        result[0] = value
        done.set()

    def show():
        APP.pending_answer = APP.dice_tray.cancel
        APP.turn.status("Your roll")
        APP.dice_tray.ask(request, make, answer)
    APP.waiting = (done, result)
    ui(show)
    ui(APP.attention, "Your roll", request["title"])
    done.wait()
    APP.waiting = None
    return result[0] or None


WEB_TOOLS = {"web_search": ("system-search-symbolic", "SEARCHING"), "news_search": ("system-search-symbolic", "NEWS SEARCH"),
             "web_fetch": ("web-browser-symbolic", "READING PAGE")}
WEB_ENTRIES_KEPT = 60
WEB_TEXT_SHOWN = 8000


def watch_web(name):
    """Wraps a web tool so each call also shows in the web panel, with exactly what came back."""
    original = agent.tools[name]

    def watched(arg=""):
        token = object()
        ui(APP.web.start, token, name, arg)
        try:
            result = original(arg) if arg != "" else original()
        except BaseException:
            ui(APP.web.finish, token, "Stopped.")
            raise
        ui(APP.web.finish, token, result)
        return result
    agent.tools[name] = watched


class WebPanel(Gtk.Box):
    """What the agent does on the web, as it happens. It has no browser of its own: each row is a real search or page
    request, and opening one shows the text the agent got back."""

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["web-panel"])
        self.app = app
        self.open_rows, self.last = {}, None
        head = Gtk.Box(spacing=8, css_classes=["web-head"])
        head.append(Gtk.Label(label="Web activity", xalign=0, css_classes=["title"]))
        self.live = Gtk.Label(label="● LIVE", css_classes=["web-live"], visible=False, hexpand=True, xalign=0)
        self.spacer = Gtk.Box(hexpand=True)
        head.append(self.live)
        head.append(self.spacer)
        head.append(mini_button("edit-clear-symbolic", "Clear this list", lambda *_: self.clear()))
        self.append(head)
        self.empty = Gtk.Label(label="Nothing yet. Searches and pages appear here as Hearthling opens them.", wrap=True,
                               justify=Gtk.Justification.CENTER, css_classes=["web-empty"], vexpand=True)
        self.append(self.empty)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["web-list"])
        self.scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, visible=False)
        self.scroller.set_child(self.list)
        self.append(self.scroller)

    def _busy(self):
        busy = bool(self.open_rows)
        self.live.set_visible(busy)
        self.spacer.set_visible(not busy)
        (self.app.web_button.add_css_class if busy else self.app.web_button.remove_css_class)("live")

    def _to_bottom(self):
        adj = self.scroller.get_vadjustment()
        GLib.timeout_add(120, lambda: (adj.set_value(adj.get_upper()), False)[1])

    def start(self, token, name, arg):
        icon, kind = WEB_TOOLS[name]
        target = agent._parse_fetch_args(arg)[0] if name == "web_fetch" else str(arg)
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["web-entry", "fade-up"])
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        words.append(Gtk.Label(label=kind, xalign=0, css_classes=["kind"]))
        words.append(Gtk.Label(label=target, xalign=0, css_classes=["target"], ellipsize=Pango.EllipsizeMode.MIDDLE,
                               tooltip_text=target))
        spinner = Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER)
        took = Gtk.Label(css_classes=["took"], valign=Gtk.Align.CENTER, visible=False)
        title = Gtk.Box(spacing=10)
        title.append(Gtk.Image(icon_name=icon, valign=Gtk.Align.CENTER))
        title.append(words)
        title.append(spinner)
        title.append(took)
        button = Gtk.Button(child=title, css_classes=["flat", "web-title"])
        row.append(button)
        reveal = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=220)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        seen_head = Gtk.Box(spacing=4, css_classes=["seen-head"])
        seen_head.append(Gtk.Label(label="WHAT THE AGENT GOT BACK", xalign=0, hexpand=True))
        if name == "web_fetch" and re.match(r"https?://", target, re.I):
            seen_head.append(mini_button("web-browser-symbolic", "Open this page in your browser",
                                         lambda *_: open_with_default(target), "Open"))
        inner.append(seen_head)
        seen = Gtk.Label(wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, xalign=0, selectable=True, css_classes=["seen"])
        inner.append(seen)
        reveal.set_child(inner)
        row.append(reveal)
        button.connect("clicked", lambda *_: reveal.set_reveal_child(not reveal.get_reveal_child()))
        self.list.append(row)
        self.open_rows[token] = (row, spinner, took, reveal, seen, time.monotonic())
        self.empty.set_visible(False)
        self.scroller.set_visible(True)
        while len(list(self._rows())) > WEB_ENTRIES_KEPT:
            self.list.remove(self.list.get_first_child())
        self._busy()
        self._to_bottom()

    def _rows(self):
        child = self.list.get_first_child()
        while child:
            yield child
            child = child.get_next_sibling()

    def finish(self, token, result):
        found = self.open_rows.pop(token, None)
        if not found:
            return
        row, spinner, took, reveal, seen, began = found
        spinner.set_spinning(False)
        spinner.set_visible(False)
        took.set_label(f"{time.monotonic() - began:.1f}s")
        took.set_visible(True)
        text = str(result)
        if not text.startswith(agent.WEB_NOTICE):
            row.add_css_class("failed")
        text = text.removeprefix(agent.WEB_NOTICE)
        if len(text) > WEB_TEXT_SHOWN:
            text = text[:WEB_TEXT_SHOWN] + f"\n… ({len(text) - WEB_TEXT_SHOWN} more characters)"
        seen.set_text(text)
        # Follow the newest result, the way a browser shows the page it is on
        if self.last is not None and self.last.get_parent() is not None:
            self.last.set_reveal_child(False)
        reveal.set_reveal_child(True)
        self.last = reveal
        self._busy()
        self._to_bottom()

    def clear(self):
        for child in list(self._rows()):
            self.list.remove(child)
        self.open_rows.clear()
        self.last = None
        self.empty.set_visible(True)
        self.scroller.set_visible(False)
        self._busy()


class CharacterPanel(Gtk.Box):
    """The player's character, live from the campaign record: it can only show what is really on the sheet."""

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["sheet"])
        self.app, self.last = app, None
        self.stack = Adw.ViewStack(vexpand=True)
        self.pages = {}
        for key, title, icon in (("sheet", "Hero", "avatar-default-symbolic"), ("gear", "Gear", "folder-symbolic"), ("journal", "Story", "accessories-text-editor-symbolic")):
            scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            self.pages[key] = scroller
            self.stack.add_titled_with_icon(scroller, key, title, icon)
        self.books = dnd_ui.BooksPage(lambda: app.window, app.toast)
        self.stack.add_titled_with_icon(Gtk.ScrolledWindow(child=self.books, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True), "books", "Books", "accessories-dictionary-symbolic")
        self.append(Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.append(self.stack)

    @staticmethod
    def _page():
        return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["sheet-page"])

    @staticmethod
    def _section(box, title):
        box.append(Gtk.Label(label=title, xalign=0, css_classes=["sheet-label", "sheet-section"]))

    @staticmethod
    def _wrap(text, css):
        return Gtk.Label(label=text, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, css_classes=css, selectable=False)

    @staticmethod
    def _tile(name, value, glint=False, tip=None):
        tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["sheet-tile"] + (["glint"] if glint else []), hexpand=True, tooltip_text=tip)
        tile.append(Gtk.Label(label=str(value), css_classes=["value"]))
        tile.append(Gtk.Label(label=name, css_classes=["name"]))
        return tile

    def _say_button(self, css, say, *children, tip=None):
        button = Gtk.Button(css_classes=[css, "flat"], tooltip_text=tip)
        if len(children) == 1:
            button.set_child(children[0])
        button.connect("clicked", lambda *_: self.app.say(say))
        return button

    def refresh(self):
        data = dnd_mode.view()
        c = data["character"]
        self._sheet(data, c)
        self._gear(c)
        self._journal(data)
        self.last = c

    def _sheet(self, data, c):
        box = self._page()
        if not c:
            box.append(Gtk.Label(label="No hero sits by the fire yet.", wrap=True, justify=Gtk.Justification.CENTER, css_classes=["sheet-empty"]))
            create = Gtk.Button(label="Forge your hero", css_classes=["allow"], halign=Gtk.Align.CENTER)
            create.connect("clicked", lambda *_: self.app.open_builder())
            box.append(create)
            self.pages["sheet"].set_child(box)
            return
        last = self.last
        top = Gtk.Box(spacing=12)
        top.append(Gtk.Label(label=c["name"][:1].upper(), css_classes=["sheet-crest"], valign=Gtk.Align.CENTER))
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        words.append(self._wrap(c["name"], ["sheet-name"]))
        words.append(self._wrap(f"{c['species']} {c['class'].capitalize()} {c['level']}" + (f" ({c['subclass']})" if c.get("subclass") else "") + f" · {c['background']}", ["sheet-class"]))
        top.append(words)
        box.append(top)
        if c.get("needs_subclass"):
            pick = Gtk.Button(label="Choose your subclass", css_classes=["allow"], halign=Gtk.Align.FILL, margin_top=6, tooltip_text="You reached level 3: choose the path your class takes.")
            pick.connect("clicked", lambda *_: self.app.open_subclass())
            box.append(pick)
        if c["xp_next"]:
            floor = dnd_mode.XP_FOR_LEVEL[c["level"] - 1]
            xp = Gtk.ProgressBar(fraction=max(0.0, min(1.0, (c["xp"] - floor) / (c["xp_next"] - floor))), css_classes=["xp"], tooltip_text=f"{c['xp']} of {c['xp_next']} XP")
            box.append(xp)
        hp = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["sheet-hp", "sheet-section"])
        if last and last["name"] == c["name"] and c["hp"] < last["hp"]:
            hp.add_css_class("hurt")
        row = Gtk.Box(spacing=8)
        row.append(Gtk.Label(label="HIT POINTS", css_classes=["sheet-label"], hexpand=True, xalign=0))
        row.append(Gtk.Label(label=f"{c['hp']} / {c['max_hp']}" + (f"  +{c['temp_hp']}" if c["temp_hp"] else ""), css_classes=["value"]))
        hp.append(row)
        fraction = c["hp"] / c["max_hp"] if c["max_hp"] else 0
        hp.append(Gtk.ProgressBar(fraction=fraction, css_classes=["hp"] + (["dying"] if fraction <= 0.25 else ["bloodied"] if fraction <= 0.5 else [])))
        box.append(hp)
        if c["hp"] == 0 and not c.get("dead"):
            box.append(self._wrap(f"Dying: {c['death']['s']} successes, {c['death']['f']} failures" if not c.get("stable") else "Stable", ["sheet-condition"]))
        if c.get("dead"):
            box.append(self._wrap("Fallen. /mode dnd new begins a new tale.", ["sheet-condition"]))
        tiles = Gtk.Box(spacing=6, homogeneous=True)
        tiles.append(self._tile("AC", c["ac"], tip="Armor Class: an attack must equal or beat this to hit you."))
        tiles.append(self._tile("INIT", f"{c['initiative']:+d}", tip="Initiative: added to your roll to set the order of a fight."))
        tiles.append(self._tile("SPEED", c["speed"], tip="How many feet you can move on your turn."))
        tiles.append(self._tile("PROF", f"{c['proficiency']:+d}", tip="Proficiency bonus: added to attacks, saves and skills you are trained in. It grows with level."))
        if c["save_dc"]:
            tiles.append(self._tile("SPELL DC", c["save_dc"], tip="Spell save DC: what enemies must beat to resist your spells."))
        box.append(tiles)
        flags = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, column_spacing=4, row_spacing=4)
        if c["inspiration"]:
            flags.append(Gtk.Label(label="★ Heroic Inspiration", css_classes=["sheet-star"], tooltip_text=dnd_mode.RULES["heroic inspiration"]))
        if c.get("raging"):
            flags.append(Gtk.Label(label="Raging", css_classes=["sheet-condition"], tooltip_text=dnd_mode.FEATURE_TIPS["Rage"]))
        for name in c["conditions"]:
            flags.append(Gtk.Label(label=name.capitalize(), css_classes=["sheet-condition"], tooltip_text=dnd_mode.RULES.get(name)))
        if c["exhaustion"]:
            flags.append(Gtk.Label(label=f"Exhaustion {c['exhaustion']}", css_classes=["sheet-condition"], tooltip_text=dnd_mode.RULES["exhaustion"]))
        if flags.get_first_child():
            box.append(flags)
        if data["combat"]:
            self._combat(box, data["combat"])
        self._section(box, "ABILITIES")
        grid = Gtk.Grid(column_spacing=6, row_spacing=6, column_homogeneous=True)
        for i, ability in enumerate(dnd_mode.ABILITIES):
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            cell.append(Gtk.Label(label=ability.upper(), css_classes=["name"]))
            cell.append(Gtk.Label(label=f"{c['modifiers'][ability]:+d}", css_classes=["value"]))
            cell.append(Gtk.Label(label=f"{c['abilities'][ability]}" + (" · save" if ability in c["saves"] else ""), css_classes=["score"]))
            full = dnd_mode.ABILITY_NAMES[ability].capitalize()
            grid.attach(self._say_button("sheet-ability", f"I try a {full} check: ", cell, tip=f"{full}. {dnd_mode.ABILITY_TIPS[ability]}"), i % 3, i // 3, 1, 1)
        box.append(grid)
        self._section(box, "ACTIONS")
        for attack in c["attacks"]:
            row = Gtk.Box(spacing=8)
            row.append(Gtk.Label(label=attack["name"], hexpand=True, xalign=0))
            row.append(Gtk.Label(label=f"{attack['to_hit']:+d} · {attack['damage']}", css_classes=["detail"]))
            box.append(self._say_button("sheet-action", f"I attack with my {attack['name']}: ", row, tip=attack["tip"]))
        self._abilities(box, c)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=3, column_spacing=4, row_spacing=4, homogeneous=True)
        for action in c["standard_actions"]:
            flow.append(self._say_button("sheet-chip", f"I use the {action} action: ", Gtk.Label(label=action), tip=dnd_mode.RULES.get(action.lower())))
        box.append(flow)
        if c["slots"] or c["spells"]:
            self._section(box, "MAGIC")
            for level, slot in sorted(c["slots"].items()):
                row = Gtk.Box(spacing=5)
                row.append(Gtk.Label(label=f"Level {level}", css_classes=["sheet-note"], width_chars=8, xalign=0))
                for i in range(slot["max"]):
                    row.append(Gtk.Box(css_classes=["sheet-pip"] + (["spent"] if i >= slot["max"] - slot["used"] else []), valign=Gtk.Align.CENTER))
                box.append(row)
            spells = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, column_spacing=4, row_spacing=4)
            for spell in c["spells"]:
                spells.append(self._say_button("sheet-chip", f"I cast {spell['name']}: ", Gtk.Label(label=spell["name"], ellipsize=Pango.EllipsizeMode.END, max_width_chars=18),
                                               tip=dnd_mode.SPELL_TIPS.get(spell["name"], spell["name"])))
            box.append(spells)
        skills = Gtk.Expander(label="Skills", css_classes=["sheet-section"])
        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for skill, bonus in sorted(c["skill_bonus"].items()):
            row = Gtk.Box(spacing=8)
            row.append(Gtk.Label(label=("● " if skill in c["skills"] else "○ ") + skill.capitalize(), hexpand=True, xalign=0))
            row.append(Gtk.Label(label=f"{bonus:+d}"))
            rows.append(self._say_button("sheet-action", f"I try {skill.capitalize()}: ", row, tip=dnd_mode.SKILL_TIPS[skill]))
        skills.set_child(rows)
        box.append(skills)
        self.pages["sheet"].set_child(box)

    def _abilities(self, box, c):
        """Limited abilities: one click uses them, and the pips show what is left."""
        usable = [r for r in c["ready"] if r["how"] != "auto"]
        if not usable:
            return
        for ready in usable:
            row = Gtk.Box(spacing=5)
            row.append(Gtk.Label(label=ready["name"], hexpand=True, xalign=0))
            if ready["max"] <= 6:
                for i in range(ready["max"]):
                    row.append(Gtk.Box(css_classes=["sheet-pip"] + (["spent"] if i >= ready["left"] else []), valign=Gtk.Align.CENTER))
            else:
                row.append(Gtk.Label(label=f"{ready['left']} / {ready['max']}", css_classes=["detail"]))
            button = Gtk.Button(child=row, css_classes=["sheet-ability-use", "flat"], tooltip_text=ready["tip"], sensitive=ready["left"] > 0)
            button.connect("clicked", lambda *_, n=ready["name"]: self.app.send(f"I use {n}."))
            box.append(button)

    def _combat(self, box, combat):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["sheet-combat", "sheet-section"])
        panel.append(Gtk.Label(label=f"COMBAT · ROUND {combat['round']}", xalign=0, css_classes=["sheet-label"]))
        for i, who in enumerate(combat["order"]):
            row = Gtk.Box(spacing=8, css_classes=["sheet-foe"] + (["now"] if i == combat["turn"] else []) + (["fallen"] if who.get("defeated") else []))
            row.append(Gtk.Label(label=str(who["init"]), width_chars=3))
            row.append(Gtk.Label(label=who["name"], hexpand=True, xalign=0))
            if not who.get("player"):  # the player sees wounds, never numbers
                state = "Defeated" if who.get("defeated") else "Bloodied" if who["hp"] * 2 <= who["max_hp"] else "Unhurt" if who["hp"] == who["max_hp"] else "Wounded"
                row.append(Gtk.Label(label=state, css_classes=["sheet-note"]))
            panel.append(row)
        eco = Gtk.Box(spacing=4, margin_top=4)
        for key, label in (("action", "Action"), ("bonus", "Bonus"), ("reaction", "Reaction")):
            eco.append(Gtk.Label(label=label, css_classes=["sheet-eco"] + (["used"] if combat["economy"][key] else [])))
        panel.append(eco)
        box.append(panel)

    def _gear(self, c):
        box = self._page()
        if not c:
            self.pages["gear"].set_child(box)
            return
        last = self.last
        purse = Gtk.Box(spacing=6, homogeneous=True)
        for key, label in (("gp", "GOLD"), ("sp", "SILVER"), ("cp", "COPPER")):
            purse.append(self._tile(label, c["gold"][key], glint=bool(last and last["gold"][key] != c["gold"][key])))
        box.append(purse)
        self._section(box, "INVENTORY")
        for item in c["inventory"]:
            row = Gtk.Box(spacing=8, css_classes=["sheet-row"])
            row.append(Gtk.Label(label="◆" if item.get("equipped") else "◇", css_classes=["equipped"]))
            words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            words.append(self._wrap(item["name"] + (f" ×{item['qty']}" if item["qty"] > 1 else ""), []))
            note = " · ".join(x for x in (item.get("damage"), item.get("mastery"), item.get("note")) if x)
            if note:
                words.append(self._wrap(note, ["note"]))
            row.append(words)
            tip = item.get("note") or None
            if item.get("damage"):
                tip = f"Damage {item['damage']}." + (f"\nMastery, {item['mastery']}: {dnd_mode.MASTERY_TIPS.get(item['mastery'], '')}" if item.get("mastery") else "")
            box.append(self._say_button("sheet-chip", f"I use my {item['name']}: ", row, tip=tip))
        if not c["inventory"]:
            box.append(self._wrap("Empty pockets.", ["sheet-note"]))
        if c["features"]:
            self._section(box, "FEATURES")
            for feature in c["features"]:
                label = self._wrap(feature, ["sheet-row"])
                label.set_tooltip_text(c["tips"].get(feature) or None)
                box.append(label)
        self.pages["gear"].set_child(box)

    def _journal(self, data):
        box = self._page()
        scene = data["scene"]
        if any(scene.values()):
            self._section(box, "NOW")
            box.append(self._wrap(" · ".join(x for x in (scene["location"], scene["time"]) if x), ["sheet-entry-name"]))
            if scene["situation"]:
                box.append(self._wrap(scene["situation"], ["sheet-note"]))

        def book(title, entries):
            if entries:
                self._section(box, title)
            for name, e in reversed(list(entries.items())):
                box.append(self._wrap(name + (f" ({e['status']})" if e.get("status") else ""), ["sheet-entry-name"]))
                if e["text"]:
                    box.append(self._wrap(e["text"], ["sheet-note"]))
        book("QUESTS", data["quests"])
        book("PEOPLE", data["npcs"])
        book("PLACES", data["locations"])
        book("ALSO MENTIONED", data["mentions"])
        if data["facts"]:
            self._section(box, "CLUES AND SECRETS")
            for e in reversed(data["facts"]):
                box.append(self._wrap(f"{e['kind'].capitalize()}: {e['text']}", ["sheet-note"]))
        if data["chronicle"] or data["beats"]:
            self._section(box, "THE STORY SO FAR")
            for e in reversed(data["beats"]):
                box.append(self._wrap(e["text"], ["sheet-note"]))
            for e in reversed(data["chronicle"]):
                box.append(self._wrap(e["text"], ["sheet-note"]))
        if not box.get_first_child():
            box.append(self._wrap("The pages are blank. For now.", ["sheet-empty"]))
        self.pages["journal"].set_child(box)


def install_hooks():
    agent.GUI[0] = True
    agent.Spinner = GuiSpinner
    agent.ReasoningView = GuiReasoning
    agent.AnswerView = GuiAnswer
    agent._confirm = gui_confirm
    # ask_user_to_run shows its own card
    agent.ui_tool = lambda name, args: (ui(APP.turn.tool, name, args) if APP.turn and name != "ask_user_to_run" and
                                        name not in dnd_mode.TOOL_NAMES else None)
    dnd_mode.LISTENERS.append(lambda kind, data: ui(APP.on_table_event, kind, data))
    dnd_mode.ROLLER[0] = gui_player_roll
    agent.ui_command = lambda command: ui(APP.turn.command, command) if APP.turn else None
    agent.ui_write = lambda action, target: ui(APP.turn.write, action, target) if APP.turn else None
    if Vte:
        agent.TERMINAL_READER[0] = APP.read_terminal
        agent.TERMINAL_RUNNER[0] = gui_run_for_user
    for name in WEB_TOOLS:
        watch_web(name)


def plain(text):
    return agent._ANSI_RE.sub("", text)


# --- The window ---
COLUMN = 860  # widest the chat column gets; narrower windows use their full width
INPUT_MAX_HEIGHT = 160


def column(child):
    clamp = Adw.Clamp(maximum_size=COLUMN, tightening_threshold=COLUMN - 160, vexpand=child.get_vexpand())
    clamp.set_child(child)
    return clamp


class Assistant(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.turn, self.worker, self.waiting, self.pending_answer = None, None, None, None
        self.in_table, self.table_generation = False, 0
        self.cancelled = threading.Event()
        self.history, self.recall = [], None
        self.attachments = []
        self.terminal = None
        self.window = None

    # Setup
    def do_activate(self):
        if self.window:
            self.window.present()
            return
        self.live_theme = livetheme.follow(self)  # follows a theme override switch while open
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if DARK else Adw.ColorScheme.FORCE_LIGHT)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.window = Adw.ApplicationWindow(application=self, title="Hearthling", default_width=900,
                                            default_height=760, css_classes=["assistant"])
        self.toasts = Adw.ToastOverlay()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        layered = Gtk.Overlay()
        layered.set_child(root)
        layered.add_overlay(self._drop_zone())
        self.dice_tray = dnd_ui.DiceTray()
        layered.add_overlay(self.dice_tray)
        self.toasts.set_child(layered)
        self.window.set_content(self.toasts)

        root.append(self._header())
        self.scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        # The chat and everything under it share one centred column, so their edges line up at any window width
        self.chat = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=["chat"], vexpand=True)
        self.scroller.set_child(column(self.chat))
        adj = self.scroller.get_vadjustment()
        self.stick = True
        adj.connect("value-changed", self._on_scroll)
        adj.connect("changed", lambda a: self.stick and a.set_value(a.get_upper() - a.get_page_size()))
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.append(self.scroller)
        self.web = WebPanel(self)
        split = Adw.OverlaySplitView(sidebar_position=Gtk.PackType.END, show_sidebar=False, collapsed=False, vexpand=True,
                                     min_sidebar_width=380, max_sidebar_width=560, sidebar_width_fraction=0.3,
                                     content=page, sidebar=self.web)
        self.web_button.connect("toggled", lambda b: split.set_show_sidebar(b.get_active()))
        self.character = CharacterPanel(self)
        self.sheet_split = Adw.OverlaySplitView(sidebar_position=Gtk.PackType.START, show_sidebar=False, collapsed=False, vexpand=True,
                                                min_sidebar_width=340, max_sidebar_width=420, sidebar_width_fraction=0.26,
                                                content=split, sidebar=self.character)
        root.append(self.sheet_split)

        self.welcome = self._welcome()
        self.chat.append(self.welcome)
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["bottom"])
        for part in (self._terminal_pane(), self._slash_menu(), self._attach_tray(), self._composer(), self._statusbar()):
            bottom.append(part)
        page.append(column(bottom))
        self._actions()
        self.window.present()
        self.input.grab_focus()

        agent.start_session()
        for sig in (2, 1, 15):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda *_: (self.quit(), False)[1])
        self.connect("shutdown", lambda *_: (agent.end_session(), shutil.rmtree(UPLOAD_DIR, ignore_errors=True)))
        threading.Thread(target=self._startup, daemon=True).start()

    def _header(self):
        header = Adw.HeaderBar(css_classes=["assistant-header"])
        title = Gtk.Box(spacing=10)
        self.header_logo = Logo(30, intro=True, particles=False)
        title.append(self.header_logo)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.title_label = Gtk.Label(label="Hearthling", xalign=0, css_classes=["title-main"])
        words.append(self.title_label)
        self.subtitle = Gtk.Label(xalign=0, css_classes=["title-sub"])
        words.append(self.subtitle)
        title.append(words)
        header.set_title_widget(title)

        menu = Gio.Menu()
        main = Gio.Menu()
        main.append("Ask before changes", "app.approvals")
        main.append("Show reasoning", "app.reasoning")
        menu.append_section(None, main)
        effort = Gio.Menu()
        for level in agent.THINK_EFFORTS:
            effort.append(level.capitalize(), f"app.effort::{level}")
        menu.append_submenu("Thinking effort", effort)
        modes = Gio.Menu()
        for name in agent_modes.completions():
            modes.append(name, f"app.mode::{name}")
        menu.append_submenu("Mode", modes)
        other = Gio.Menu()
        other.append("Paste image from clipboard", "app.paste")
        other.append("New chat", "app.clear")
        menu.append_section(None, other)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Options"))
        self.term_button = Gtk.ToggleButton(icon_name="utilities-terminal-symbolic", tooltip_text="Terminal (Ctrl+`)")
        self.term_button.connect("toggled", lambda b: self.show_terminal(b.get_active()))
        header.pack_end(self.term_button)
        self.web_button = Gtk.ToggleButton(icon_name="web-browser-symbolic", css_classes=["web-toggle"],
                                           tooltip_text="Watch what Hearthling is doing on the web")
        header.pack_end(self.web_button)
        self.sheet_button = Gtk.ToggleButton(icon_name="avatar-default-symbolic", tooltip_text="Your character", active=True, visible=False)
        self.sheet_button.connect("toggled", lambda b: self.sheet_split.set_show_sidebar(b.get_active() and self.in_table))
        header.pack_start(self.sheet_button)
        return header

    def _hide_the_door(self, logo):
        """Five quick pokes at the fire open the hidden Dungeon Master mode."""
        pokes = []

        def poked(*_):
            now = time.monotonic()
            pokes[:] = [t for t in pokes if now - t < 3] + [now]
            logo.stoke()
            if len(pokes) >= 5 and not self.worker:
                pokes.clear()
                self.send("/mode dnd")
        click = Gtk.GestureClick()
        click.connect("pressed", poked)
        logo.add_controller(click)

    def _welcome(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["welcome"],
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.big_logo = Logo(150, intro=bool(agent.SETTINGS["animated_logo"]))
        self.big_logo.set_halign(Gtk.Align.CENTER)
        box.append(self.big_logo)
        self._hide_the_door(self.big_logo)
        box.append(Gtk.Label(label=agent.greeting(), css_classes=["greeting"], justify=Gtk.Justification.CENTER, wrap=True))
        box.append(Gtk.Label(label="Your friendly AI helper for this PC and beyond. Ask in plain English.", css_classes=["tagline"],
                             justify=Gtk.Justification.CENTER, wrap=True))
        self.status_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, column_spacing=8,
                                      row_spacing=8, margin_top=14, halign=Gtk.Align.CENTER)
        self.status_box.append(Gtk.Label(label="Starting Ollama…", css_classes=["status-pill"]))
        box.append(self.status_box)
        box.append(Gtk.Label(label="TRY ASKING", css_classes=["section-label"]))
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1, max_children_per_line=2,
                           column_spacing=10, row_spacing=10, halign=Gtk.Align.CENTER, homogeneous=True)
        for prompt in random.sample(agent.EXAMPLE_PROMPTS, 4):
            button = Gtk.Button(css_classes=["suggestion"])
            button.set_child(Gtk.Label(label=prompt, wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=44))
            button.connect("clicked", lambda _b, p=prompt: self.send(p))
            flow.append(button)
        box.append(flow)
        # Expands while it is the only thing in the chat, so it sits in the middle of the window
        revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=450,
                                reveal_child=True, vexpand=True)
        revealer.set_child(box)
        return revealer

    def _startup(self):
        ok = agent.ensure_ollama_running()
        lines = []
        if not ok:
            lines.append(("✗ Could not reach or start the Ollama server (is ollama installed?)", True))
        else:
            def model(role, name):
                installed = agent.model_installed(name)
                if installed is False:
                    return (f"⚠  {role}: {name} not installed · ollama pull {name}", True)
                return (f"●  {role}  {name}", False)
            lines.append(model("Chat", agent.chat_model()))
            if not agent.VISION_ENABLED:
                lines.append(("○  Vision off", False))
            elif agent.VISION_SAME:
                lines.append(("●  Vision  same model", False))
            else:
                lines.append(model("Vision", agent.VISION_MODEL))
        health = plain(agent.health_summary()).replace(" ask me about them", "").replace("health monitor: ", "")
        lines.append((health, "⚠" in health))
        ui(self._show_status, lines)

    def _show_status(self, lines):
        while child := self.status_box.get_first_child():
            self.status_box.remove(child)
        for text, warn in lines:
            css = ["status-pill", "fade-up", "warn" if warn else "ok"]
            if warn and "health monitor" in text:  # a click asks about what it flagged
                pill = Gtk.Button(label=text, css_classes=css, tooltip_text="Ask what the health monitor found")
                pill.connect("clicked", lambda *_: self.send("What issues did the health monitor flag?"))
            else:
                pill = Gtk.Label(label=text, css_classes=css)
            self.status_box.append(pill)

    def _slash_menu(self):
        self.slash_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=200)
        self.slash_box = Gtk.Box(spacing=6)
        scroller = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                      css_classes=["slash-menu"])
        scroller.set_child(self.slash_box)
        self.slash_revealer.set_child(scroller)
        return self.slash_revealer

    def _composer(self):
        box = Gtk.Box(spacing=8, css_classes=["composer"])
        attach = Gtk.Button(icon_name="mail-attachment-symbolic", css_classes=["flat", "attach"], valign=Gtk.Align.END,
                            margin_bottom=1,
                            tooltip_text="Attach pictures or files (or paste / drop them here)")
        attach.connect("clicked", lambda *_: self.choose_files())
        box.append(attach)
        self.input = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, hexpand=True, accepts_tab=False,
                                  top_margin=11, bottom_margin=11, left_margin=4)
        self.input.get_buffer().connect("changed", self._on_input_changed)
        self.input.connect("paste-clipboard", self._on_paste)
        # No scrollbar until the text fills the box: even hidden, its minimum height would make one line look tall
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                                      propagate_natural_height=True, max_content_height=INPUT_MAX_HEIGHT, hexpand=True)
        scroller.set_child(self.input)
        self.input_scroller = scroller
        # Lined up with where typed text starts
        self.placeholder = Gtk.Label(label="Ask anything, or type / for commands", xalign=0, can_target=False,
                                     css_classes=["placeholder"], valign=Gtk.Align.START, margin_top=11, margin_start=4,
                                     ellipsize=Pango.EllipsizeMode.END)
        overlay = Gtk.Overlay(hexpand=True)
        overlay.set_child(scroller)
        overlay.add_overlay(self.placeholder)
        box.append(overlay)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.input.add_controller(keys)
        self.send_button = Gtk.Button(icon_name="go-up-symbolic", css_classes=["send"], valign=Gtk.Align.END,
                                      tooltip_text="Send (Enter)")
        self.send_button.connect("clicked", lambda *_: self.stop() if self.worker else self.send())
        box.append(self.send_button)
        return box

    # Attachments
    def _attach_tray(self):
        self.tray = Gtk.Box(spacing=8)
        scroller = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                      css_classes=["attach-tray"])
        scroller.set_child(self.tray)
        self.tray_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=240)
        self.tray_revealer.set_child(scroller)
        return self.tray_revealer

    def _drop_zone(self):
        zone = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.FILL, halign=Gtk.Align.FILL,
                       css_classes=["drop-zone"])
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.CENTER, vexpand=True)
        inner.append(Gtk.Image(icon_name="document-send-symbolic", pixel_size=56))
        inner.append(Gtk.Label(label="Drop to attach", css_classes=["big"]))
        inner.append(Gtk.Label(label="Pictures are read by the vision model · other files go with your question",
                               css_classes=["small"]))
        zone.append(inner)
        self.drop_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, transition_duration=180,
                                          can_target=False)
        self.drop_revealer.set_child(zone)
        target = Gtk.DropTarget.new(GObject.TYPE_NONE, Gdk.DragAction.COPY)
        target.set_gtypes([Gdk.FileList, Gdk.Texture])
        target.connect("enter", lambda *_: (self.drop_revealer.set_reveal_child(True), Gdk.DragAction.COPY)[1])
        target.connect("leave", lambda *_: self.drop_revealer.set_reveal_child(False))
        target.connect("drop", self._on_drop)
        self.window.add_controller(target)
        return self.drop_revealer

    def _on_drop(self, _target, value, _x, _y):
        self.drop_revealer.set_reveal_child(False)
        if isinstance(value, Gdk.Texture):
            self.add_texture(value, "dropped image")
        else:
            self.add_files(value.get_files())
        return True

    def _on_paste(self, view):
        """Ctrl+V: files copied in a file manager and pictures (screenshots, images copied in a browser) become
        attachments; anything else pastes as text as usual."""
        clipboard = view.get_clipboard()
        formats = clipboard.get_formats()
        if formats.contain_gtype(Gdk.FileList):
            GObject.signal_stop_emission_by_name(view, "paste-clipboard")
            clipboard.read_value_async(Gdk.FileList, GLib.PRIORITY_DEFAULT, None, self._pasted_files)
        elif any(GObject.type_is_a(t, Gdk.Texture) for t in formats.get_gtypes() or []) \
                or any(m.startswith("image/") for m in formats.get_mime_types() or []):
            GObject.signal_stop_emission_by_name(view, "paste-clipboard")
            clipboard.read_texture_async(None, self._pasted_texture)

    def _pasted_files(self, clipboard, result):
        try:
            self.add_files(clipboard.read_value_finish(result).get_files())
        except GLib.Error as e:
            self.toast(f"Could not paste the files: {e.message}")

    def _pasted_texture(self, clipboard, result):
        try:
            texture = clipboard.read_texture_finish(result)
        except GLib.Error as e:
            self.toast(f"Could not paste the picture: {e.message}")
            return
        if texture:
            self.add_texture(texture, "pasted image")

    def choose_files(self):
        dialog = Gtk.FileDialog(title="Attach pictures or files", modal=True)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        images = Gtk.FileFilter(name="Pictures")
        images.add_pixbuf_formats()
        everything = Gtk.FileFilter(name="All files")
        everything.add_pattern("*")
        filters.append(everything)
        filters.append(images)
        dialog.set_filters(filters)
        dialog.set_default_filter(everything)
        dialog.set_initial_folder(Gio.File.new_for_path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
                                                        or os.path.expanduser("~")))

        def chosen(dlg, result):
            try:
                files = dlg.open_multiple_finish(result)
            except GLib.Error:
                return  # cancelled
            self.add_files([files.get_item(i) for i in range(files.get_n_items())])
        dialog.open_multiple(self.window, None, chosen)

    def add_files(self, files):
        for f in files:
            path = f.get_path()
            if not path:
                self.toast(f"{f.get_uri()} is not a local file, so it cannot be attached")
                continue
            if any(a.original == path for a in self.attachments):
                continue
            name = os.path.basename(path.rstrip("/")) or path
            if mime_of(path).startswith("image/"):
                if os.path.getsize(path) > IMAGE_MAX_BYTES:
                    self.toast(f"{name} is larger than {IMAGE_MAX_BYTES // 1_000_000} MB")
                    continue
                try:
                    self._attach(Attachment("image", save_image(path, os.path.splitext(name)[0]), name, path))
                    continue
                except GLib.Error:
                    pass  # an image type GdkPixbuf cannot read (some SVGs, RAW): pass it on as a file
            self._attach(Attachment("file", path, name))

    def add_texture(self, texture, label):
        stem = f"{label.replace(' ', '-')}-{time.strftime('%H%M%S')}"
        path = upload_path(stem)
        texture.save_to_png(path)
        if max(texture.get_width(), texture.get_height()) > IMAGE_MAX_SIDE:
            big, path = path, save_image(path, stem)
            os.remove(big)
        self._attach(Attachment("image", path, label))

    def _attach(self, attachment):
        self.attachments.append(attachment)
        chip = Gtk.Overlay(css_classes=["attachment", attachment.kind], tooltip_text=attachment.original)
        if attachment.kind == "image":
            chip.set_child(thumbnail(attachment.path, 72))
        else:
            row = Gtk.Box(spacing=8)
            row.append(file_icon(attachment.original))
            words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
            words.append(Gtk.Label(label=attachment.name, xalign=0, css_classes=["name"],
                                   ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=24))
            words.append(Gtk.Label(label="folder" if os.path.isdir(attachment.original) else human_size(attachment.size),
                                   xalign=0, css_classes=["size"]))
            row.append(words)
            row.append(Gtk.Box(width_request=26))  # room for the remove button
            chip.set_child(row)
        remove = Gtk.Button(icon_name="window-close-symbolic", css_classes=["remove"], halign=Gtk.Align.END,
                            valign=Gtk.Align.START if attachment.kind == "image" else Gtk.Align.CENTER,
                            tooltip_text="Remove")
        remove.connect("clicked", lambda *_: self._detach(attachment, chip))
        chip.add_overlay(remove)
        self.tray.append(chip)
        self.tray_revealer.set_reveal_child(True)
        self._update_send()
        self.input.grab_focus()

    def _detach(self, attachment, chip):
        if attachment in self.attachments:
            self.attachments.remove(attachment)
        if attachment.kind == "image" and attachment.path.startswith(UPLOAD_DIR):
            try:
                os.remove(attachment.path)
            except OSError:
                pass
        self.tray.remove(chip)
        self.tray_revealer.set_reveal_child(bool(self.attachments))
        self._update_send()

    def _clear_tray(self):
        self.attachments = []
        while child := self.tray.get_first_child():
            self.tray.remove(child)
        self.tray_revealer.set_reveal_child(False)

    def _update_send(self):
        if not self.worker:
            self.send_button.set_sensitive(bool(self._text().strip() or self.attachments))

    def _statusbar(self):
        bar = Gtk.Box(spacing=6, css_classes=["statusbar"])
        self.pill_mode = Gtk.MenuButton(css_classes=["pill"], always_show_arrow=False)
        menu = Gio.Menu()
        for name in agent_modes.completions():
            menu.append(name, f"app.mode::{name}")
        self.pill_mode.set_menu_model(menu)
        self.pill_approvals = Gtk.Button(css_classes=["pill", "flat"])
        self.pill_approvals.connect("clicked", lambda *_: self.activate_action("approvals"))
        self.pill_think = Gtk.Button(css_classes=["pill", "flat"])
        self.pill_think.connect("clicked", lambda *_: self._cycle_effort())
        for pill in (self.pill_mode, self.pill_approvals, self.pill_think):
            bar.append(pill)
        bar.append(Gtk.Label(hexpand=True))
        bar.append(Gtk.Label(label="Enter to send · Shift+Enter for a new line", ellipsize=Pango.EllipsizeMode.END, css_classes=["footer"]))
        self.refresh_status()
        return bar

    def _terminal_pane(self):
        # vexpand off: the terminal inside expands, and that would pull space from the chat even while hidden
        self.term_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
                                          transition_duration=320, vexpand=False)
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["terminal-pane"], height_request=280)
        head = Gtk.Box(spacing=6, css_classes=["terminal-head"])
        head.append(Gtk.Label(label="  Terminal", hexpand=True, xalign=0))
        head.append(mini_button("window-close-symbolic", "Hide the terminal", lambda *_: self.term_button.set_active(False)))
        pane.append(head)
        if Vte:
            self.terminal = Vte.Terminal(vexpand=True, hexpand=True, margin_start=8, margin_end=8, margin_bottom=8)
            self.terminal.set_font(Pango.FontDescription.from_string("CaskaydiaCove Nerd Font Mono 11"))
            self.terminal.set_scrollback_lines(5000)
            self._terminal_colours()
            self.terminal.connect("child-exited", lambda *_: (setattr(self, "term_alive", False), setattr(self, "term_pid", None)))
            self.term_alive, self.term_pid = False, None
            pane.append(self.terminal)
        else:
            pane.append(Gtk.Label(label="The built-in terminal needs the vte4 package:  sudo pacman -S vte4\n"
                                        "Until then, Run opens your own terminal.", vexpand=True,
                                  css_classes=["status-line"], selectable=True))
        self.term_revealer.set_child(pane)
        return self.term_revealer

    def _terminal_colours(self):
        def colour(value):
            c = Gdk.RGBA()
            c.parse(value)
            return c
        fg = colour(PALETTE.get("foreground", C["base_text"]))
        bg = colour("rgba(0,0,0,0)")
        slots = [PALETTE.get(f"color{i}") for i in range(16)]
        if all(slots):
            self.terminal.set_colors(fg, bg, [colour(s) for s in slots])
        else:
            self.terminal.set_colors(fg, bg, None)
        self.terminal.set_color_cursor(colour(C["accent"]))

    def _spawn_shell(self):
        shell = os.environ.get("SHELL") or "/bin/bash"
        def spawned(_terminal, pid, *_rest):
            self.term_pid = pid if pid and pid > 0 else None
        args = (Vte.PtyFlags.DEFAULT, os.path.expanduser("~"), [shell], None, GLib.SpawnFlags.DEFAULT,
                None, None, -1, None, spawned, None)
        try:
            self.terminal.spawn_async(*args)
        except TypeError:  # older bindings take child_setup and its data as one argument
            self.terminal.spawn_async(*args[:5], None, -1, None, spawned, None)
        self.term_alive = True

    def show_terminal(self, show):
        if show and not Vte:
            self.term_button.set_active(False)
            self._external_terminal()
            return
        if self.term_button.get_active() != show:
            self.term_button.set_active(show)
            return
        if show and not self.term_alive:
            self._spawn_shell()
        self.term_revealer.set_reveal_child(show)
        (self.terminal if show else self.input).grab_focus()

    def _external_terminal(self):
        terminal = "ghostty"
        try:
            from hyprsettings.schema import BY_ID
            from hyprsettings.store import Store
            terminal = Store().get(BY_ID["hyprdots.terminal"])[0] or terminal
        except Exception:
            pass
        try:
            subprocess.Popen([terminal], cwd=os.path.expanduser("~"), start_new_session=True)
        except OSError as e:
            self.toast(f"Could not open {terminal}: {e}")

    def _shell_idle(self):
        """True when the shell itself is at the front of the terminal: nothing is running in it."""
        try:
            return self.term_pid is not None and os.tcgetpgrp(self.terminal.get_pty().get_fd()) == self.term_pid
        except (OSError, AttributeError):
            return False

    def run_in_terminal(self, code, started=None):
        """Runs the code in the terminal as if typed, after anything half-typed is cleared. started(row) is called with
        the cursor's row, or None if it could not run. It refuses while a program is running there: the text would go
        to that program, not the shell."""
        started = started or (lambda _row: None)
        if not Vte:
            self.paste_in_terminal(code)
            started(None)
            return
        fresh = not self.term_alive
        self.show_terminal(True)
        tries = [0]

        def go():
            tries[0] += 1
            if self.term_pid is None and tries[0] < 40:  # the shell is still starting
                return GLib.SOURCE_CONTINUE
            if not self._shell_idle():
                self.toast("The terminal is busy. Finish what is running there first")
                started(None)
                return GLib.SOURCE_REMOVE
            row = self.terminal.get_cursor_position()[1]
            self.terminal.feed_child(b"\x05\x15" + code.strip("\n").encode() + b"\n")  # End, then erase the line
            self.terminal.grab_focus()
            started(row)
            return GLib.SOURCE_REMOVE
        GLib.timeout_add(1000 if fresh else 50, go)  # a new shell needs a moment to reach its prompt

    def when_finished(self, cancelled, finished):
        """Calls finished() once the command just started has ended and the shell is back at its prompt."""
        began, idle_since, seen_busy = time.monotonic(), [None], [False]

        def check():
            if cancelled():
                return GLib.SOURCE_REMOVE
            if not self.term_alive:
                finished()
                return GLib.SOURCE_REMOVE
            now = time.monotonic()
            if not self._shell_idle():
                seen_busy[0], idle_since[0] = True, None
                return GLib.SOURCE_CONTINUE
            idle_since[0] = idle_since[0] or now
            # Shell prompts run helpers of their own, and shell builtins never leave the shell at all
            if now - idle_since[0] >= (0.4 if seen_busy[0] else 1.2) and now - began >= 0.4:
                finished()
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        GLib.timeout_add(120, check)

    def paste_in_terminal(self, code):
        """Puts the code in the terminal without running it: you read it and press Enter."""
        if not Vte:
            self.copy(code)
            self._external_terminal()
            self.toast("Copied. Paste it into the terminal (Ctrl+Shift+V) — vte4 adds a built-in one")
            return
        self.show_terminal(True)
        GLib.timeout_add(150 if self.term_alive else 600, lambda: (self.terminal.paste_text(code.strip("\n")),
                                                                   self.terminal.grab_focus(), False)[2])

    def read_terminal(self, lines):
        """For the agent's worker thread: the terminal's newest lines as plain text, None if GTK did not answer in time."""
        result, done = [], threading.Event()

        def grab():
            try:
                result.append(self._terminal_text(lines))
            finally:
                done.set()
            return False
        GLib.idle_add(grab)
        return result[0] if done.wait(5) and result else None

    def _terminal_text(self, lines, since=None):
        # Counted back from the cursor: the scroll position is not known until the pane has been shown
        term = self.terminal
        _column, row = term.get_cursor_position()
        start = max(0, row - lines) if since is None else max(since, row - lines)
        text = term.get_text_range_format(Vte.Format.TEXT, start, 0, row + term.get_row_count(),
                                          term.get_column_count())[0] or ""
        rows = [line.rstrip() for line in text.split("\n")]
        while rows and not rows[-1]:
            rows.pop()
        return "\n".join(rows[-lines:])

    def copy(self, text):
        self.window.get_clipboard().set(text)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    def tint(self, widget, ansi_code):
        widget.add_css_class(f"tint-{ansi_code if ansi_code in ANSI else '36'}")

    # Actions and status
    def _actions(self):
        approvals = Gio.SimpleAction.new_stateful("approvals", None, GLib.Variant.new_boolean(not agent.AUTO_APPROVE[0]))
        approvals.connect("activate", lambda *_: self.slash("/ask" if agent.AUTO_APPROVE[0] else "/allow"))
        reasoning = Gio.SimpleAction.new_stateful("reasoning", None, GLib.Variant.new_boolean(agent.THINK["show"]))
        reasoning.connect("activate", lambda *_: self.slash("/think"))
        effort = Gio.SimpleAction.new_stateful("effort", GLib.VariantType.new("s"),
                                               GLib.Variant.new_string(agent.THINK["effort"]))
        effort.connect("activate", lambda _a, v: self.slash(f"/effort {v.get_string()}"))
        mode = Gio.SimpleAction.new_stateful("mode", GLib.VariantType.new("s"), GLib.Variant.new_string(agent_modes.name()))
        mode.connect("activate", lambda _a, v: self.slash(f"/mode {v.get_string()}"))
        paste = Gio.SimpleAction.new("paste", None)
        paste.connect("activate", lambda *_: self.send("/paste"))
        clear = Gio.SimpleAction.new("clear", None)
        clear.connect("activate", lambda *_: self.clear())
        terminal = Gio.SimpleAction.new("terminal", None)
        terminal.connect("activate", lambda *_: self.show_terminal(not self.term_revealer.get_reveal_child()))
        stop = Gio.SimpleAction.new("stop", None)
        stop.connect("activate", lambda *_: self.stop())
        for action in (approvals, reasoning, effort, mode, paste, clear, terminal, stop):
            self.add_action(action)
        self.actions = {a.get_name(): a for a in (approvals, reasoning, effort, mode)}
        self.set_accels_for_action("app.terminal", ["<Control>grave"])
        self.set_accels_for_action("app.stop", ["Escape"])
        self.set_accels_for_action("app.clear", ["<Control>l"])

    def say(self, text):
        """Starts a sentence for the player from the character sheet, for them to finish and send."""
        self._set_text(text)
        self.input.grab_focus()

    def open_builder(self):
        def done():
            self.character.refresh()
            self.send(dnd_mode.OPENING, quiet=True)
        dnd_ui.CharacterBuilder(done).present(self.window)

    def open_subclass(self):
        c = dnd_mode.view()["character"]
        if self.window.get_visible_dialog() or not c or not c.get("needs_subclass"):
            return

        def picked(name, from_book):
            if from_book:
                self.send(f"For my subclass I choose {name}, from my books. Please look it up and add what I gain at this level.")
                return
            result = dnd_mode.TOOLS["dnd_update"]({"subclass": name})
            if result.startswith("Rejected"):
                self.toast(result.split(": ", 1)[-1])
            else:
                self.toast(f"You follow the {name}.".replace("the Oath", "Oath"))
        dnd_ui.SubclassDialog(c, dnd_library.books(), picked).present(self.window)

    def on_table_event(self, kind, data):
        if kind == "sheet":
            if self.in_table:
                self.character.refresh()
                if not self.worker:
                    self._offer_subclass()
        elif self.turn and self.in_table:
            (self.turn.dice if kind == "roll" else self.turn.dnd_note)(data)

    def _offer_subclass(self):
        if not self.window.get_visible_dialog() and (dnd_mode.game()["character"] or {}).get("needs_subclass"):
            GLib.idle_add(lambda: (self.open_subclass(), False)[1])

    def _clear_chat(self):
        while (child := self.chat.get_last_child()) and child is not self.welcome:
            self.chat.remove(child)

    def _sit_at_the_table(self):
        """Changes the window to match the mode. The first request of a sitting has the Dungeon Master open the scene."""
        table = agent_modes.fiction()
        new_tale = table and self.table_generation != dnd_mode.GENERATION[0]
        if table == self.in_table and not new_tale:
            return
        self.in_table, self.table_generation = table, dnd_mode.GENERATION[0]
        (self.window.add_css_class if table else self.window.remove_css_class)("dnd")
        Logo.stone = (rgb("#9a8a72"), rgb("#5a4a38")) if table else None
        self.title_label.set_label("The Hearth · Dungeon Master" if table else "Hearthling")
        self.placeholder.set_label("What do you do?" if table else "Ask anything, or type / for commands")
        self.sheet_button.set_visible(table)
        self.pill_think.set_visible(not table)
        self.pill_approvals.set_visible(not table)
        self.web_button.set_visible(not table)
        self.term_button.set_visible(not table)
        if table:
            self.web_button.set_active(False)
            self.show_terminal(False)
        self.sheet_split.set_show_sidebar(table and self.sheet_button.get_active())
        self._clear_chat()
        self.welcome.set_vexpand(not table)
        self.welcome.set_reveal_child(not table)
        if table:
            self.character.last = None
            self.character.refresh()
            if dnd_mode.game()["character"]:
                GLib.idle_add(lambda: (self.send(dnd_mode.OPENING, quiet=True), False)[1])
            else:
                GLib.idle_add(lambda: (self.open_builder(), False)[1])

    def refresh_status(self):
        self._sit_at_the_table()
        mode = agent_modes.describe()
        self.pill_mode.set_label(f"◆ {mode}")
        if agent.AUTO_APPROVE[0]:
            self.pill_approvals.set_label("⚡ approvals off")
            self.pill_approvals.add_css_class("warn")
            self.pill_approvals.remove_css_class("good")
        else:
            self.pill_approvals.set_label("✓ approvals on")
            self.pill_approvals.add_css_class("good")
            self.pill_approvals.remove_css_class("warn")
        self.pill_think.set_label(f"◔ reasoning {agent.THINK['effort']}" if agent.THINK["show"] else "◔ reasoning hidden")
        self.subtitle.set_label(f"{agent.chat_model()} · {mode}")
        if hasattr(self, "actions"):
            self.actions["approvals"].set_state(GLib.Variant.new_boolean(not agent.AUTO_APPROVE[0]))
            self.actions["reasoning"].set_state(GLib.Variant.new_boolean(agent.THINK["show"]))
            self.actions["effort"].set_state(GLib.Variant.new_string(agent.THINK["effort"]))
            self.actions["mode"].set_state(GLib.Variant.new_string(agent_modes.name()))

    def _cycle_effort(self):
        levels = agent.THINK_EFFORTS
        self.slash(f"/effort {levels[(levels.index(agent.THINK['effort']) + 1) % len(levels)]}")

    def slash(self, line):
        """Settings changes from the menu and pills: run the /command quietly and say what changed in a toast."""
        found = agent.run_slash_command(line)
        self.refresh_status()
        if found:
            first = re.sub(r"\*\*|`", "", found[1].split("\n")[0])
            model = f" It answers with {agent.chat_model()}." if line.startswith("/mode") and agent.chat_model() != agent.MODEL else ""
            self.toast(first.split(". ")[0].rstrip(".") + "." + model)

    # Scrolling
    def _on_scroll(self, adj):
        self.stick = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 60

    def follow(self):
        if not self.stick:
            return
        adj = self.scroller.get_vadjustment()
        GLib.idle_add(lambda: (adj.set_value(adj.get_upper() - adj.get_page_size()), False)[1])

    # Input
    def _text(self):
        buf = self.input.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _set_text(self, text):
        buf = self.input.get_buffer()
        buf.set_text(text)
        buf.place_cursor(buf.get_end_iter())

    def _on_input_changed(self, _buf):
        text = self._text()
        self.placeholder.set_visible(not text)
        self._update_send()
        GLib.idle_add(self._input_scrollbar)
        while child := self.slash_box.get_first_child():
            self.slash_box.remove(child)
        matches = []
        if text.startswith("/") and "\n" not in text:
            name, space, arg = text[1:].partition(" ")
            if not space:
                matches = [(f"/{n}", desc, colour) for n, (_f, desc, colour) in agent.SLASH_COMMANDS.items()
                           if n.startswith(name.lower())]
            else:
                matches = [(f"/{name} {o}", "option", agent.SLASH_COMMANDS.get(name.lower(), (0, 0, "36"))[2])
                           for o in agent.SLASH_ARGS.get(name.lower(), []) if o.startswith(arg.lower())]
        for label, desc, colour in matches:
            button = Gtk.Button(tooltip_text=desc, css_classes=["slash", "flat"])
            inner = Gtk.Box(spacing=8)
            inner.append(Gtk.Label(label=label, css_classes=["name"]))
            if len(matches) <= 3 and desc != "option":
                inner.append(Gtk.Label(label=desc, css_classes=["desc"]))
            button.set_child(inner)
            self.tint(button, colour)
            button.connect("clicked", lambda _b, l=label: (self._set_text(l + " "), self.input.grab_focus()))
            self.slash_box.append(button)
        self.slash_revealer.set_reveal_child(bool(matches))
        self.slash_matches = [m[0] for m in matches]

    def _input_scrollbar(self):
        tall = self.input.measure(Gtk.Orientation.VERTICAL, self.input.get_width())[1] > INPUT_MAX_HEIGHT
        self.input_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC if tall else Gtk.PolicyType.EXTERNAL)
        return False

    def _on_key(self, _ctl, keyval, _code, state):
        shift = state & Gdk.ModifierType.SHIFT_MASK
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not shift:
            if self.pending_answer:
                return True
            self.send()
            return True
        if keyval == Gdk.KEY_Tab and getattr(self, "slash_matches", None):
            self._set_text(self.slash_matches[0] + " ")
            return True
        if keyval == Gdk.KEY_Up and self.history and (not self._text() or self._text() == self.recall):
            index = self.history.index(self.recall) - 1 if self.recall in self.history else len(self.history) - 1
            self.recall = self.history[max(0, index)]
            self._set_text(self.recall)
            return True
        return False

    def send(self, text=None, quiet=False):
        text = (text if text is not None else self._text()).strip()
        if self.worker or not (text or self.attachments):
            return
        if re.fullmatch(r"roll for initiative[.!]*", text, re.I) and not agent_modes.fiction():
            text = "/mode dnd"
        attachments = [] if text.startswith("/") else self.attachments  # a /command leaves them in the tray
        if attachments:
            self._clear_tray()
        self._set_text("")
        self.recall = None
        if text and not quiet and (not self.history or self.history[-1] != text):
            self.history.append(text)
        if text.lower() in ("exit", "quit"):
            self.quit()
            return
        if self.welcome.get_reveal_child():
            self.welcome.set_vexpand(False)
            self.welcome.set_reveal_child(False)
        self.big_logo.freeze()
        self.stick = True
        slash = None
        if text.startswith("/"):
            name = text[1:].partition(" ")[0].lower()
            slash = (name, agent.SLASH_COMMANDS.get(name, (0, 0, "31"))[2])
        self.turn = Turn(self, None if slash or quiet else text, slash, attachments)
        self.chat.append(self.turn)
        self.follow()
        self._busy(True)
        self.cancelled.clear()
        self.worker = threading.Thread(target=self._work, args=(text, self.turn, bool(slash), attachments), daemon=True)
        self.worker.start()

    def _work(self, text, turn, is_slash, attachments=()):
        agent.TOOL_COUNT[0] = 0
        started = time.time()
        failed, took = False, None
        try:
            if is_slash:
                _name, reply, colour = agent.run_slash_command(text)
                failed = colour == "31"
            elif attachments:
                reply = self._ask_with_attachments(text, attachments)
                took = time.time() - started
                failed = reply.startswith(agent.FAILURE_PREFIXES)
            else:
                reply = agent.process_prompt(text)
                took = time.time() - started
                failed = reply.startswith(agent.FAILURE_PREFIXES)
        except KeyboardInterrupt:
            agent.log_turn(text, "", "cancelled by the user")
            reply = "**Stopped.** Commands that had already run are not undone, and nothing from this request was saved."
            failed = True
        except Exception as e:  # noqa: BLE001  (the window must survive anything the agent throws)
            reply = f"Something went wrong: {e}"
            failed = True
        ui(self._done, turn, reply, took, agent.TOOL_COUNT[0], failed, is_slash)

    @staticmethod
    def _ask_with_attachments(text, attachments):
        """Pictures go to the vision model first (its answer is kept for follow-ups, like /paste); then the agent gets
        the question with a note per attachment. Pictures alone with no question get the description straight back."""
        vision = {}
        for a in attachments:
            if a.kind != "image":
                continue
            if not agent.VISION_ENABLED:
                vision[a] = "no vision model is set up (run ~/.config/hypr/assistant/setup.sh to add one)"
                continue
            vision[a] = agent.analyze_image(a.path, text or "Describe this image in detail.",
                                            "Looking at the picture", source=f"attached image {a.name}")
        if not text and attachments and all(a.kind == "image" for a in attachments):
            parts = []
            for a in attachments:
                seen = vision[a]
                body = seen[len("Vision Analysis: "):].strip() if seen.startswith("Vision Analysis: ") else seen
                parts.append(f"**{a.name}**\n\n{body}" if len(attachments) > 1 else body)
            reply = "\n\n".join(parts)
            agent.log_turn(f"[attached {', '.join(a.name for a in attachments)}]", reply)
            return reply
        return agent.process_prompt(attachment_prompt(text, attachments, vision))

    def _done(self, turn, reply, took, steps, failed, is_slash):
        turn.finish(reply, took, steps, failed)
        self.worker = None
        self.turn = None
        self._busy(False)
        if self.in_table:
            self._offer_subclass()
        self._update_send()
        self.refresh_status()
        if not is_slash and not self.window.is_active():
            subprocess.Popen(["notify-send", "-a", "Hearthling", "--", "Done.", reply[:600]])

    def _busy(self, busy):
        self.header_logo.set_busy(busy)
        self.send_button.set_sensitive(True)  # it is the stop button while busy
        self.send_button.set_icon_name("media-playback-stop-symbolic" if busy else "go-up-symbolic")
        self.send_button.set_tooltip_text("Stop (Esc)" if busy else "Send (Enter)")
        (self.send_button.add_css_class if busy else self.send_button.remove_css_class)("stop")

    def stop(self):
        """Stops the answer: interrupts the worker the way Ctrl+C does in the terminal."""
        worker = self.worker
        if not worker:
            return
        self.cancelled.set()
        if self.pending_answer:
            self.pending_answer(False)
        if self.waiting:
            self.waiting[1][0] = False
            self.waiting[0].set()
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(worker.ident), ctypes.py_object(KeyboardInterrupt))
        if self.turn:
            self.turn.status("Stopping")

    def attention(self, title, body):
        if not self.window.is_active():
            subprocess.Popen(["notify-send", "-a", "Hearthling", "-u", "critical", "--", title, body[:300]])

    def clear(self):
        if self.worker:
            return
        agent.HISTORY.clear()
        if agent.SESSION_FILE[0]:
            try:
                open(agent.SESSION_FILE[0], "w").close()
            except OSError:
                pass
        self._clear_chat()
        self.welcome.set_vexpand(True)
        self.welcome.set_reveal_child(True)
        self.web.clear()
        self.toast("New chat. Earlier messages are forgotten.")


APP = Assistant()


def main():
    GLib.set_application_name("Hearthling")  # shown by the file picker and other system dialogs
    install_hooks()
    return APP.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
