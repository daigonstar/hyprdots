# <img src="screens/hypr.svg" alt="hypr" width="25" height="25" /> Hyprland Dotfiles <img src="screens/hypr.svg" alt="hypr" width="25" height="25" />

This is the configuration I am currently using for Hyprland
I have tried many dots in the past and I liked them but not ALL of what each one offered so I decided to make my own config
I have borrowed some code from the dots I like (especially JaKoolIt) but have also added my own spin on some things

I have also made an install script that should install everything nicely (I even left in the dry-run command just so you can see exactly what it is doing)

I have added some wallpapers I've collected (will probably add more as I go)

### **Keybinds**

<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + Space = Launcher  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + Q = Quit app  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + T = Terminal (Ghostty as default)  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + C = PC assistant (optional, see below)  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + CTRL + C = Clipboard history  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + E = File Manager (Thunar is default)  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + B = Browser (Zen is default)  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + A = App Store (Bazaar is default)  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + N = Refresh waybar  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> SHIFT + N = Launch waybar (used if waybar crashes)  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + W = Launch wallpaper selecter  

### Default Desktop
![image](screens/desktop.png)

### Terminal
![image](screens/term.png)

### **JaKoolIt** Wallpaper selector
![image](screens/wall.png)

### Applauncher (rofi)
![image](screens/appl.png)

### Powermenu
Full screen, with a PC (a laptop when a battery is found) in the middle and the options in a ring around it. Arrow keys, the first letter of an option, or the mouse.
![image](screens/power.png)

### Install:

The installer is for **Arch Linux** (it uses `pacman` and `paru`) and expects a Hyprland 0.55+ session with the Lua config. Run it as your normal user; it asks for `sudo` when needed. Try `./hyprinstall.sh --dry-run` first to see exactly what it would do.

```bash
git clone https://github.com/daigonstar/hyprdots.git
cd hyprdots
chmod +x hyprinstall.sh
./hyprinstall.sh
```
The installer enables multilib (needed for Steam), auto-detects your GPU (AMD, NVIDIA or Intel) and installs the matching drivers from `install/gpu-<vendor>.txt`. Force the choice with `HYPR_GPU="amd nvidia" ./hyprinstall.sh`. Everything else is in `install/required.txt` (Flatpaks in `install/flatpak.txt`). `install/hide.sh` hides unwanted app launcher entries listed in `install/hide.txt`. It also enables the needed services. The PC assistant is optional (see below).
### PC assistant (optional)

A local AI helper (Super+C or the bar button) that answers questions about your PC, calendar and the web. It runs through Ollama, so nothing leaves your machine, but it needs a reasonably strong GPU. The installer asks, shows what it detected and recommends a size:

| Tier | Chat model | Vision model | Download | Needs |
| --- | --- | --- | --- | --- |
| `full` | gpt-oss:20b | qwen2.5vl:7b | ~19 GB | 16 GB GPU memory |
| `balanced` | qwen3:8b | qwen2.5vl:3b | ~8 GB | 8 GB GPU memory |
| `light` | qwen3:4b | none | ~3 GB | 4 GB GPU memory, or CPU only (slow) |
| `custom` | any Ollama model | optional | - | - |
| `none` | no assistant | | 0 | |

The assistant is tuned for gpt-oss; smaller models are less reliable with tools. Choosing `none` installs no Ollama and hides the bar button; Super+C shows a hint instead. Change your mind any time:

    ~/.config/hypr/assistant/setup.sh                 # menu
    ~/.config/hypr/assistant/setup.sh --none          # turn it off
    ~/.config/hypr/assistant/setup.sh --tier balanced
    ~/.config/hypr/assistant/setup.sh --model qwen3:14b --vision-model none
    HYPR_ASSISTANT=none ./hyprinstall.sh              # unattended install choice

