# PC context for the assistant
<!-- Edit freely. This file is loaded into the agent's prompt on every request. Keep it short and factual. -->

## Hardware
- Hostname: teostra (desktop PC, not a laptop; no battery or backlight control)
- CPU: AMD Ryzen 9 7950X
- GPU: AMD Radeon RX 7700/7800 XT (amdgpu, ROCm for Ollama). There is NO Nvidia GPU.
- Monitors: DP-1 (primary) and DP-2 (disabled in SDDM only)
- Peripherals: Logitech receiver (Solaar), Corsair G915 TKL keyboard, Corsair MM800 mousepad, Corsair receiver

## Software
- OS: Arch Linux, Hyprland (Wayland, Lua config), SDDM login manager (its greeter runs on X11)
- AUR helper: paru. Update alias: `update` (paru -Syu && flatpak update)
- Terminal: ghostty. Bar: waybar. Notifications: swaync
- Dotfiles repo: ~/hyprdots, symlinked into ~/.config. Edit the repo, not copies.
- Local LLMs: Ollama (gpt-oss:20b for this agent, llava for screenshots)

## How to help
- The user wants diagnosis and clear explanations. Gather evidence with read-only commands first.
- Run read-only checks freely without asking. Anything that changes the system is shown to the user for approval first, including sudo, so propose changes directly and explain what they do.
- Do not run full system updates (paru -Syu) on your own initiative; tell the user when updates are pending instead.

## Known issues
- None recorded. TPM is intentionally disabled, so failed systemd-pcr*/systemd-tpm2-* units are expected; do not suggest enabling it.
