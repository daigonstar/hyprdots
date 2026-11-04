# hyprdots audit

Updated: 2026-11-04. This replaces the audit of 2026-10-19; what that one found and got fixed is summarised at the end, and the full text is in git history.

**The goal:** a modern, sleek, reliable desktop with features that make it stand out, on a **desktop, a laptop and a tablet PC**. This lists everything found that stands between today and that goal, in the order it matters.

**How much to trust each item:**

- **[checked]** confirmed in the code or on the running desktop while writing this.
- **[old]** carried over from the first audit and still looks open, but not re-proven. Reviewer findings; none of the exploit scenarios were ever run.
- **[gap]** something that does not exist yet.
- **[idea]** not a fault: a feature that would help it stand out.

Everything was tested on one PC: a desktop with two screens and an AMD card. Nothing has run on a real laptop or tablet.

## Where it stands

These are judgement calls, not measurements.

| | Today | What is missing most |
|---|---|---|
| **Desktop (this PC)** | About 90% | Real-world use, and the hand checks below |
| **Fresh install on another PC** | About 85% | Passes in a virtual machine with default answers; real graphics drivers tested by hand only |
| **Laptop** | About 50% | Lid, power profiles, gestures, sleep on battery. What exists has only run on simulated hardware |
| **Tablet** | About 15% | No on-screen keyboard, rotation or touch gestures, and much of the desktop assumes a keyboard or a hover |

## 1. Reliability: fix these first

A desktop feels unreliable when one failure leaves you stuck, so these come before any new feature.

### Nothing has been proven on a blank machine

- **A real install now passes in a virtual machine.** [checked] `install/tests/vm/vm.sh test` takes a blank Arch disk through the full-screen installer, a reboot, two logins and checks, in about 15 minutes. First passed on 4 November, after fixing what only a blank machine shows: `pipewire-jack` stopping the install, Flathub setup failing without `sudo`, no wallpaper at first login, no Python for the installer, and `makepkg` asking for the password again (it runs `sudo -k`). It covers the default answers only, with no extra apps, no assistant and a plain virtual card, so real graphics drivers and bare metal are still untested. It needs KVM, so it does not run in CI.
- **Nothing tests the desktop itself.** [gap] CI runs unit tests and a dry run. Nothing starts Hyprland, the bar or the tray, and this session's bugs (Dismiss could not be clicked, Alt+Tab crashed on some apps, a bad rule option) were all of the kind that only a real run finds. A headless Hyprland in CI could at least catch config errors and start-up crashes.
- **Hand checks are outstanding.** [checked] See the list near the end.

### If a background part dies

- **Restarts are in; a real login is still to be checked.** [checked] The bar, swaync, tray, udiskie and hypridle are now systemd user services (`hypr/systemd`, started by `scripts/desktop-services.sh`). Each was killed with `kill -9` on this PC and came back within 2.5 seconds. After 5 crashes in 2 minutes systemd stops, you get one notification, and `SUPER + N` brings it back. Logs are in the journal, and the health monitor reports parts that are down or keep crashing. A first version froze login for 24 seconds by racing Hyprland's own session target; that fix still needs a real log out and in to confirm.
- **The tray holds a lot.** [checked] The same process holds the volume popup, Alt+Tab, the overview and the battery warnings, and its notification list is lost when it restarts.
- **Not covered:** the clipboard watcher, wallpaper daemon and game workspace script are still started once. A crashing part restarted with `KillMode=process` can leave old helpers behind, such as a `swaync-client` from the bar.

### Updates and bad changes have no way back

