#!/usr/bin/env bash
# Show/hide the PC assistant as a scratchpad. The first press starts it; later presses
# toggle its special workspace, so the running chat (history, attachments) is kept.
class="com.hyprdots.assistant"

if hyprctl clients | grep -q "class: $class\$"; then
    hyprctl dispatch 'hl.dsp.workspace.toggle_special("agent")'
else
    exec ghostty --class="$class" --title="Hyprland Assistant" -e "$HOME/.config/hypr/assistant/hypr_agent.py"
fi
