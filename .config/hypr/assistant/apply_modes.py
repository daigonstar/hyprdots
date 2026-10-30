#!/usr/bin/env python3
"""Adds assistant modes (/mode <name>) to hypr_agent.py.

Usage: python3 apply_modes.py [path/to/hypr_agent.py]     (default: ./hypr_agent.py)

All edits are checked first: every anchor must match exactly once, otherwise nothing is written.
A backup is saved next to the file as hypr_agent.py.pre-modes. Re-running is safe (it detects the patch).
"""
import py_compile
import shutil
import sys
from pathlib import Path

EDITS = []


def edit(old, new):
    EDITS.append((old, new))


# 1. import the modes module
edit(r'''import usersettings
SETTINGS = usersettings.section("assistant", {''',
     r'''import usersettings
import agent_modes
SETTINGS = usersettings.section("assistant", {''')

# 2. detect extra modes in private_modes/ (nothing happens if the folder is absent) and merge any feeds they bring
edit(r'''MEMORY_MAX_CHARS = SETTINGS["memory_max_chars"]''',
     r'''MEMORY_MAX_CHARS = SETTINGS["memory_max_chars"]
agent_modes.load_private(os.path.join(AGENT_DIR, "private_modes"))
NEWS_FEEDS.update(agent_modes.extra_feeds())''')

# 3. context: PC profile, health and image notes only where the mode uses them
edit(r'''    if profile:
        parts.append(f"USER'S PC PROFILE''',
     r'''    if profile and agent_modes.uses_profile():
        parts.append(f"USER'S PC PROFILE''')
edit(r'''    health = _read_text(HEALTH_FILE, 2000)
    if health:''',
     r'''    health = _read_text(HEALTH_FILE, 2000)
    if health and agent_modes.uses_pc_state():''')
edit(r'''    if IMAGE_NOTES:
        shown''',
     r'''    if IMAGE_NOTES and agent_modes.uses_pc_state():
        shown''')

# 4. the system prompt depends on the mode
edit(r"""'content': SYSTEM_PROMPT + f""",
     r"""'content': agent_modes.system_prompt(SYSTEM_PROMPT) + f""")

# 5. window and product guidance only make sense in local mode
edit(r'''    if "focus" in user_input.lower() or "windows" in user_input.lower():''',
     r'''    if agent_modes.is_local() and ("focus" in user_input.lower() or "windows" in user_input.lower()):''')
edit(r'''    if re.search(r"\b(this|that|it|its''',
     r'''    if agent_modes.is_local() and re.search(r"\b(this|that|it|its''')
edit(r'''    if PRODUCT_RE.search(user_input) and not PC_PROBLEM_RE.search(user_input):''',
     r'''    if agent_modes.is_local() and PRODUCT_RE.search(user_input) and not PC_PROBLEM_RE.search(user_input):''')

# 6. only the mode's tools are offered, and only they can run
edit(r'''response = _ask(messages, user_input, tools=TOOL_SCHEMAS, reason=True)''',
     r'''response = _ask(messages, user_input, tools=agent_modes.schemas(TOOL_SCHEMAS), reason=True)''')
edit(r'''def execute_tool(name, arg):
    try:
        return tools[name]()''',
     r'''def execute_tool(name, arg):
    if not agent_modes.allowed(name):
        return f"Tool '{name}' is not available in /mode {agent_modes.name()}. Use only the tools you were given, or tell the user to type /mode local."
    try:
        return tools[name]()''')

# 7. per-mode tool budgets
edit(r'''        cap = TOOL_CAPS.get(name)''',
     r'''        cap = agent_modes.caps(TOOL_CAPS).get(name)''')

