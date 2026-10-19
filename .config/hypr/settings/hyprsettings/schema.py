"""Every setting the app can change: where it lives, how it is edited and what it means.

Defaults here are only a fallback. The shared user_settings.toml wins over them, so the "default" a
user sees is the same one the assistant and monitor use."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PAGES = ["Assistant", "Assistant Monitor", "Calendar", "Cloud drives", "Displays", "Appearance", "Hyprland", "Keybinds", "File types", "Hyprdots"]

# One short explanation shown at the top of each page
PAGE_INTRO = {
    "Assistant": "The local AI helper you open with Super+C: which models it uses and how it behaves.",
    "Assistant Monitor": "This is NOT about your screens. It is the assistant's background health monitor: every few minutes it checks "
                         "your PC (failed services, full disks, heat, pending updates) and sends a desktop notification when something is "
                         "wrong. For screen layout see the Displays page.",
    "Calendar": "Calendars shown in the clock popup and readable by the assistant. Links stay private on this computer.",
    "Cloud drives": "Your online accounts (Google Drive, OneDrive, Dropbox, Nextcloud, ownCloud, WebDAV) shown as normal folders in "
                    "Thunar. Each one appears in the Thunar sidebar and under ~/Cloud, and reconnects by itself when you log in. "
                    "Passwords and tokens are kept by rclone, never in these settings files.",
    "Displays": "Your screens: resolution, refresh rate, scale, rotation and where each one sits. Changes apply straight away and you "
                "get a few seconds to confirm, so a bad choice undoes itself. Remembered in monitors.lua.",
    "Appearance": "The look of GTK apps (Thunar, settings dialogs and so on): theme, icons, mouse cursor and font. "
                  "Applies straight away; apps that are already open may need a restart.",
    "Hyprland": "How the desktop looks and how your keyboard and mouse behave. After saving you are offered a reload.",
    "Keybinds": "Select an action and press Enter to give it a new key combo. Open the first item for how to add your own. "
                "Super is the Windows key. Applied when Hyprland reloads.",
    "File types": "Which app opens each kind of file: links, pictures, video, PDFs and so on. Changes apply straight away and are "
                  "kept in ~/.config/mimeapps.list, which every desktop app reads.",
    "Hyprdots": "Default apps for the keybinds, and what starts when you log in.",
}


@dataclass(frozen=True)
class Setting:
    page: str
    section: str                       # TOML section in user_settings.local.toml
    key: str
    label: str
    kind: str                          # choice | bool | int | float | text | list | model | vision_model
    default: Any
    help: str
    choices: tuple = ()                # ((value, label), ...)
    allow_custom: bool = False
    lo: float | None = None
    hi: float | None = None
    step: float = 1
    unit: str = ""
    effect: str = "next time the assistant starts"
    lua: tuple = ()                    # path inside hl.config({...}) for Hyprland settings
    group: str = ""

    @property
    def id(self) -> str:
        return f"{self.section}.{self.key}"


def _c(*pairs):
    return tuple(pairs)


ACCENTS = _c(("36", "Cyan"), ("35", "Magenta"), ("34", "Blue"), ("32", "Green"), ("33", "Yellow"), ("31", "Red"), ("37", "White"))
KEEP_ALIVE = _c(("30s", "30 seconds (frees the GPU quickly)"), ("5m", "5 minutes"), ("30m", "30 minutes"),
                ("2h", "2 hours"), ("-1", "Never unload"))
CONTEXT = _c((8192, "8192 (small, least memory)"), (16384, "16384 (default)"), (24576, "24576"), (32768, "32768 (needs a big GPU)"))
KB_LAYOUTS = _c(("gb", "gb - United Kingdom"), ("us", "us - United States"), ("de", "de - German"), ("fr", "fr - French"),
                ("es", "es - Spanish"), ("it", "it - Italian"), ("pt", "pt - Portuguese"), ("se", "se - Swedish"),
                ("no", "no - Norwegian"), ("dk", "dk - Danish"), ("fi", "fi - Finnish"), ("pl", "pl - Polish"),
                ("ie", "ie - Irish"), ("br", "br - Brazilian"))
FOLLOW = _c((0, "0 - Click to focus"), (1, "1 - Focus follows the mouse"), (2, "2 - Follows, but cursor is not moved"),
            (3, "3 - Follows and the cursor is independent"))

ASSISTANT, MONITOR, CALENDAR, CLOUD, DISPLAYS, APPEARANCE, HYPRLAND, KEYBINDS, FILETYPES, HYPRDOTS = PAGES

SETTINGS: list[Setting] = [
    # ---- Assistant -------------------------------------------------------------------------------------
    Setting(ASSISTANT, "assistant", "model", "Chat model", "model", "gpt-oss:20b",
            "The model that answers you and calls tools. It must support tool calling. gpt-oss is what the assistant was tuned for; "
            "bigger models are smarter but need more GPU memory.", group="Models"),
    Setting(ASSISTANT, "assistant", "vision_model", "Vision model", "vision_model", "qwen2.5vl:7b",
            "Reads screenshots and pasted images. 'Same as chat model' works when your chat model can see images (qwen3.5 can) and saves "
            "loading a second model. Choose None to switch image features off (no screenshot tool, no /paste).", group="Models"),
    Setting(ASSISTANT, "assistant", "think_effort", "Thinking effort", "choice", "medium",
            "How hard the model thinks before answering. Higher is slower but better on hard problems.",
            choices=_c(("low", "Low - quick answers"), ("medium", "Medium"), ("high", "High - slowest, most careful")), group="Behaviour"),
    Setting(ASSISTANT, "assistant", "show_thinking", "Show live reasoning", "bool", True,
            "Watch the model think while it works. You can toggle this inside the chat with /think.", group="Behaviour"),
    Setting(ASSISTANT, "assistant", "fact_check", "Fact-check answers", "bool", True,
            "Before replying, check the answer against what was actually looked up, and send the assistant back to verify "
            "anything it took from memory. Slower, but far fewer made-up specs.", group="Behaviour"),
    Setting(ASSISTANT, "assistant", "searxng_url", "SearXNG address", "text", "",
            "Your own SearXNG search service, for example http://127.0.0.1:8888. Gives the assistant far better web searches "
            "than the public engines, which often block it. Leave empty if you do not run one.", group="Behaviour"),
    Setting(ASSISTANT, "assistant", "max_tool_steps", "Tool steps per question", "int", 30,
            "How many tool calls the assistant may make for one question before it has to answer.", lo=5, hi=60, group="Behaviour"),
    Setting(ASSISTANT, "assistant", "keep_alive", "Keep model loaded", "choice", "30s",
            "How long a model stays in GPU memory after your last question. Longer is faster to reply but holds memory.",
            choices=KEEP_ALIVE, allow_custom=True, group="Performance"),
    Setting(ASSISTANT, "assistant", "num_ctx", "Context window", "choice", 16384,
            "How much conversation the model can see, in tokens. Bigger needs more GPU memory (about 3 GB extra at 16384 on a 14B model).",
            choices=CONTEXT, allow_custom=True, group="Performance"),
    Setting(ASSISTANT, "assistant", "accent", "Accent colour", "choice", "36",
            "Colour of the prompt and banner in the chat window.", choices=ACCENTS, group="Look"),
    Setting(ASSISTANT, "assistant", "animated_logo", "Animated logo", "bool", True,
            "Spin the logo in the startup banner.", group="Look"),
    Setting(ASSISTANT, "assistant", "command_timeout", "Read-only command timeout", "int", 20,
            "Seconds a command the assistant runs on its own may take.", lo=5, hi=120, unit="s", group="Limits"),
    Setting(ASSISTANT, "assistant", "confirmed_command_timeout", "Approved command timeout", "int", 180,
            "Seconds a command you approved may take (installs, sudo).", lo=30, hi=1800, unit="s", group="Limits"),
    Setting(ASSISTANT, "assistant", "web_timeout", "Web request timeout", "int", 15,
            "Seconds before a web request gives up.", lo=5, hi=60, unit="s", group="Limits"),
    # ---- Monitor ---------------------------------------------------------------------------------------
    Setting(MONITOR, "monitor", "defer_when_busy", "Pause while gaming", "bool", True,
            "Skip the health check while a game is running or the GPU is busy, so it never causes a stutter.",
            effect="on the next health check", group="Behaviour"),
    Setting(MONITOR, "monitor", "busy_gpu_pct", "Busy GPU level", "int", 60,
            "GPU load that counts as busy (sustained for a few seconds).", lo=20, hi=100, unit="%",
            effect="on the next health check", group="Behaviour"),
    Setting(MONITOR, "monitor", "renotify_hours", "Repeat a warning after", "int", 6,
            "Hours before you are reminded about a problem that is still open.", lo=1, hi=72, unit="h",
            effect="on the next health check", group="Behaviour"),
    Setting(MONITOR, "monitor", "journal_window", "Look back for errors", "choice", "30 minutes ago",
            "How far back the monitor reads the system journal.",
            choices=_c(("10 minutes ago", "10 minutes"), ("30 minutes ago", "30 minutes"), ("1 hour ago", "1 hour"), ("3 hours ago", "3 hours")),
            allow_custom=True, effect="on the next health check", group="Behaviour"),
    Setting(MONITOR, "monitor", "disk_warn", "Disk warning", "int", 85, "Warn when a disk is this full.", lo=50, hi=99, unit="%",
            effect="on the next health check", group="Thresholds"),
    Setting(MONITOR, "monitor", "disk_crit", "Disk critical", "int", 95, "Critical alert when a disk is this full.", lo=60, hi=100, unit="%",
            effect="on the next health check", group="Thresholds"),
    Setting(MONITOR, "monitor", "mem_warn_pct", "Low memory warning", "int", 10, "Warn when available RAM falls below this.", lo=2, hi=50, unit="%",
            effect="on the next health check", group="Thresholds"),
    Setting(MONITOR, "monitor", "swap_warn_pct", "Swap warning", "int", 50, "Warn when swap use is above this.", lo=10, hi=100, unit="%",
            effect="on the next health check", group="Thresholds"),
    Setting(MONITOR, "monitor", "temp_warn", "Temperature warning", "int", 85, "Warning temperature.", lo=50, hi=110, unit="°C",
            effect="on the next health check", group="Thresholds"),
    Setting(MONITOR, "monitor", "temp_crit", "Temperature critical", "int", 95, "Critical temperature.", lo=60, hi=120, unit="°C",
            effect="on the next health check", group="Thresholds"),
    Setting(MONITOR, "monitor", "updates_warn", "Pending updates warning", "int", 50, "Flag when this many updates are waiting.", lo=5, hi=500,
            effect="on the next health check", group="Thresholds"),
    Setting(MONITOR, "monitor", "journal_ignore", "Ignored journal sources", "list", ["bluetoothd", "kwin_wayland", "sddm-helper"],
            "Noisy programs whose log errors are skipped. Separate several with commas.",
            effect="on the next health check", group="Ignore lists"),
    Setting(MONITOR, "monitor", "units_ignore", "Ignored failed services", "list", ["systemd-pcr*", "systemd-tpm2-setup*"],
            "Failed services to ignore, with * wildcards. Separate several with commas.",
            effect="on the next health check", group="Ignore lists"),
    # ---- Hyprland (written to user_overrides.lua, applied with a reload) ------------------------------------
    Setting(HYPRLAND, "hyprland", "gaps_in", "Gap between windows", "int", 5, "Space between tiled windows.", lo=0, hi=50, unit="px",
            effect="when Hyprland reloads", lua=("general", "gaps_in"), group="Windows"),
    Setting(HYPRLAND, "hyprland", "gaps_out", "Gap at screen edges", "int", 10, "Space between windows and the screen edge.", lo=0, hi=100, unit="px",
            effect="when Hyprland reloads", lua=("general", "gaps_out"), group="Windows"),
    Setting(HYPRLAND, "hyprland", "border_size", "Border thickness", "int", 2, "Width of window borders. 0 removes them.", lo=0, hi=10, unit="px",
            effect="when Hyprland reloads", lua=("general", "border_size"), group="Windows"),
    Setting(HYPRLAND, "hyprland", "rounding", "Corner rounding", "int", 18, "How round window corners are. 0 is square.", lo=0, hi=40, unit="px",
            effect="when Hyprland reloads", lua=("decoration", "rounding"), group="Windows"),
    Setting(HYPRLAND, "hyprland", "layout", "Tiling layout", "choice", "dwindle",
            "dwindle splits each window in two; master keeps one big window with a stack beside it.",
            choices=_c(("dwindle", "dwindle - binary splits"), ("master", "master - one main window")),
            effect="when Hyprland reloads", lua=("general", "layout"), group="Windows"),
    Setting(HYPRLAND, "hyprland", "active_opacity", "Focused window opacity", "float", 1.0, "1.0 is fully solid.", lo=0.3, hi=1.0, step=0.05,
            effect="when Hyprland reloads", lua=("decoration", "active_opacity"), group="Effects"),
    Setting(HYPRLAND, "hyprland", "inactive_opacity", "Unfocused window opacity", "float", 1.0, "Lower makes windows you are not using fade.",
            lo=0.3, hi=1.0, step=0.05, effect="when Hyprland reloads", lua=("decoration", "inactive_opacity"), group="Effects"),
    Setting(HYPRLAND, "hyprland", "blur", "Background blur", "bool", True, "Blur what is behind transparent windows. Costs some GPU.",
            effect="when Hyprland reloads", lua=("decoration", "blur", "enabled"), group="Effects"),
    Setting(HYPRLAND, "hyprland", "shadow", "Window shadows", "bool", False, "Draw a shadow behind windows.",
            effect="when Hyprland reloads", lua=("decoration", "shadow", "enabled"), group="Effects"),
    Setting(HYPRLAND, "hyprland", "animations", "Animations", "bool", True, "Window and workspace animations. Turn off for a snappier feel.",
            effect="when Hyprland reloads", lua=("animations", "enabled"), group="Effects"),
    Setting(HYPRLAND, "hyprland", "kb_layout", "Keyboard layout", "choice", "gb", "Your keyboard layout code.", choices=KB_LAYOUTS, allow_custom=True,
            effect="when Hyprland reloads", lua=("input", "kb_layout"), group="Input"),
    Setting(HYPRLAND, "hyprland", "kb_variant", "Keyboard variant", "text", "", "Optional layout variant such as dvorak or intl. Leave empty for the standard one.",
            effect="when Hyprland reloads", lua=("input", "kb_variant"), group="Input"),
    Setting(HYPRLAND, "hyprland", "follow_mouse", "Focus follows mouse", "choice", 1, "Whether moving the mouse over a window focuses it.", choices=FOLLOW,
            effect="when Hyprland reloads", lua=("input", "follow_mouse"), group="Input"),
    Setting(HYPRLAND, "hyprland", "sensitivity", "Mouse sensitivity", "float", 0.0, "-1.0 is slowest, 1.0 fastest, 0 is unchanged.", lo=-1.0, hi=1.0, step=0.1,
            effect="when Hyprland reloads", lua=("input", "sensitivity"), group="Input"),
    Setting(HYPRLAND, "hyprland", "natural_scroll", "Natural scrolling (touchpad)", "bool", False, "Content follows your fingers, like a phone.",
            effect="when Hyprland reloads", lua=("input", "touchpad", "natural_scroll"), group="Input"),
    # ---- Hyprdots (default apps are read by keybinds.lua through user_overrides.lua) ---------------------------
    Setting(HYPRDOTS, "hyprdots", "terminal", "Terminal", "text", "ghostty", "Opened by Super+T.", allow_custom=True,
            effect="when Hyprland reloads", group="Default apps"),
    Setting(HYPRDOTS, "hyprdots", "file_manager", "File manager", "text", "thunar", "Opened by Super+E and Super+Shift+E (cloud drives).", allow_custom=True,
            effect="when Hyprland reloads", group="Default apps"),
    Setting(HYPRDOTS, "hyprdots", "browser", "Web browser", "text", "zen-browser", "Opened by Super+B.", allow_custom=True,
            effect="when Hyprland reloads", group="Default apps"),
    Setting(HYPRDOTS, "hyprdots", "store", "App store", "text", "flatpak run io.github.kolunmi.Bazaar", "Opened by Super+A.", allow_custom=True,
            effect="when Hyprland reloads", group="Default apps"),
]

# Installed programs suggested for each default app (only those that exist are offered)
APP_CANDIDATES = {
    "terminal": ["ghostty", "kitty", "alacritty", "foot", "wezterm", "konsole", "gnome-terminal", "xterm"],
    "file_manager": ["thunar", "nautilus", "dolphin", "pcmanfm", "nemo", "yazi"],
    "browser": ["zen-browser", "firefox", "chromium", "google-chrome-stable", "brave", "librewolf", "vivaldi"],
    "store": ["flatpak run io.github.kolunmi.Bazaar", "gnome-software", "pamac-manager", "plasma-discover", "cosmic-store"],
}

BY_ID = {s.id: s for s in SETTINGS}


def for_page(page: str) -> list[Setting]:
    return [s for s in SETTINGS if s.page == page]
