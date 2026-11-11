#!/usr/bin/env bash
# Opens or closes the notes window (Super+I). It runs as a service (hyprdots-notes), so it opens at once; this asks it to
# show or hide, and starts it first if it is not running.
#   notes.sh                toggle
#   notes.sh --append TEXT  add a line to the Inbox tab, with or without the window open
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ "${1:-}" == "--append" ]]; then
    shift
    exec python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import notebook; print(notebook.Notebook().append(" ".join(sys.argv[2:])))' "$dir" "$@"
fi
# The Rust build (hyprdots-notes) or notes.py, whichever start.sh ran. One pkill: each one reads every process
signal_it() { pkill -USR1 -f '^[^ ]*/[h]yprdots-notes$|[h]ypr/notes/notes\.py'; }
signal_it && exit 0
# Not running: start it (as the service when the desktop runs them), and ask once it is listening
if systemctl --user cat hyprdots-notes.service >/dev/null 2>&1; then
    systemctl --user start hyprdots-notes.service
else
    LD_PRELOAD="/usr/lib/libgtk4-layer-shell.so${LD_PRELOAD:+:$LD_PRELOAD}" setsid "$dir/start.sh" >/dev/null 2>&1 </dev/null &
fi
for _ in $(seq 50); do
    [[ -e "${XDG_RUNTIME_DIR:-/tmp}/hyprdots-notes.ready" ]] && signal_it && exit 0
    sleep 0.1
done
notify-send -a Notes "Notes did not start" "See: journalctl --user -u hyprdots-notes"
