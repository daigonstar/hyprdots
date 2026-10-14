#!/usr/bin/env bash
# Show/hide the PC assistant as a scratchpad. The first press starts it; later presses
# toggle its special workspace, so the running chat (history, attachments) is kept.
# The assistant is optional: ~/.config/hypr/assistant/setup.sh turns it on or off.
class="com.hyprdots.assistant"
state="${XDG_STATE_HOME:-$HOME/.local/state}/hypr_agent"
assistant="$HOME/.config/hypr/assistant"

if [[ -e "$state/disabled" ]]; then
    notify-send -a "PC Assistant" "The assistant is turned off" "Run $assistant/setup.sh to enable it."
    exit 0
fi
if ! command -v ollama >/dev/null 2>&1 || ! python3 -c "import ollama" 2>/dev/null; then
    notify-send -a "PC Assistant" "The assistant is not set up" "Run $assistant/setup.sh to install it."
    exit 1
fi

if hyprctl clients | grep -q "class: $class\$"; then
    hyprctl dispatch 'hl.dsp.workspace.toggle_special("agent")'
else
    exec ghostty --class="$class" --title="Hyprland Assistant" -e python3 "$assistant/hypr_agent.py"
fi
