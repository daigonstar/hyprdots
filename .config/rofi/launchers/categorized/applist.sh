#!/usr/bin/env bash
#
## Shared app-scanning library for the categorized rofi launcher.
## Sourced by both launcher.sh (to know which categories are non-empty)
## and category-mode.sh (the rofi script-mode executable that lists apps
## for a given category and launches the selected one).
##
## Performance note: rofi's mode-switcher calls EVERY configured modi
## script once up front (to build the tab bar), not just the active tab.
## With ~10 categories, a naive per-file bash/awk/grep scan (~1s each)
## meant ~10s before the launcher became visible. To fix this:
##   1. The whole desktop-file scan is done in a single gawk process
##      (one process for all files, instead of ~10 subprocess forks per
##      file), cutting a cold scan down to well under 100ms.
##   2. Results are cached to a file. The cache is considered fresh as
##      long as no watched applications directory has a newer mtime than
##      the cache (directory mtime changes whenever a .desktop file is
##      added/removed), so newly installed apps still show up on the very
##      next launcher open without needing a manual refresh.

CACHE_FILE="${XDG_CACHE_HOME:-$HOME/.cache}/rofi-categorized-apps.cache"

BUCKET_ORDER=(Internet Development Multimedia Graphics Games Office System Settings Utility Other)

# Populates the following globals (name-keyed, i.e. the app's display Name
# is the key - fine for a desktop launcher, collisions just keep the first
# hit found, and user-installed dirs are scanned before system ones):
#   APP_ID[name]     -> desktop file id (without .desktop), for gtk-launch
#   APP_ICON[name]   -> Icon= value (theme name or absolute path)
#   APP_BUCKET[name] -> assigned bucket
declare -gA APP_ID=()
declare -gA APP_ICON=()
declare -gA APP_BUCKET=()

_app_dirs() {
    local app_dirs=("$HOME/.local/share/applications")
    local xdg_dirs=()
    IFS=':' read -ra xdg_dirs <<< "${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
    local d
    for d in "${xdg_dirs[@]}"; do
        app_dirs+=("$d/applications")
    done
    printf '%s\n' "${app_dirs[@]}"
}

# Newest mtime (epoch seconds) among all existing app directories. Used to
# decide whether the cache is stale (a dir's mtime bumps whenever a file is
# added/removed/renamed inside it).
_app_dirs_newest_mtime() {
    local newest=0 d m
    while IFS= read -r d; do
        [[ -d "$d" ]] || continue
        m="$(stat -c %Y "$d" 2>/dev/null || echo 0)"
        (( m > newest )) && newest=$m
    done < <(_app_dirs)
    echo "$newest"
}