- **Undo for updates is in, for most updates.** [checked] On btrfs the installer offers snapper and snap-pac, and `hyprundo` puts the last pacman or paru run back; tested in a VM by undoing a real package install. It cannot undo a kernel change, as `/boot` is not in the snapshot, and there is no boot menu entry, so a PC that no longer starts still needs a live USB.
- **Stable channel waits for 1.0.** [checked] Decided 4 November: no branches until there is a good 1.0, so everything follows `main` until then. The support is in and stays dormant: with no `stable` branch there is no menu and nothing is saved. Running `install/promote.sh` creates the branch and switches it on for new installs. Each update already lists what changed.
- **Safe mode is in, with gaps.** [checked] A Lua file that fails to load now falls back to its last working copy (`hypr/safe_config.lua`), with emergency keys if the keybinds have no copy, and Settings checks the config before reloading. Tested in a nested Hyprland, not yet through a real broken login. Not covered: a mistake in `hyprland.lua` or `safe_config.lua` themselves, a file that loads but does the wrong thing, and `autostart.lua` failing after it has registered its start-up, which would start things twice.

### Hardening

- **No firewall in the dots.** [checked] `ufw` is installed on this PC, but the install list does not set one up.
- **No disk encryption path.** [checked] This PC has none, and the installer says nothing about it. It matters most on a laptop or tablet that can be lost.
- **Hearthling data handling.** See section 7: the web check is a safeguard, not a guarantee.

## 2. Foundation for three kinds of device

These sit underneath the laptop and tablet work, so they come first.

- **One idea of "what device is this".** [gap] The tray checks for laptops itself, and the power menu checks for a battery. A single detected profile (desktop, laptop, tablet or convertible, from the chassis type, battery, touchscreen and tablet switch) should drive the defaults everywhere, and be overridable in Settings.
- **Defaults are no longer this PC's.** [checked] New installs get a US keyboard unless they choose (the installer asks), no named mouse or lighting profile, and only the Steam game rules built in. Settings and the cheatsheet leave out apps you did not install. Installs that relied on the old UK default or the old built-in rules need to set them again.
- **HiDPI works in a VM.** [checked] Scales 1.25, 1.6 and 2 were looked at on one virtual screen: the bar, tray, calendar, launcher and power menu fit, and scroll when the screen is too short. GTK 3 parts are slightly soft at fractional scales, which they cannot avoid. Not yet seen on a real HiDPI panel, or with Xwayland apps.
- **A screen with no saved settings** now gets its preferred mode and an automatic scale. Still needs seeing on a real laptop panel.
- **The Surface.** [gap] The earlier plan is still waiting on the model. ARM Surfaces (Pro X, Snapdragon Pro 11 and Laptop 7) cannot run Arch normally, so this decides what is possible. The rest needs `linux-surface` and `iptsd`.

## 3. Laptop

- **Lid is not handled.** [checked] There is no lid bind or setting. It needs: sleep when closed on battery, and with an external screen connected, turn off the built-in panel and keep working, then bring it back when opened. Audit item 8 stopped this being saved wrongly, but the behaviour itself is missing.
- **No power profiles.** [checked] `power-profiles-daemon` or `tuned` is not installed, so the tile never appears. It should also switch by itself on battery.
- **Idle does not know about battery.** [checked] The Power & lock page has one set of timeouts. Laptops want shorter ones on battery.
- **No hibernate.** [gap] Sleep only, including the 3% battery action. Suspend-then-hibernate protects work on a dying battery, but it needs swap set up by the installer.
- **No touchpad gestures.** [checked] `hl.gesture` exists but nothing is configured. Three-finger swipe between workspaces and four-finger for the overview are the minimum, with a Settings page.
- **No network status on the bar.** [checked] I removed it from the default, since the tray has it. A desktop on a cable does not need it, but a laptop on Wi-Fi does. Same for Bluetooth headphones. The profile above should decide.
- **Brightness popup only follows the keys.** [checked] Automatic brightness or firmware keys do not show it. There is no keyboard backlight control or popup, and no automatic screen brightness.
- **Battery details.** [gap] Time remaining, health, and a charge limit to protect the battery.
- **Fingerprint login.** [gap] `fprintd` with hyprlock and the login screen, where the hardware allows.
- **Graphics switching on hybrid laptops.** [gap] The installer can install drivers for two cards, but nothing helps run an app on the dedicated one.
- **Laptop parts have only run in simulation.** [checked] Battery row, brightness slider, touchpad and airplane tiles. The touchpad switch's command has never run against a real touchpad.

