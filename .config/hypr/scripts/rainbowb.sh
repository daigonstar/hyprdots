#!/bin/bash
# /* ---- 💫 https://github.com/JaKooLit 💫 ---- */  ##
# for rainbow borders animation

function random_hex() {
    printf '"rgba(%06xff)"' $((RANDOM % 16777216))
}

# hyprctl's legacy `keyword` command no longer works under the Lua config
# parser ("keyword can't work with non-legacy parsers. Use eval."), so the
# gradient is applied via hl.config() through `hyprctl eval` instead.
colors="$(random_hex)"
for _ in $(seq 1 9); do
    colors+=", $(random_hex)"
done

# rainbow colors only for active window
hyprctl eval "hl.config({ general = { col = { active_border = { colors = { ${colors} }, angle = 270 } } } })"

# rainbow colors for inactive window (uncomment to take effect)
#hyprctl eval "hl.config({ general = { col = { inactive_border = { colors = { ${colors} }, angle = 270 } } } })"