_scan_apps_awk() {
    local files=()
    while IFS= read -r adir; do
        [[ -d "$adir" ]] || continue
        while IFS= read -r -d '' f; do
            files+=("$f")
        done < <(find "$adir" -maxdepth 1 -name '*.desktop' -print0 2>/dev/null)
    done < <(_app_dirs)

    [[ "${#files[@]}" -eq 0 ]] && return

    gawk '
        BEGIN {
            split("Network WebBrowser Email Chat InstantMessaging News RemoteAccess P2P FileTransfer VideoConference Feed", a, " "); for (i in a) cat2bucket[a[i]] = "Internet"
            split("Development IDE Building Debugger GUIDesigner Profiling RevisionControl Translation ProjectManagement", a, " "); for (i in a) cat2bucket[a[i]] = "Development"
            split("AudioVideo Audio Video Player Recorder DiscBurning Music TV Mixer Sequencer", a, " "); for (i in a) cat2bucket[a[i]] = "Multimedia"
            split("Graphics 2DGraphics 3DGraphics VectorGraphics RasterGraphics Photography Scanning Viewer", a, " "); for (i in a) cat2bucket[a[i]] = "Graphics"
            split("Game ActionGame AdventureGame ArcadeGame BoardGame CardGame PuzzleGame StrategyGame SimulationGame SportsGame LogicGame Emulator", a, " "); for (i in a) cat2bucket[a[i]] = "Games"
            split("Office WordProcessor Spreadsheet Presentation Calendar ContactManagement Database Chart Finance Dictionary", a, " "); for (i in a) cat2bucket[a[i]] = "Office"
            split("System Filesystem Monitor TerminalEmulator ConsoleOnly Security", a, " "); for (i in a) cat2bucket[a[i]] = "System"
            split("Settings DesktopSettings HardwareSettings PackageManager", a, " "); for (i in a) cat2bucket[a[i]] = "Settings"
            split("Utility Accessibility Archiving Compression FileTools FileManager TextEditor TextTools Calculator Clock", a, " "); for (i in a) cat2bucket[a[i]] = "Utility"

            # Preference order when an app lists multiple categories that
            # map to different buckets (e.g. Steam ships
            # "Network;FileTransfer;Game;" - Game is far more useful than
            # the generic Network bucket it happens to list first).
            split("Games Development Graphics Multimedia Office Internet Settings System Utility", prio, " ")
        }
        FNR == 1 {
            in_entry = 0; name = ""; icon = ""; categories = ""
            no_display = ""; hidden = ""; type_val = ""
            n = split(FILENAME, parts, "/")
            id = parts[n]
            sub(/\.desktop$/, "", id)
        }
        /^\[Desktop Entry\]/ { in_entry = 1; next }
        /^\[/ { in_entry = 0 }
        in_entry && /^NoDisplay=/  { no_display = substr($0, 11) }
        in_entry && /^Hidden=/     { hidden = substr($0, 8) }
        in_entry && /^Type=/       { type_val = substr($0, 6) }
        in_entry && /^Name=/ && name == ""       { name = substr($0, 6) }
        in_entry && /^Icon=/ && icon == ""       { icon = substr($0, 6) }
        in_entry && /^Categories=/ && categories == "" { categories = substr($0, 12) }
        ENDFILE {
            valid = 1
            if (id in seen) valid = 0
            seen[id] = 1
            if (valid && (no_display == "true" || hidden == "true")) valid = 0
            if (valid && type_val != "" && type_val != "Application") valid = 0
            if (valid && name == "") valid = 0

            if (valid) {
                if (icon == "") icon = "application-x-executable"

                delete matched
                m = split(categories, cats, ";")
                for (i = 1; i <= m; i++) {
                    c = cats[i]
                    if (c == "") continue
                    if (c in cat2bucket) matched[cat2bucket[c]] = 1
                }
                bucket = ""
                for (i = 1; i <= 9; i++) {
                    p = prio[i]
                    if (p in matched) { bucket = p; break }
                }
                if (bucket == "") bucket = "Other"

                print bucket "\x1f" name "\x1f" icon "\x1f" id
            }
        }
    ' "${files[@]}"
}

# Populate APP_ID/APP_ICON/APP_BUCKET, either from a fresh cache file or by
# rescanning (and rewriting the cache) if any app directory changed since.
scan_apps() {
    [[ "${APP_SCAN_DONE:-0}" == "1" ]] && return
    APP_SCAN_DONE=1

    local newest_dir_mtime cache_mtime=-1
    newest_dir_mtime="$(_app_dirs_newest_mtime)"
    if [[ -f "$CACHE_FILE" ]]; then
        cache_mtime="$(stat -c %Y "$CACHE_FILE" 2>/dev/null || echo -1)"
    fi

    if [[ ! -f "$CACHE_FILE" || "$cache_mtime" -lt "$newest_dir_mtime" ]]; then
        mkdir -p "$(dirname "$CACHE_FILE")"
        _scan_apps_awk > "$CACHE_FILE.tmp" && mv "$CACHE_FILE.tmp" "$CACHE_FILE"
    fi

    local bucket name icon id
    while IFS=$'\x1f' read -r bucket name icon id; do
        [[ -z "$name" ]] && continue
        APP_ID[$name]="$id"
        APP_ICON[$name]="$icon"
        APP_BUCKET[$name]="$bucket"
    done < "$CACHE_FILE"
}

# print_nonempty_buckets: one bucket name per line, in BUCKET_ORDER, skipping
# empty ones, followed by "All Apps" if there is at least one app total.
print_nonempty_buckets() {
    scan_apps
    local bucket name count
    for bucket in "${BUCKET_ORDER[@]}"; do
        count=0
        for name in "${!APP_BUCKET[@]}"; do
            [[ "${APP_BUCKET[$name]}" == "$bucket" ]] && ((count++))
        done
        [[ "$count" -gt 0 ]] && echo "$bucket"
    done
    [[ "${#APP_ID[@]}" -gt 0 ]] && echo "All Apps"
}

# print_rofi_entries_for_bucket BUCKET: emits rofi script-mode formatted
# rows (name + icon + info=desktop-id) for every app in that bucket,
# sorted alphabetically. BUCKET="All Apps" lists everything.
print_rofi_entries_for_bucket() {
    scan_apps
    local bucket="$1" name
    for name in "${!APP_BUCKET[@]}"; do
        if [[ "$bucket" != "All Apps" && "${APP_BUCKET[$name]}" != "$bucket" ]]; then
            continue
        fi
        printf '%s\0icon\x1f%s\x1finfo\x1f%s\n' "$name" "${APP_ICON[$name]:-application-x-executable}" "${APP_ID[$name]}"
    done | sort
}
