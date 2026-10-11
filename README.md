# <img src="/hyprdots/screens/hypr.svg" alt="hypr" width="25" height="25" /> Hyprland Dotfiles <img src="/hyprdots/screens/hypr.svg" alt="hypr" width="25" height="25" />

This is the configuration I am currently using for Hyprland
I have tried many dots in the past and I liked them but not ALL of what each one offered so I decided to make my own config
I have borrowed some code from the dots I like (especially JaKoolIt) but have also added my own spin on some things

I have also made an install script that should install everything nicely (I even left in the dry-run command just so you can see exactly what it is doing)

I have added some wallpapers I've collected (will probably add more as I go)

### **Keybinds**

<img src="/screens/tux.svg" alt="Tux" width="25" height="25" /> + Space = Launcher  
<img src="/screens/tux.svg" alt="Tux" width="25" height="25" /> + Q = Quit app  
<img src="/screens/tux.svg" alt="Tux" width="25" height="25" /> + T = Terminal (Ghostty as default)  
<img src="/screens/tux.svg" alt="Tux" width="25" height="25" /> + C = Open clipboard  
<img src="/screens/tux.svg" alt="Tux" width="25" height="25" /> + E = File Manager (Thunar is default)  
<img src="/screens/tux.svg" alt="Tux" width="25" height="25" /> + B = Browser (Zen is default)  
<img src="/screens/tux.svg" alt="Tux" width="25" height="25" /> + A = App Store (Cosmic is default)   
<img src="/screens/tux.svg" alt="Tux" width="25" height="25" /> + N = Refresh waybar  
<img src="/screens/tux.svg" alt="Tux" width="25" height="25" /> SHIFT + N = Launch waybar (used if waybar crashes)  
<img src="/screens/tux.svg" alt="Tux" width="25" height="25" /> SHIFT + W = Launch wallpaper selecter  

### Default Desktop
![image](/screens/desktop.png)

### Terminal
![image](/screens/term.png)

### **JaKoolIt** Wallpaper selector
![image](/screens/wall.png)

### Applauncher (rofi)
![image](/screens/appl.png)

### Powermenu (JaKoolIt)
![image](/screens/power.png)

### Install:
```bash
git clone https://github.com/daigonstar/hyprdots.git
cd hyprland-dots/hyprdots
chmod +x hyprinstall.sh
./hyprinstall.sh
```
The installer enables multilib (needed for Steam), auto-detects your GPU (AMD, NVIDIA or Intel) and installs the matching drivers from `gpu-<vendor>.txt`. Force the choice with `HYPR_GPU="amd nvidia" ./hyprinstall.sh`. Everything else is in `required.txt`. It also enables the needed services and optionally downloads the assistant's Ollama models (~19 GB).
### User settings
All options for the PC assistant, health monitor and popup calendar live in `~/.config/hypr/user_settings.toml` (the cog in the waybar drawer opens it).

Private values go in `~/.config/hypr/user_settings.local.toml` (git-ignored, created by the installer from `user_settings.local.toml.example`). To show Google Calendar events in the clock popup, copy your calendar's *Secret address in iCal format* (Google Calendar → Settings → your calendar → Integrate calendar) into `sources` there, then click the clock.

#### For my SDDM Greeter I use [SDDM Astronaut Theme](https://github.com/Keyitdev/sddm-astronaut-theme)
Please install that for a better greeter theme
