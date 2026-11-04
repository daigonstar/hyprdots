#!/usr/bin/env bash
# SUPER + N and the settings pages: restart the bar, the notification centre, or (all) those and anything else that is down.
exec "$HOME/.config/hypr/scripts/desktop-services.sh" restart "${1:-all}"
