# hyprdots audit

Date: 2026-10-19. Four read-only reviews (installer and updater, Hyprland and desktop config, AI assistant, settings app and new menus), about 100 findings in total. Nothing was changed while auditing.

**How much to trust each item:** items marked *(checked)* were confirmed in the code by hand. The rest come from a reviewer reading the code; none of the exploit scenarios were actually run. One reviewer claim was wrong and is left out: `imagemagick` is not missing from the installer, it is installed as an extra dependency.

## Fix first

| # | Problem | Why it matters |
|---|---|---|
| 1 | `update.sh` moves your local config (`monitors.lua`, `user_settings.local.toml`, `user_overrides.lua` and others) to `~/.config/backup` before it checks the network. A failed `git fetch` strands it there. *(checked)* | Hyprland fails to load `monitors.lua` on the next start. |
| 2 | `update.sh` runs `git reset --hard` on the repo while it is still reading `update.sh`. | The rest of the run can execute garbled. |
| 3 | `git clean -fdx` deletes more than the five preserved files, including the saved branch choice. The updater also never installs new dependencies from `install/required.txt`. | Existing installs break after an update that adds a package. |
| 4 | `hyprinstall.sh` and `update.sh` delete your existing configs and `~/Pictures/wallpapers`. The installer's backup prompt defaults to No. | A clean-machine user can lose their own configs and wallpapers. |
| 5 | `assistant/setup.sh` classes every Intel GPU as AMD: the pattern `amd\|ati\|advanced micro` matches "Intel Corporation". *(checked)* | Intel users get the AMD ROCm build of ollama. |
| 6 | `assistant/setup.sh` assumes `paru` exists. On a clean Arch machine the install silently fails. | This is the bug hit on the laptop. |
| 7 | Assistant command guard bypasses: `env -S`, docker/systemctl option values read as the subcommand, `git ls-remote --upload-pack`, `cp`/`mv --target-directory=`. `write_file` can also stage a config file that a "safe" command then loads. | Commands run or files are written without a prompt. Prompt injection from a web page or calendar entry could use this. |
| 8 | Displays page: turning off the laptop's own screen while docked can be saved to `monitors.lua`. | Undocked, no screen is enabled. |
| 9 | Display confirm popup: Esc is ignored and Enter keeps the layout, but the text says anything else puts the old settings back. Saving also forgets screens that are not plugged in, and mirrored screens are not handled. | On a blank screen the popup cannot be cancelled. |
| 10 | The Super+K cheatsheet reads `~/.config/hypr/keybinds.conf`, which no longer exists. *(checked)* | The cheatsheet opens empty. |
| 11 | `.config/rofi/.current_wallpaper` is committed as a symlink to `/home/robb/Pictures/wallpapers/lieutenant-titus.jpg`, and `.config/rofi/.wallpaper_current` is a committed 2.2 MB JPEG. *(checked)* | They break game mode on other machines and are re-committed on every wallpaper change. |

## Installer and updater

- `update.sh` reads its whole body before the repo is reset; wrap it in a function or re-run itself after the reset.
- Wallpapers are wiped and recopied on every install and update; use `rsync -a` or `cp -rn`.
- Plymouth: `git clone` into `/usr/share/plymouth/themes` fails on a re-run and aborts the installer under `set -e`. The `plymouth` hook and `splash` kernel parameter are never added, so the splash never appears.
- `--dry-run` crashes on a machine without `paru`, because the clone is only printed and `pushd` then fails.
- The log directory is created only in dry-run mode, so a real first run falls back to `~/hyprinstall.log`.
- The cursor theme copy nests (`Future-cursors/Future-cursors`) on the second run. The SDDM `Xsetup.bak` is overwritten on the second run.
- SDDM monitor detection uses `xrandr`, which needs a display; from a TTY it finds nothing.
- The installer defaults to the unstable `dev` branch, and the pull rewrites `hyprinstall.sh` mid-run.
- Services are enabled unconditionally (`NetworkManager`, `docker`, and others), which can drop the network on machines using another network manager.
- Packages used but not listed in `install/required.txt`: `lm_sensors`, `kitty`. `bluetui` and `docker-compose` need checking.
- CI does not run the settings tests (`.config/hypr/settings/tests/` is gitignored, including `test_mime.py` and `test_displays_gtk.py`), does not run a dry-run install, and uses `shellcheck -S error`, which hides most warnings.
- Hardcoded paths: `install/hide.sh` defaults to `$HOME/hyprdots/...`, `.bashrc` aliases expand `$REPO_DIR` at install time, and `update.sh` has a shorter chmod list than the installer.

