hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")
hl.env("WLR_DRM_DEVICES", "/dev/dri/card0")
hl.env("SDL_VIDEO_FULLSCREEN_HEAD", "0")
hl.env("QT_QPA_PLATFORM", "wayland")
hl.env("GDK_BACKEND", "wayland")
hl.env("PROTON_ENABLE_WAYLAND", "1")


-- ~/.local/bin on the PATH of everything Hyprland starts: Thunar's "Open Terminal Here" needs the
-- xfce4-mime-helper stand-in installed there (see scripts/exo-terminal.sh).
local home, path = os.getenv("HOME"), os.getenv("PATH") or ""
if home and not (":" .. path .. ":"):find(":" .. home .. "/.local/bin:", 1, true) then
    hl.env("PATH", home .. "/.local/bin:" .. path)
end