# 8. the /mode command
edit(r'''PASTE_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "hypr_agent_paste")''',
     r'''def cmd_mode(arg=""):
    """/mode shows the modes; /mode <name> [option] switches and stays switched, like /allow."""
    text, cleared, switched = agent_modes.switch(arg, HISTORY)
    if cleared and SESSION_FILE[0]:
        try:
            open(SESSION_FILE[0], "w").close()  # the old mode's turns must not reach the new one
        except OSError:
            pass
    if switched:
        extra = agent_modes.activate(sys.modules[__name__])
        if extra:
            text += "\n\n" + extra
    return text

PASTE_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "hypr_agent_paste")''')
edit(r'''    "help": (cmd_help, "List slash commands", "36"),''',
     r'''    "help": (cmd_help, "List slash commands", "36"),
    "mode": (cmd_mode, "Switch assistant mode and keep it (type /mode to see them)", "36"),''')
edit(r'''SLASH_ARGS = {"think": ["on", "off"], "effort": list(THINK_EFFORTS)}''',
     r'''SLASH_ARGS = {"think": ["on", "off"], "effort": list(THINK_EFFORTS), "mode": agent_modes.completions()}''')
# options such as "mode gaming" or "mode <name> <option>" contain a space, so Tab must still match them
edit(r'''if " " not in partial and choice.startswith(partial.lower()):''',
     r'''if choice.startswith(partial.lower()):''')

# 9. show the mode in the prompt and the status bar
edit(r'''def prompt_glyph():
    if AUTO_APPROVE[0]:
        return f"{_c('1;33', '⚡')}{_c('1;' + theme_code(0), '❯')} "
    return f"{_c('1;' + theme_code(0), '❯')} "''',
     r'''def prompt_glyph():
    badge = "" if agent_modes.is_local() else f"{_c('1;' + agent_modes.colour(), '[' + agent_modes.name() + ']')} "
    if AUTO_APPROVE[0]:
        return badge + f"{_c('1;33', '⚡')}{_c('1;' + theme_code(0), '❯')} "
    return badge + f"{_c('1;' + theme_code(0), '❯')} "''')
edit(r'''    return f" {approvals}  {sep}  {reasoning}  {sep}  {dim('type / for commands')}"''',
     r'''    mode = _c(agent_modes.colour(), "mode: " + agent_modes.describe())
    return f" {mode}  {sep}  {approvals}  {sep}  {reasoning}  {sep}  {dim('type / for commands')}"''')


def main():
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "hypr_agent.py").expanduser()
    if not target.is_file():
        sys.exit(f"Not found: {target}")
    source = target.read_text(encoding="utf-8")
    if "import agent_modes" in source:
        sys.exit("hypr_agent.py already has the modes patch; nothing to do.")
    if not (target.parent / "agent_modes.py").is_file():
        sys.exit(f"Put agent_modes.py in {target.parent} first.")
    patched, problems = source, []
    for number, (old, new) in enumerate(EDITS, 1):
        found = patched.count(old)
        if found != 1:
            problems.append(f"edit {number}: anchor matched {found} times: {old.strip().splitlines()[0][:80]!r}")
            continue
        patched = patched.replace(old, new)
    if problems:
        sys.exit("Nothing was changed. The file differs from the version this patch was written for:\n  " + "\n  ".join(problems))
    backup = target.with_name(target.name + ".pre-modes")
    shutil.copy2(target, backup)
    target.write_text(patched, encoding="utf-8")
    try:
        py_compile.compile(str(target), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(backup, target)
        sys.exit(f"The patched file did not compile, so the original was restored: {e}")
    print(f"Patched {target} ({len(EDITS)} edits). Backup: {backup}")
    ignore = target.parent / ".gitignore"
    if ignore.is_file():
        lines = ignore.read_text(encoding="utf-8").splitlines()
        if "private_modes/" not in lines:
            ignore.write_text("\n".join(lines + ["private_modes/"]) + "\n", encoding="utf-8")
            print("Added private_modes/ to .gitignore so private modes are never committed.")
    else:
        print("Add `private_modes/` to your .gitignore so private mode files are never committed.")


if __name__ == "__main__":
    main()