## Hyprland, Waybar and rofi

- `autostart.lua` and the Super+F12 keybind hardcode `DP-1`; both do nothing on a laptop with `eDP-1`.
- `environment.lua` sets `WLR_DRM_DEVICES=/dev/dri/card0`. Hyprland probably ignores it (it uses `AQ_DRM_DEVICES`), and if honoured it pins the wrong GPU on hybrid laptops.
- `hypridle.conf` uses `hyprctl dispatch dpms on/off`, and `scripts/startup.sh` uses `closewindow`; both are legacy dispatcher forms that may not work under the Lua config. Not tested.
- `hypridle.conf` and `gamemode.sh` point at `swaync/images/ja.png`, which does not exist (it is at `rofi/images/ja.png`).
- `hyprpaper.conf` is dead (the setup uses awww) and contains `/home/robb/...` paths.
- Waybar CSS names the font `ttf-cascadia-code-nerd` (an Arch package name, not a font family) and mixes in `NotoSansMono Nerd Font`, which is not installed. Rofi themes use `JetBrainsMono Nerd Font` and `feather`, also not installed.
- Dead files: the old rofi power-menu theme (`powermenu/style.rasi`, `shared/colors.rasi`, `shared/fonts.rasi`), `rofi/colors/onedark.rasi`, and unused Waybar modules (`custom/notification`, `custom/endpoint`, `custom/separator`). Several CSS selectors match nothing (`.expand`, `#bluetooth-connected`, `#pulseaudio.format-icons`).
- `refresh.sh` sends SIGUSR1 to Waybar after killing it, which toggles visibility; `gamemode.sh` ends with an unreachable `hyprctl reload`.
- Waybar's update click runs `bash -ic update`, which depends on the `.bashrc` alias.
- `wallust.toml` has orphaned templates and writes kitty and cava configs for programs that are not required.
- Hardware-specific defaults: UK keyboard layout, an `epic-mouse-v1` device rule, and autostart entries (`openrgb ... Ice.orp`, Solaar, Nextcloud, Bitwarden) that are on by default.
- `.gitignore` does not cover `*.orig` and `*.rej`.

## AI assistant

- **Guard bypasses** (reading `hypr_agent.py` around lines 2485-2720): see item 7 above. Others in the same area:
  - `/allow` auto-approves wrappers such as `sh -c "sudo ..."`, `env sudo` and `xargs sudo`.
  - Abbreviated long options bypass exact-match deny lists (`sort --out=FILE`, `grep --rec`, `nmcli c del`).
  - `nmcli -s -g ... c show` prints Wi-Fi passwords into the model context.
  - The blocked-path list omits browser profiles, `.docker/config.json`, `.npmrc`, shell history, `/proc/*/environ`, and `printenv`/`env` dump environment secrets.