For web research, `setup.sh` also starts a private [SearXNG](https://docs.searxng.org/) search service in Docker or Podman when either is available (about 150 MB of RAM, idle CPU, 400 MB of disk). It listens on `127.0.0.1:8888`, so only this PC can reach it, and restarts on boot. Public search engines block or throttle scripts, so without it the assistant's searches are much narrower. Skip it with `--no-search`, or remove it later with `docker rm -f searxng`; its config lives in `~/.config/searxng/settings.yml` and is never overwritten.

Your choice is stored in `~/.config/hypr/user_settings.local.toml` (git-ignored). Without a vision model the screenshot and `/paste` features switch themselves off. If your chat model can see images (qwen3.5 can), set the vision model to **Same as chat model** in the settings app (or `vision_model = "same"`): one model does both, so there is no second download and nothing extra to load. The background health monitor is separate and needs no model.

Describe your own machine to the assistant in `~/.config/hypr/assistant/agent_context.md` (hardware, distribution, package manager, things that are deliberately odd). `setup.sh` creates it from the tracked template `agent_context.example.md` the first time and never overwrites it; it is git-ignored, and `update.sh` preserves it.

### Settings app

Click the cog in the waybar drawer (or run `~/.config/hypr/scripts/settings.sh`) for a menu where you can change things without editing files:

| Page | What you can change |
| --- | --- |
| Assistant | Pick the chat and vision model from the ones you have installed (or download one), thinking effort, memory use, colours, and switch the assistant on or off |
| Assistant Monitor | The assistant's background health checks (not your screens): when to warn about full disks, heat and failed services, and what to ignore |
| Calendar | Add, rename or remove calendars (links stay private) |
| Cloud drives | Google Drive, OneDrive, Dropbox, Nextcloud and other WebDAV accounts shown as folders in Thunar |
| Displays | Resolution, refresh rate, scale, rotation and position of each screen (replaces nwg-displays); changes apply at once and undo themselves if you do not confirm |
| Appearance | GTK theme, icons, cursor and font, and dark mode (replaces nwg-look) |
| Hyprland | Gaps, borders, rounding, blur, animations, layout, keyboard layout and mouse |
| Keybinds | Change the key combo for any action |
| File types | Which app opens links, pictures, video, PDFs, archives and other kinds of file |
| Hyprdots | Default terminal, file manager, browser and store, and which apps start with the desktop |

Every option has a short explanation and says when it takes effect. The Displays, Appearance, File types and Cloud drives pages apply straight away. On the other pages changes are not applied until you save: the title bar and a yellow bar at the bottom say how many are pending, and Ctrl+S, `s` or the **[ Save changes ]** button (mouse works too) keeps them. Your choices are saved to `~/.config/hypr/user_settings.local.toml` (and `user_overrides.lua` for the Hyprland look and apps); both are git-ignored, so updating the dotfiles never undoes them. The shared `user_settings.toml` only holds the defaults. Use `r` to go back to a default.

### User settings

The settings app edits these files for you; you can also edit `~/.config/hypr/user_settings.toml` (shared defaults) and `~/.config/hypr/user_settings.local.toml` (yours, and it wins) by hand.

Private values go in `~/.config/hypr/user_settings.local.toml` (git-ignored, created by the installer from `user_settings.local.toml.example`). To show Google Calendar events in the clock popup, copy your calendar's *Secret address in iCal format* (Google Calendar → Settings → your calendar → Integrate calendar) into `sources` there, then click the clock.

#### For my SDDM Greeter I use [SDDM Astronaut Theme](https://github.com/Keyitdev/sddm-astronaut-theme)
Please install that for a better greeter theme

### Notes

- Zen browser: if you sign in with a returning Mozilla account that has a custom wallpaper, set `zen.urlbar.replace-newtab` to `false` in `about:config`, otherwise the new-tab page will not show again on launch.

### License

MIT, see [LICENSE](LICENSE). The rEFInd theme (`.config/refind`) and the SDDM theme (`SDDM/sugar-dark`) keep their own licenses. Wallpapers are collected from around the web and belong to their respective creators.