## 4. Tablet

Nothing here exists yet, and most of it is [gap]. It decides whether this can be a tablet desktop at all.

- **No on-screen keyboard.** With no keyboard attached you cannot type. It needs one that appears for text fields (`wvkbd` or `squeekboard`) and works on hyprlock and the login screen, or you cannot unlock.
- **No auto-rotate.** `iio-sensor-proxy` with `iio-hyprland` or a small script, plus a rotation lock tile in the tray. Rotation must also rotate touch and pen input.
- **No tablet mode.** Detect a detached keyboard and switch: show the on-screen keyboard, larger controls, and windows fullscreen or side by side.
- **No touch gestures.** Edge swipes to open the launcher and tray, swipes between workspaces, and three-finger close. `hyprgrass` needs `hyprpm`, which is not installed, and I do not know its state under the Lua config. `lisgd` is the plugin-free choice. Needs a test.
- **Controls that need hover or a keyboard.** [checked]
  - The bar's system tray drawer opens on hover (`click-to-reveal` is false), so touch cannot open it.
  - Alt+Tab is keyboard only, and the overview's keyboard shortcut has no touch way in except the tray.
  - The tray has no keyboard navigation at all, and its sliders and small icon buttons are mouse-sized.
  - The overview's drag uses GTK drag and drop, which has never been tried with a finger.
- **Touch sizes.** Bar icons are 15px. A tablet preset needs a taller bar with larger targets.
- **Pen.** Pressure and eraser, mapped to the built-in screen only, and a note-taking shortcut. Pen button actions in Settings.
- **Handwriting and palm rejection.** Depends on hardware and `iptsd`.

## 5. Desktop

The strongest of the three. What is left:

- **HDR.** [gap] No setting on the Displays page, though Hyprland has been adding support. Check and expose it.
- **Screens keyed by port name.** [old] Displays stores `DP-1` and `DP-2`, so swapping cables loses settings. Use the monitor's description instead.
- **Per-screen profiles.** [gap] "Docked", "just the main screen" and "TV" layouts you can switch between, which also matters for laptops.
- **A wake-from-sleep and game check.** [gap] Game mode, VRR and sleep have not had a dedicated stress test. Game mode no longer restarts the bar, but a video wallpaper is not restored afterwards. [checked]
- **Boot time.** [checked] 34.7 seconds on one boot: 16.4 firmware, 4.9 loader, 6.5 kernel, 6.9 userspace. The firmware is now the largest part, so the loader is no longer the easy win it looked like.

## 6. Modern and sleek

Things people now expect, and the finish that makes it feel designed.

### Missing basics

- **Accessibility: none.** [checked] No screen reader support has been tested, no large-text or high-contrast mode, and no reduced-motion option beyond turning animations off. The tray is mouse-only. Colour alone carries some meaning.
- **Other languages.** [checked] All text is hard-coded English.
- **Printers.** [checked] Nothing for CUPS or printer setup.
- **Phone connection.** [checked] No KDE Connect. LocalSend is included.
- **Screen sharing check.** [gap] Portals are installed, but the common apps have not been tested.
- **Notification buttons in the tray.** [checked] Reply and similar only work on popups, and clicking a notification does not open its app. It was kept this way by choice. The options are replacing swaync with a daemon of our own, or adding an "Open app" button by focusing the app's window.
- **Notifications from before the tray started** [checked] only show as a count, and the list is lost if the tray restarts.
- **Grouped notifications and per-app settings.** [gap] Several messages from one app should fold together, and each app should be able to stay quiet.
- **Per-app volume.** [gap] The tray has output and input only, and no per-app sliders.
- **Tray settings.** [gap] You cannot choose which tiles and shortcuts appear, or their order. Nothing to adjust sounds, or volume ticks separately.
- **Update centre.** [gap] Updates open a terminal running `paru`. A page showing what changes, with one button, would suit a non-terminal user.
- **Backup.** [gap] Nothing for your own files, and no export of your settings to carry to a new device.
- **Drive popups need a real USB test.** [checked] See the hand checks.

