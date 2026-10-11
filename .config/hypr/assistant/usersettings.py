"""Loads user settings from user_settings.toml, overridden by user_settings.local.toml.

Both files live in ~/.config/hypr/. The .local file is git-ignored, so private
values (calendar links) never get committed. Missing or wrongly typed values
fall back to the defaults given by the caller.
"""
import os
import sys
import tomllib

HYPR_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SETTINGS_FILES = (
    os.path.join(HYPR_DIR, "user_settings.toml"),
    os.path.join(HYPR_DIR, "user_settings.local.toml"),
)


def _load_all():
    merged = {}
    for path in SETTINGS_FILES:
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            continue
        except (OSError, tomllib.TOMLDecodeError) as e:
            print(f"settings: ignoring {path}: {e}", file=sys.stderr)
            continue
        for name, values in data.items():
            if isinstance(values, dict):
                merged.setdefault(name, {}).update(values)
    return merged


def section(name, defaults):
    """Returns defaults overridden by [name] from the settings files."""
    result = dict(defaults)
    for key, value in _load_all().get(name, {}).items():
        if key not in defaults:
            print(f"settings: unknown key [{name}] {key}", file=sys.stderr)
            continue
        default = defaults[key]
        ok = isinstance(value, type(default))
        if isinstance(default, float) and isinstance(value, int) and not isinstance(value, bool):
            value, ok = float(value), True
        if isinstance(default, int) and isinstance(value, bool):
            ok = isinstance(default, bool)
        if ok:
            result[key] = value
        else:
            print(f"settings: [{name}] {key} should be {type(default).__name__}, using default", file=sys.stderr)
    return result
