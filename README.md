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
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + C = Open clipboard  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + E = File Manager (Thunar is default)  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + B = Browser (Zen is default)  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + A = App Store (Cosmic is default)   
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> + N = Refresh waybar  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> SHIFT + N = Launch waybar (used if waybar crashes)  
<img src="screens/tux.svg" alt="Tux" width="25" height="25" /> SHIFT + W = Launch wallpaper selecter  

### Default Desktop
![image](screens/desktop.png)

### Terminal
![image](screens/term.png)

### **JaKoolIt** Wallpaper selector
![image](screens/wall.png)

### Applauncher (rofi)
![image](screens/appl.png)

### Powermenu (JaKoolIt)
![image](screens/power.png)

### Install:
```bash
git clone https://github.com/daigonstar/hyprdots.git
cd hyprland-dots/hyprdots
chmod +x hyprinstall.sh
./hyprinstall.sh
```
The installer enables multilib (needed for Steam), auto-detects your GPU (AMD, NVIDIA or Intel) and installs the matching drivers from `install/gpu-<vendor>.txt`. Force the choice with `HYPR_GPU="amd nvidia" ./hyprinstall.sh`. Everything else is in `install/required.txt` (Flatpaks in `install/flatpak.txt`). `install/hide.sh` hides unwanted app launcher entries listed in `install/hide.txt`. It also enables the needed services. The PC assistant is optional (see below).
### User settings
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

Your choice is stored in `~/.config/hypr/user_settings.local.toml` (git-ignored). Without a vision model the screenshot and `/paste` features switch themselves off. The background health monitor is separate and needs no model.

Describe your own machine to the assistant in `~/.config/hypr/assistant/agent_context.md` (hardware, distribution, package manager, things that are deliberately odd). `setup.sh` creates it from the tracked template `agent_context.example.md` the first time and never overwrites it; it is git-ignored, and `update.sh` preserves it.

All options for the PC assistant, health monitor and popup calendar live in `~/.config/hypr/user_settings.toml` (the cog in the waybar drawer opens it).

Private values go in `~/.config/hypr/user_settings.local.toml` (git-ignored, created by the installer from `user_settings.local.toml.example`). To show Google Calendar events in the clock popup, copy your calendar's *Secret address in iCal format* (Google Calendar → Settings → your calendar → Integrate calendar) into `sources` there, then click the clock.

#### For my SDDM Greeter I use [SDDM Astronaut Theme](https://github.com/Keyitdev/sddm-astronaut-theme)
Please install that for a better greeter theme

### Notes

- Zen browser: if you sign in with a returning Mozilla account that has a custom wallpaper, set `zen.urlbar.replace-newtab` to `false` in `about:config`, otherwise the new-tab page will not show again on launch.