### Consistency and finish

- **Look and feel across parts.** [gap] The tray, launcher, power menu, settings and rofi pickers each draw their own controls. Corner radius, spacing and sizes should come from one shared set, as colours already do. Two toolkits (GTK 3 and GTK 4) and rofi are in use, which keeps them slightly apart.
- **Rofi is the odd one out.** [checked] Wallpaper, clipboard and emoji pickers still use it. It does not support the same animation or touch, and it would be better replaced by the launcher's own style.
- **Qt apps.** [checked] Only Ark has been checked. Links stay blue, buttons are low contrast on a black palette, and running apps only recolour when reopened. Whether other apps, such as OpenRGB, follow is untested.
- **Colour contrast is not guaranteed.** [gap] A role can land on a colour that is hard to read. The Theme page, or the wallust step, should enforce a minimum, instead of leaving it to the wallpaper. The amber update pill is one place it could show.
- **Video wallpapers.** [gap] From reading the script, game mode does not restore one. How the lock screen and overview look with one has not been tried.
- **Login to desktop handover.** [gap] Plymouth, the login screen, the lock screen and the desktop should look like one continuous thing. Not checked end to end at each scale.
- **Stale leftovers.** [checked] Comments naming `JaKooLit` and odd names remain in older scripts.
- **README screenshots.** [checked] They need a fresh set once the look settles, and the tray, overview and window rules have none.
- **Very large files.** [checked] `tray/quick_tray.py` is 1,204 lines and `assistant/hypr_agent.py` is 5,116. They need splitting before more goes in.
- **Deprecated calls.** [checked] `popup_calendar.py` still uses `GLib.unix_signal_add`.
- **Known calendar quirk.** [checked] It closes itself whenever it loses focus, including when started from a script.

## 7. Open items from the first audit

Still open unless noted. Rechecked as far as a read of the code allows.

### Hearthling

- **Data leaving through the web is only partly closed.** [checked] Web calls now ask first when the query or address the model wrote is very long, or contains an email address, the home path, this PC's name, a secret, an encoded string, a long number, or a phrase from your notes, calendar, images or files in your home folder. This recognises data; it cannot prove none left. A reworded or short fact gets through, and `resolvectl query` can still carry data out in a DNS lookup without asking.
- **Untrusted text in the prompt.** [old] Journal text and calendar titles are not marked as untrusted. `_note_from_user` can save a note with no confirmation if it has no long words, and notes persist.
- **`setup.sh`.** [checked] The SearXNG config is created mode 0600 and may be unreadable in the container, and its image is an unpinned `:latest`. [old] `vision_model = "same"` is passed to `ollama pull`, and Ollama can be started three different ways.
- **`agent_monitor.py`.** [checked] The report is not written atomically, a missing `notify-send` would crash it, journal output has no limit, and the service has no timeout.
- **Small.** [checked] A double-press race in `assistant-toggle.sh` (no lock), and dead `_page_excerpt`. [old] `/tmp` fallback paths, and a timed-out command may leave child processes (`killpg` is now used on some paths, so this needs a fresh look).

### Settings app

