#!/usr/bin/env bash
# Waybar update indicator: pending official (checkupdates), AUR (paru) and Flatpak updates.
# Prints JSON for waybar; always shows the icon. Class: "updated" (0), "pending" (1-49, orange), "critical" (50+, red).

official=$(checkupdates 2>/dev/null | wc -l)
aur=$(paru -Qua 2>/dev/null | wc -l)
flat=$(flatpak remote-ls --updates 2>/dev/null | wc -l)
total=$((official + aur + flat))

if [[ "$total" -eq 0 ]]; then
    printf '{"text": "󰏔", "class": "updated", "tooltip": "System is up to date"}\n'
else
    class="pending"
    [[ "$total" -ge 50 ]] && class="critical"
    printf '{"text": "󰏔 %s", "class": "%s", "tooltip": "Official: %s\\nAUR: %s\\nFlatpak: %s\\n\\nClick to update"}\n' \
        "$total" "$class" "$official" "$aur" "$flat"
fi