- Data can leave the machine with no prompt: `web_fetch` and `web_search` take free-form URLs and queries after the model has read sensitive data.
- The approval prompt prints raw command text, so control characters can overwrite what the user sees.
- Journal text and calendar event titles go into the system prompt without being marked as untrusted. `_note_from_user` can save a note with no confirmation if it has no long words, and saved notes persist across sessions.
- No client timeout on calls to ollama; a stalled server hangs the process.
- State files in `~/.local/state/hypr_agent` are world-readable, and `failures.log` can contain secrets from tool output.
- A timed-out confirmed command can leave child processes running; `sudo` ignores a non-root kill.
- `setup.sh`: the SearXNG config is created mode 0600 and probably unreadable inside the container; the image is unpinned `:latest`; `vision_model = "same"` is passed to `ollama pull`; ollama can be started three different ways (`ollama.sh`, `setup.sh`, the agent).
- `agent_monitor.py`: the report is written non-atomically, a missing `notify-send` crashes it, `journalctl` output is unbounded, and the service has no timeout.
- Small items: predictable `/tmp` fallback paths, a double-press race in `assistant-toggle.sh`, `$(cat browser.sh)` run as a command in `ai.sh`, and dead code (`hypr_agent.py.bak`, `_page_excerpt`).

## Settings app and new menus

- **Displays:**
  - Item 8 and 9 above.
  - The 10-second revert timer and the `y` key can race, leaving the file and the live layout disagreeing.
  - `fresh` can be an empty list from a failed `hyprctl`, which would write an empty `monitors.lua`.
  - Scale is rounded to 3 decimals on read, then every screen is re-applied, so a 1.666667 scale becomes 1.667.
  - Applying runs synchronously in the key handler and freezes the UI.
  - Screens are keyed by port name, so DP-1 and DP-2 swapping loses their settings.
- **Cloud drives:**
  - It lists and can remove every `rclone` remote, including hand-made crypt, sftp and s3 remotes.
  - Remote names are not escaped in the systemd unit template, and `exe` is not quoted.
  - The WebDAV password is passed on the command line.
  - `rclone` and `systemctl` calls run on the render thread and can freeze the UI; Esc does not stop a mount in progress.
  - Bookmarks and unit files are written non-atomically.
- **File types:** the default lookup ignores desktop-specific `mimeapps.list` files, Removed Associations, `Hidden=true` masking, and MIME aliases.
- **Appearance:** writing `settings.ini` replaces a symlinked file with a regular file, and the GTK 4 link step unlinks any existing symlink.
- **`exo-terminal.sh`:** the cleanup of `helpers.rc` can strip the `[Default]` header and leave a broken file when other keys are present.
- **Power menu:** the toggle uses `pkill -f` on the script path, which also matches an editor that has the file open. Lock is silent if `hypridle` is not listening. The layer-shell library path is hardcoded to `/usr/lib`.
- **Wallpaper picker:** a second keypress closes and then reopens it, and it kills any rofi. Thumbnails are written straight to their final name, so a killed run leaves a broken file that is never regenerated. Thumbnail names use a 32-bit checksum, so two files can collide.
- **Smaller:** the TOML parser ignores `[[arrays]]` and multi-line strings; the private settings file is briefly readable before `chmod`; `nan`/`inf` pass float validation and break the generated Lua; `KeyError` from `hyprctl` crashes the Displays page; a terminal under 60x16 wraps badly.
- **First-time user:** "SUPER + +" cannot be entered as a key; the 10-second timer has no on-screen countdown; some pages save immediately and some wait for Ctrl+S.
- **Test gaps:** no tests for `cloud.py`, the revert race, Esc/Enter on the confirm popup, mirrored or laptop layouts, disabled-monitor persistence, hotplug, `sync_terminal`, or the shell scripts.

## Suggested order

1. Updater and installer safety (items 1-4), then the Intel and `paru` bugs (items 5-6).
2. Tighten the assistant guard (item 7) by allow-listing flags per command instead of deny-listing, then fix the display popup and docked-laptop cases (items 8-9).
3. Clear the broken or accidentally committed files (items 10-11) and un-ignore the tests so CI runs them.

## For the launch page

A first-run page should cover: which screen is the primary one, whether this is a laptop, that `paru` is needed for the assistant, and a short tour of the settings pages.