- **Displays.** [checked] Scale is rounded when read, so 1.666667 becomes 1.667 and is re-applied. [old] The revert timer and the keep key can race, and applying can freeze the page.
- **Cloud drives.** [checked] It lists and can remove every `rclone` remote, including hand-made ones. The executable path is unquoted in the unit file, and bookmarks and unit files are not written atomically. The obscured WebDAV password is on the command line, and there are no tests for `cloud.py`. Fixed since the first audit: the GTK page no longer blocks on these calls.
- **File types.** [checked] Removed Associations and MIME aliases are not honoured. `Hidden=true` now is.
- **GTK settings.** [checked] Writing `settings.ini` replaces a symlinked file, and the GTK 4 step removes any existing link.
- **`exo-terminal.sh`.** [checked] Cleaning `helpers.rc` removes the `[Default]` header, which can leave a broken file if other keys are there.
- **Power menu.** [checked] Its toggle uses `pkill -f` on the script path, which also matches an editor with that file open. [old] Lock is silent if `hypridle` is not listening, and the layer-shell path is hard-coded to `/usr/lib`.
- **Wallpaper picker.** [checked] Thumbnails are written straight to their final name, so a killed run leaves a broken one that is never remade. Names use a 32-bit checksum, so two can collide. [old] A second keypress closes and reopens it.
- **Smaller.** [old] The TOML parser ignores `[[arrays]]` and multi-line strings, `KeyError` from `hyprctl` can crash Displays, and a terminal under 60x16 wraps badly.
- **First-time use.** [old] "SUPER + +" cannot be entered as a key, the terminal version has no countdown for the display timer, and some pages save at once while others wait for Save.
- **Test gaps.** [checked] No tests for `cloud.py`, the revert race, mirrored or laptop layouts, disabled-monitor persistence, or real screen changes. The GUI itself has almost none: `gui/windowrules.py` and the tray's windows were only checked by driving them in a scratch script.

## 8. Features that would make it stand out

None of these are faults. Many Linux desktops can match the basics, so this is where it could be different. All [idea]. The first two groups build on what is already unusual here.

### Hearthling as part of the desktop

The strongest thing this has that others do not. Today it is a separate chat window.

- **In the launcher:** type a question into Super+Space and get an answer or an action.
- **Explain this:** "what is this error?" on a notification, or on a screenshot or selected text.
- **Do it for me:** "make Discord always open on workspace 2" writes a window rule, with the same approval flow.
- **Health that fixes itself:** the PC Health monitor's warnings could offer a fix button that hands the problem to Hearthling.
- **Local and private by default,** which is worth saying clearly in the README.

### One desktop that adapts

- **Tablet, laptop and desktop modes that switch by themselves,** with the same apps and settings. Few Linux setups do this well, and this could be the headline feature.
- **Modes for what you are doing:** "Gaming", "Work" and "Focus" switch game mode, do not disturb, wallpaper, bar layout and which apps open, in one click from the tray. Game mode is the start of this.
- **Follow-me colours:** the wallpaper-driven theme is already unusual in reaching this far. Add a smooth colour transition when the wallpaper changes, and automatic light and dark by time of day.
- **Time-of-day wallpaper,** tied to the night light with a sunset schedule.

### Everyday touches

- **A launcher that searches everything:** files, settings pages, windows, calendar, clipboard, and web.
- **Smart screenshots:** copy text from a screenshot (`tesseract` is already on this PC, though not in the install list), annotate, and pin to the screen.
- **Clipboard with pictures** in a panel of its own, rather than a rofi list.
- **Live activity on the bar:** a small area for media, recording, timers and downloads, like a phone's.
- **Now playing with artwork,** in the tray and on the lock screen.
- **Calendar in the tray:** today's events beside the clock or notifications, and a reminder before each.
- **Weather** on the tray or lock screen.
- **Window snapping layouts:** pick a layout from the tray or by dragging, for people who are new to tiling.
- **Session restore:** reopen what you had, on the right workspaces, after a restart.
- **Peek at a workspace** by hovering on it in the bar, reusing the overview's window pictures.

### A proper first impression

- **A graphical installer or a live USB** rather than a shell script, including partitioning and encryption.
- **A fuller welcome:** pick your device type, keyboard, apps, wallpaper, and then a short interactive tour.
- **A website or README with short videos,** since motion is much of the appeal.

## 9. Hand checks still to do

These cannot be clicked or pressed from the tools used.

**Popups**
- [ ] Click inside a popup: it stays open. Click outside, on another screen and on the desktop: it closes
- [ ] Click the bell or the clock while its popup is open: it closes and does not reopen
- [ ] A toast: clicking elsewhere hides it, and it stays listed in the quick tray

**User page**
- [ ] Choose a picture with the file picker, then remove it
- [ ] Change your name
- [ ] Change your password, trying a wrong current one once, then log in with the new one. Have the old one written down until you have

