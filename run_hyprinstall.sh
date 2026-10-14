#!/usr/bin/env bash
# Wrapper for hyprinstall.sh
# Accepts same flags: --dry-run, --verbose
# Forward all arguments to hyprinstall.sh

# Ensure hyprinstall.sh is executable
chmod +x hyprinstall.sh

# Run hyprinstall.sh with forwarded args
bash hyprinstall.sh "$@"
