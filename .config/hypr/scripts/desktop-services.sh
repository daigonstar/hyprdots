#!/usr/bin/env bash
# The parts of the desktop that must stay running, as systemd user services: they come back by themselves after a
# crash and log to the journal (journalctl --user -u waybar). The units are in ~/.config/hypr/systemd.
#   desktop-services.sh login               from autostart.lua: everything up, with Hyprland's environment
#   desktop-services.sh start               after an update, from any terminal: the same, keeping the environment
#   desktop-services.sh restart [all|waybar|swaync]
#   desktop-services.sh failed <unit>       a part crashed too often and systemd gave up on it: tell the user
PARTS=(waybar swaync hypridle hyprdots-tray hyprdots-usb)
UNITS="$HOME/.config/hypr/systemd"
USER_DIR="$HOME/.config/systemd/user"

install_units() {
    mkdir -p "$USER_DIR"
    local item
    for item in "$UNITS"/*; do
        ln -sfn "$item" "$USER_DIR/$(basename "$item")"
    done
    systemctl --user daemon-reload
}

import_session() {
    # Everything Hyprland was given, so a bar or tray in a service, and apps opened from them, see the same as before.
    # Only from autostart: from a terminal this would pass on that terminal's environment too.
    local names
    names=$(compgen -e | grep -vE '^(_|SHLVL|PWD|OLDPWD|LD_PRELOAD|INVOCATION_ID|JOURNAL_STREAM|NOTIFY_SOCKET|MANAGERPID|MANAGERPIDFDID|SYSTEMD_EXEC_PID|LISTEN_.*)$')
    # shellcheck disable=SC2086
    systemctl --user import-environment $names
    # shellcheck disable=SC2086
    dbus-update-activation-environment --systemd $names 2>/dev/null
}

stop_strays() {
    # Copies started outside the services (an older version of these dots) would fight the new ones
    systemctl --user -q is-active waybar || pkill -x waybar
    systemctl --user -q is-active swaync || pkill -x swaync
    systemctl --user -q is-active hypridle || pkill -x hypridle
    systemctl --user -q is-active hyprdots-tray || pkill -f '^python3? .*[h]ypr/tray/quick_tray'
    systemctl --user -q is-active hyprdots-usb || pkill -f '[u]diskie -c'
    sleep 0.3
}

units_of() { local p; for p in "${PARTS[@]}"; do echo "$p.service"; done; }

case "${1:-}" in
    login|start)
        install_units
        [[ "$1" == login ]] && import_session
        systemctl --user start hyprdots-session.target
        stop_strays
        # shellcheck disable=SC2046
        systemctl --user reset-failed $(units_of) 2>/dev/null
        systemctl --user reset-failed 'hyprdots-part-failed@*' 2>/dev/null
        # restart, not start: a new login replaces anything left from the last one, with this session's settings
        # shellcheck disable=SC2046
        systemctl --user restart $(units_of)
        ;;
    restart)
        install_units
        case "${2:-all}" in
            waybar) systemctl --user reset-failed waybar.service 2>/dev/null
                    systemctl --user restart waybar.service ;;
            swaync) systemctl --user reset-failed swaync.service hyprdots-tray.service 2>/dev/null
                    systemctl --user restart swaync.service
                    systemctl --user start hyprdots-tray.service ;;  # it follows swaync back by itself if still running
            *)      stop_strays
                    # shellcheck disable=SC2046
                    systemctl --user reset-failed $(units_of) 2>/dev/null
                    systemctl --user reset-failed 'hyprdots-part-failed@*' 2>/dev/null
                    systemctl --user restart waybar.service swaync.service
                    # shellcheck disable=SC2046
                    systemctl --user start $(units_of) ;;
        esac
        ;;
    failed)
        # systemd calls this after every crash; only tell the user when it has stopped trying
        systemctl --user -q is-failed "${2:-}" || exit 0
        message="${2:-A desktop part} keeps crashing and was not restarted again. Press SUPER + N to try again; the log is in: journalctl --user -u ${2:-}"
        # The failed part may be the notification daemon itself
        timeout 3 notify-send -u critical "Desktop problem" "$message" || hyprctl notify 3 20000 0 "$message" || true
        ;;
    *)
        echo "usage: $0 login | start | restart [all|waybar|swaync] | failed <unit>" >&2
        exit 2
        ;;
esac