**Desktop**
- [ ] Hold Alt and tap Tab, with windows on both screens
- [ ] Overview (`SUPER + TAB`): click a window, click a workspace, and drag a window to another
- [ ] Bar: the system tray arrow still opens on hover
- [ ] Window rules: add a rule with the wizard and press the real Save, then switch one off
- [ ] Night light on and off
- [ ] Screenshot: Open, Show in folder and Edit buttons, and region and window modes
- [ ] Emoji typed into an app, and a picked colour pasted
- [ ] Record an area with the mouse, and stop from the REC badge

**Hardware**
- [ ] Plug in a USB stick: mounts, notifies, opens and ejects from the tray
- [ ] Log out and back in: udiskie and the tray both start, and the login is quick
- [ ] Unplug a screen for real and plug it back in (it was only simulated by turning one off)
- [ ] Sleep and wake with the tray open
- [ ] OpenRGB: your lighting profile loads at login

**Optional: undo for updates on your PC** (this changes your system, so it has not been done there)
- [ ] `sudo ~/hyprdots/install/snapshots.sh`, run `pacman -S` on something small, then `hyprundo` and check it is gone

## 10. Suggested order

1. **Prove it works:** run the hand checks.
2. **Make it hard to break:** the small open items in section 7 that remain.
3. **Tidy up:** split the large files, and refresh the README's screenshots.
4. **Build the foundation for three devices:** device profile, first-run choices, and HiDPI.
5. **Laptop:** lid, power profiles, gestures, and battery-aware idle. A real laptop is needed from here.
6. **Tablet:** confirm the Surface model first, then on-screen keyboard, rotation, gestures, and touch sizes, tested on the device.
7. **Sleek:** shared design values, replacing rofi, accessibility, grouped notifications, and per-app volume.
8. **Stand out:** Hearthling in the launcher, automatic device modes, and activity modes.

## Fixed since the first audit

All are in git history.

- **Installer and updater:** local config is no longer stranded or deleted, the update runs safely while replacing itself, missing packages are installed, and configs are backed up rather than removed. Dry runs are safe and run in CI, along with shellcheck and all test suites. Plymouth and the login screen were reworked, and the login screen now runs on Wayland.
- **Desktop config:** hard-coded `DP-1` paths, old dispatchers, dead files, font names and rainbow border overrides are all gone.
- **Assistant:** the listed command guard bypasses are closed, wrapped `sudo` always asks, secrets and browser profiles are blocked, and control characters are shown as text.
- **Settings:** the display popup can be cancelled, a built-in screen is never saved as off, the cheatsheet works again, and the settings window is now GTK.
- **Installer password, 4 November:** the full-screen installer asks for your password in an overlay whenever sudo needs it, including from `makepkg` and `paru`.
- **Updates and installs, 3 November:** updates keep hand edits, untracked files and your own configs, stop on unpushed commits, and are tested against a throwaway remote. The installer is now a full-screen interface asking for keyboard, graphics, browser, optional apps, Hearthling and more up front, then showing live progress. `install/apps.sh` adds more later. Update tests and install-choice tests run in CI.
- **Settings and drivers, 4 November:** a User page in Settings for your name, picture and password, with the picture on the quick tray and lock screen. A graphics card with no drivers is now noticed at login and in `update.sh`.
- **Popups and icons, 4 November:** a click outside closes popups and hides toasts (`hypr/click_away.lua`; touchscreen taps do not trigger it). Icons are centred by using the Nerd Font's Propo cut.
- **4 November:** web calls ask first when they appear to carry private data, Hearthling's state folder and files are private to you, calls to Ollama have a timeout, and stale `.orig`/`.rej` files, `hypr-dock` and three unused scripts are gone.
- **Added on 2 November:** the quick tray, notifications in one panel, volume and brightness popups, Alt+Tab, the workspace overview, screenshot actions, screen recording, emoji and colour pickers, night light, system sounds, low battery warnings, USB handling, screen hotplug handling, Qt theming, new animations, a first-run welcome, the Window rules page and wizard, and a cleaned-up bar.
