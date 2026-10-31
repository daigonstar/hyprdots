"""Every setting the app can change: where it lives, how it is edited and what it means.

Defaults here are only a fallback. The shared user_settings.toml wins over them, so the "default" a
user sees is the same one the assistant and monitor use."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PAGES = ["Assistant", "Assistant Monitor", "Calendar", "Cloud drives", "Displays", "Workspaces", "Power & lock", "Appearance",
         "Hyprland", "Keybinds", "File types", "Hyprdots"]

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
    "Workspaces": "Super+1 to Super+0 switch between ten workspaces. Choose which screen each one opens on, which one a screen "
                  "starts on, and give it a name or an app to open. Saved to workspaces.lua when you press Save: Hyprland reloads "
                  "and open workspaces move to their screen.",
    "Power & lock": "What happens when you step away: when the screen locks, when the screens switch off and when the PC goes "
                    "to sleep. Applied as soon as you save. Set a time to 0 to switch that step off.",
    "Appearance": "The look of GTK apps (Thunar, settings dialogs and so on): theme, icons, mouse cursor and font. "
                  "Applies straight away; apps that are already open may need a restart.",
    "Hyprland": "How the desktop looks and how your keyboard, mouse and touchpad behave. After saving you are offered a reload. "
                "Hover over an option for more detail.",
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
    tip: str = ""                      # longer explanation shown when hovering the row (GTK window)

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
KB_OPTIONS = _c(("", "None"), ("caps:escape", "Caps Lock is another Escape"), ("caps:ctrl_modifier", "Caps Lock is another Ctrl"),
                ("ctrl:swapcaps", "Swap Caps Lock and left Ctrl"), ("compose:ralt", "Right Alt is the Compose key"),
                ("caps:none", "Caps Lock does nothing"))
ACCEL = _c(("", "Device default"), ("adaptive", "Adaptive (speeds up with faster moves)"), ("flat", "Flat (same speed always, good for games)"))
POWER_EFFECT = "as soon as you save"
LOCK_EFFECT = "the next time the screen locks"
LOCK_BACKGROUNDS = _c(("wallpaper", "Your wallpaper"), ("wallpaper_blur", "Your wallpaper, blurred"),
                      ("screenshot_blur", "What was on screen, blurred"))
CLOCK_FORMATS = _c(("24h", "24-hour (21:30)"), ("12h", "12-hour (9:30 PM)"))
CLOCK_WEIGHTS = _c((100, "Thin"), (200, "Extra light"), (300, "Light"), (400, "Regular"), (600, "Bold"))
CLOCK_POSITIONS = _c(("centre", "Centre"), ("top", "Higher up"))
PASSWORD_STYLES = _c(("underline", "A line at the bottom"), ("box", "A box under the clock"))
LOCK_SCREENS = _c(("all", "Keep every screen on"), ("focused", "Only the screen you were using"))
CACHE_MODES = _c(("full", "Keep a local copy"), ("writes", "Stream from the server"))
CLOUD_EFFECT = "when the cloud drives restart"
SUPER_LOGOS = _c(("arch", "Arch logo"), ("tux", "Tux the penguin"), ("text", "The word SUPER"))
FOLLOW = _c((0, "0 - Click to focus"), (1, "1 - Focus follows the mouse"), (2, "2 - Follows, but cursor is not moved"),
            (3, "3 - Follows and the cursor is independent"))

ASSISTANT, MONITOR, CALENDAR, CLOUD, DISPLAYS, WORKSPACES, POWER, APPEARANCE, HYPRLAND, KEYBINDS, FILETYPES, HYPRDOTS = PAGES

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
    Setting(HYPRLAND, "hyprland", "resize_on_border", "Resize by dragging window edges", "bool", False, 'Grab the edge or border of a tiled or floating window with the mouse to resize it.',
            effect="when Hyprland reloads", lua=('general', 'resize_on_border'), group="Windows"),
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
    Setting(HYPRLAND, "hyprland", "dim_inactive", "Dim unfocused windows", "bool", False, 'Darkens every window except the one you are using.',
            effect="when Hyprland reloads", lua=('decoration', 'dim_inactive'), group="Effects"),
    Setting(HYPRLAND, "hyprland", "dim_strength", "Dim amount", "float", 0.5, 'How dark unfocused windows get when dimming is on.', lo=0.05, hi=1.0, step=0.05,
            effect="when Hyprland reloads", lua=('decoration', 'dim_strength'), group="Effects"),
    Setting(HYPRLAND, "hyprland", "blur_size", "Blur strength", "int", 3, 'How far the blur spreads behind transparent windows and the bar.', lo=1, hi=20,
            effect="when Hyprland reloads", lua=('decoration', 'blur', 'size'), group="Effects"),
    Setting(HYPRLAND, "hyprland", "blur_passes", "Blur smoothness", "int", 1, 'More passes look smoother but cost more GPU.', lo=1, hi=4,
            effect="when Hyprland reloads", lua=('decoration', 'blur', 'passes'), group="Effects"),
    Setting(HYPRLAND, "hyprland", "kb_layout", "Keyboard layout", "choice", "gb", "Your keyboard layout code.", choices=KB_LAYOUTS, allow_custom=True,
            effect="when Hyprland reloads", lua=("input", "kb_layout"), group="Keyboard"),
    Setting(HYPRLAND, "hyprland", "kb_variant", "Keyboard variant", "text", "", "Optional layout variant such as dvorak or intl. Leave empty for the standard one.",
            effect="when Hyprland reloads", lua=("input", "kb_variant"), group="Keyboard"),
    Setting(HYPRLAND, "hyprland", "kb_options", "Extra keyboard options", "choice", '', 'Small changes to what some keys do, such as using Caps Lock as Escape.', choices=KB_OPTIONS, allow_custom=True,
            effect="when Hyprland reloads", lua=('input', 'kb_options'), group="Keyboard",
            tip='Something else... takes any XKB option, several separated by commas, for example caps:escape,compose:ralt.'),
    Setting(HYPRLAND, "hyprland", "repeat_delay", "Key repeat delay", "int", 600, 'How long to hold a key before it starts repeating.', lo=150, hi=1500, step=25, unit="ms",
            effect="when Hyprland reloads", lua=('input', 'repeat_delay'), group="Keyboard"),
    Setting(HYPRLAND, "hyprland", "repeat_rate", "Key repeat speed", "int", 25, 'How many times a second a held key repeats.', lo=5, hi=80, unit="per second",
            effect="when Hyprland reloads", lua=('input', 'repeat_rate'), group="Keyboard"),
    Setting(HYPRLAND, "hyprland", "numlock", "Num Lock on at login", "bool", False, 'Turns the number pad on when you log in.',
            effect="when Hyprland reloads", lua=('input', 'numlock_by_default'), group="Keyboard"),
    Setting(HYPRLAND, "hyprland", "follow_mouse", "Focus follows mouse", "choice", 1, "Whether moving the mouse over a window focuses it.", choices=FOLLOW,
            effect="when Hyprland reloads", lua=("input", "follow_mouse"), group="Mouse"),
    Setting(HYPRLAND, "hyprland", "sensitivity", "Mouse sensitivity", "float", 0.0, "-1.0 is slowest, 1.0 fastest, 0 is unchanged.", lo=-1.0, hi=1.0, step=0.1,
            effect="when Hyprland reloads", lua=("input", "sensitivity"), group="Mouse"),
    Setting(HYPRLAND, "hyprland", "accel_profile", "Pointer acceleration", "choice", '', 'Whether the pointer goes further when you move the mouse faster.', choices=ACCEL,
            effect="when Hyprland reloads", lua=('input', 'accel_profile'), group="Mouse",
            tip='Adaptive suits everyday use. Flat makes the pointer move the same distance for the same hand movement whatever the speed, which many people prefer for games and drawing.'),
    Setting(HYPRLAND, "hyprland", "left_handed", "Left-handed buttons", "bool", False, 'Swaps the left and right mouse buttons.',
            effect="when Hyprland reloads", lua=('input', 'left_handed'), group="Mouse"),
    Setting(HYPRLAND, "hyprland", "scroll_factor", "Mouse scroll speed", "float", 1.0, 'How far one notch of the wheel scrolls. 1.0 is normal.', lo=0.2, hi=3.0, step=0.1,
            effect="when Hyprland reloads", lua=('input', 'scroll_factor'), group="Mouse"),
    Setting(HYPRLAND, "hyprland", "natural_scroll", "Natural scrolling", "bool", False, "Content follows your fingers, like a phone.",
            effect="when Hyprland reloads", lua=("input", "touchpad", "natural_scroll"), group="Touchpad"),
    Setting(HYPRLAND, "hyprland", "tap_to_click", "Tap to click", "bool", True, 'A light tap on the touchpad counts as a click.',
            effect="when Hyprland reloads", lua=('input', 'touchpad', 'tap_to_click'), group="Touchpad"),
    Setting(HYPRLAND, "hyprland", "disable_while_typing", "Ignore the touchpad while typing", "bool", True, 'Stops a palm brushing the touchpad from moving the pointer while you type.',
            effect="when Hyprland reloads", lua=('input', 'touchpad', 'disable_while_typing'), group="Touchpad"),
    Setting(HYPRLAND, "hyprland", "clickfinger", "Two-finger click is a right click", "bool", False, 'Click with two fingers anywhere on the pad for a right click, instead of clicking its bottom-right corner.',
            effect="when Hyprland reloads", lua=('input', 'touchpad', 'clickfinger_behavior'), group="Touchpad"),
    Setting(HYPRLAND, "hyprland", "touchpad_scroll_factor", "Touchpad scroll speed", "float", 1.0, 'How far a two-finger swipe scrolls. 1.0 is normal.', lo=0.2, hi=3.0, step=0.1,
            effect="when Hyprland reloads", lua=('input', 'touchpad', 'scroll_factor'), group="Touchpad"),
    Setting(HYPRLAND, "hyprland", "hide_on_key_press", "Hide the pointer while typing", "bool", False, 'It comes back as soon as you move the mouse.',
            effect="when Hyprland reloads", lua=('cursor', 'hide_on_key_press'), group="Cursor"),
    Setting(HYPRLAND, "hyprland", "cursor_timeout", "Hide the pointer after", "int", 0, 'Hides a still pointer after this many seconds. 0 never hides it.', lo=0, hi=120, unit="s",
            effect="when Hyprland reloads", lua=('cursor', 'inactive_timeout'), group="Cursor"),
    Setting(HYPRLAND, "hyprland", "no_warps", "Leave the pointer where it is", "bool", False, 'Normally the pointer jumps to a window when you focus it with the keyboard. On keeps it where you left it.',
            effect="when Hyprland reloads", lua=('cursor', 'no_warps'), group="Cursor"),
    Setting(HYPRLAND, "hyprland", "focus_on_activate", "Switch to windows that ask for attention", "bool", False, 'When an app asks to be shown (for example a link opening in your browser), go straight to it.',
            effect="when Hyprland reloads", lua=('misc', 'focus_on_activate'), group="Behaviour",
            tip='Off: the app is only marked as wanting attention, and you switch to it yourself. On can pull you away from what you are doing, for example while gaming.'),
    Setting(HYPRLAND, "hyprland", "workspace_back_and_forth", "Press a workspace's key again to go back", "bool", False, 'Pressing Super and the number of the workspace you are already on takes you to the one you were on before.',
            effect="when Hyprland reloads", lua=('binds', 'workspace_back_and_forth'), group="Behaviour"),
    Setting(HYPRLAND, "hyprland", "middle_click_paste", "Middle-click paste", "bool", True, 'Paste the last text you selected with the middle mouse button.',
            effect="when Hyprland reloads", lua=('misc', 'middle_click_paste'), group="Behaviour"),
    Setting(HYPRLAND, "hyprland", "force_zero_scaling", "Sharp old apps on scaled screens", "bool", False, 'Stops older (XWayland) apps looking blurry on a screen with a scale above 1. They may draw small instead.',
            effect="when Hyprland reloads", lua=('xwayland', 'force_zero_scaling'), group="Behaviour",
            tip='Only matters if a screen on the Displays page has a scale other than 1. Steam and some games are XWayland apps.'),
    Setting(HYPRLAND, "hyprland", "mouse_wakes", "Wake the screens with the mouse", "bool", False, 'Moving the mouse turns the screens back on after they switch off.',
            effect="when Hyprland reloads", lua=('misc', 'mouse_move_enables_dpms'), group="Behaviour"),
    Setting(HYPRLAND, "hyprland", "key_wakes", "Wake the screens with the keyboard", "bool", False, 'Pressing a key turns the screens back on after they switch off.',
            effect="when Hyprland reloads", lua=('misc', 'key_press_enables_dpms'), group="Behaviour"),
    # ---- Power & lock (written to hypridle.local.conf, see idle.py) -------------------------------------------
    Setting(POWER, "power", "lock_after", "Lock the screen after", "int", 0,
            "Minutes without using the PC before it locks. 0 never locks by itself.", lo=0, hi=240, unit="min",
            effect=POWER_EFFECT, group="When you step away",
            tip="Locking shows the lock screen; your apps keep running. Super+L or the power menu locks straight away."),
    Setting(POWER, "power", "screen_off_after", "Switch the screens off after", "int", 30,
            "Minutes without using the PC before the screens turn off. 0 keeps them on.", lo=0, hi=240, unit="min",
            effect=POWER_EFFECT, group="When you step away",
            tip="Moving the mouse or pressing a key turns them back on (see Wake the screens on the Hyprland page)."),
    Setting(POWER, "power", "suspend_after", "Go to sleep after", "int", 0,
            "Minutes without using the PC before it goes to sleep. 0 never sleeps by itself.", lo=0, hi=720, unit="min",
            effect=POWER_EFFECT, group="When you step away",
            tip="Sleep saves power but stops everything, including downloads, game servers and the cloud drives. "
                "Apps that are playing video or audio can keep the PC awake."),
    Setting(POWER, "power", "lock_screens", "Screens while locked", "choice", "all",
            "Which screens stay on behind the lock screen. The others switch off until you unlock.",
            choices=LOCK_SCREENS, allow_custom=True, effect=POWER_EFFECT, group="When you step away",
            tip="Only the screen you were using: whichever screen had your mouse or keyboard focus when it locked. "
                "Picking a screen by name always keeps that one, and the clock and password line show there."),
    Setting(POWER, "power", "lock_before_sleep", "Lock before going to sleep", "bool", True,
            "So the PC wakes up at the lock screen.", effect=POWER_EFFECT, group="When you step away"),
    # ---- Lock screen look (written to hyprlock.local.conf, see lockscreen.py) --------------------------------
    Setting(POWER, "lockscreen", "background", "Background", "choice", 'wallpaper',
            'What the lock screen shows behind the clock.', choices=LOCK_BACKGROUNDS,
            effect=LOCK_EFFECT, group="Lock screen",
            tip='Your wallpaper follows whatever you pick with the wallpaper picker (Super+W). What was on screen shows your open windows blurred, so nothing on them can be read.'),
    Setting(POWER, "lockscreen", "darken", "Darken the background", "int", 35,
            'Makes the clock easier to read on a bright wallpaper. 0 leaves it as it is.', lo=0, hi=90, step=5, unit="%",
            effect=LOCK_EFFECT, group="Lock screen"),
    Setting(POWER, "lockscreen", "clock_format", "Clock", "choice", '24h',
            'How the time is shown.', choices=CLOCK_FORMATS,
            effect=LOCK_EFFECT, group="Lock screen"),
    Setting(POWER, "lockscreen", "clock_weight", "Clock thickness", "choice", 200,
            'Thin and light look sleek; bold is easiest to read from across the room.', choices=CLOCK_WEIGHTS,
            effect=LOCK_EFFECT, group="Lock screen"),
    Setting(POWER, "lockscreen", "clock_size", "Clock size", "int", 140,
            'Size of the time.', lo=60, hi=240, step=10, unit="pt",
            effect=LOCK_EFFECT, group="Lock screen"),
    Setting(POWER, "lockscreen", "clock_position", "Clock position", "choice", 'centre',
            'Where the clock and date sit.', choices=CLOCK_POSITIONS,
            effect=LOCK_EFFECT, group="Lock screen"),
    Setting(POWER, "lockscreen", "show_date", "Show the date", "bool", True,
            'The day and date under the clock.',
            effect=LOCK_EFFECT, group="Lock screen"),
    Setting(POWER, "lockscreen", "show_user", "Show your username", "bool", False,
            'Your user name near the password.',
            effect=LOCK_EFFECT, group="Lock screen"),
    Setting(POWER, "lockscreen", "password", "Password", "choice", 'underline',
            'Where you type your password.', choices=PASSWORD_STYLES,
            effect=LOCK_EFFECT, group="Lock screen",
            tip='A line at the bottom only shows dots as you type, on a thin line. A box under the clock shows a rounded box with a Password hint that turns green or red when you press Enter.'),
    Setting(POWER, "lockscreen", "grace", "Unlock without a password for", "int", 0,
            'Seconds after locking during which moving the mouse or pressing a key unlocks again. 0 always asks.', lo=0, hi=30, unit="s",
            effect=LOCK_EFFECT, group="Lock screen",
            tip='Handy if you lock by accident or the idle lock catches you reading. Leave it at 0 if others use the room.'),
    Setting(POWER, "lockscreen", "fade", "Fade in and out", "bool", True,
            'A short fade when the lock screen appears and goes.',
            effect=LOCK_EFFECT, group="Lock screen"),
    # ---- Cloud drives (rclone mount flags, see cloud.mount_flags) ----------------------------------------------
    Setting(CLOUD, "cloud", "cache_mode", "File cache", "choice", "full",
            "Keep a local copy of what you open (faster), or stream every file from the server (nothing kept on this PC).",
            choices=CACHE_MODES, effect=CLOUD_EFFECT, group="How files are opened",
            tip="Keep a local copy: only the parts of a file you actually read are downloaded, then kept on disk. Opening it "
                "again, scrubbing back in a video or jumping around a zip is instant, and recently opened files still open "
                "offline. Uses up to the cache size below on this PC.\n\n"
                "Stream from the server: nothing you read is kept. Every open downloads again, seeking waits on the server, and "
                "nothing opens offline. Files you save are still staged briefly before upload, so saving stays safe.\n\n"
                "Either way, browsing folders and opening Thunar are equally fast, and thumbnails are only made once."),
    Setting(CLOUD, "cloud", "cache_size_gb", "Cache size per drive", "int", 10,
            "Most disk space each drive's local copies may use. Only used when keeping a local copy.",
            lo=1, hi=500, unit="GB", effect=CLOUD_EFFECT, group="How files are opened",
            tip="When the cache is full, the files you opened longest ago are removed first. Bigger keeps more of what you use "
                "instant; smaller saves disk space. Files still waiting to upload are never removed."),
    Setting(CLOUD, "cloud", "cache_days", "Keep cached files for", "int", 30,
            "Local copies not opened for this long are removed. Only used when keeping a local copy.",
            lo=1, hi=365, unit="days", effect=CLOUD_EFFECT, group="How files are opened",
            tip="Short (a day or two) means little stays on this PC, but files you come back to next week download again. "
                "Long keeps them instant, up to the cache size."),
    # ---- Hyprdots (default apps are read by keybinds.lua through user_overrides.lua) ---------------------------
    Setting(HYPRDOTS, "hyprdots", "terminal", "Terminal", "text", "ghostty", "Opened by Super+T.", allow_custom=True,
            effect="when Hyprland reloads", group="Default apps"),
    Setting(HYPRDOTS, "hyprdots", "file_manager", "File manager", "text", "thunar", "Opened by Super+E and Super+Shift+E (cloud drives).", allow_custom=True,
            effect="when Hyprland reloads", group="Default apps"),
    Setting(HYPRDOTS, "hyprdots", "browser", "Web browser", "text", "zen-browser", "Opened by Super+B.", allow_custom=True,
            effect="when Hyprland reloads", group="Default apps"),
    Setting(HYPRDOTS, "hyprdots", "store", "App store", "text", "flatpak run io.github.kolunmi.Bazaar", "Opened by Super+A.", allow_custom=True,
            effect="when Hyprland reloads", group="Default apps"),
    # Its own section: everything in [hyprdots] is passed to keybinds.lua as a default app
    Setting(HYPRDOTS, "look", "super_logo", "Super key shown as", "choice", "arch",
            "How the Super (Windows) key is drawn in the keybind cheatsheet (Super+K).", choices=SUPER_LOGOS,
            effect="next time the cheatsheet opens", group="Keybind cheatsheet"),
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
