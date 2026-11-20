#!/usr/bin/env python3
"""Add or remove the /handoff hooks in a Claude Code settings.json.

  hooks_install.py install   [--settings PATH] [--window N] [--warn 45,70] [--notify] [--no-compact-hold]
  hooks_install.py uninstall [--settings PATH]

Idempotent: existing /handoff entries are replaced, never duplicated, and every
other setting and hook is left untouched. The first settings backup is saved
alongside the settings file as settings.json.handoff-bak. On Windows the hooks
use the Python that ran the installer. On POSIX they use scripts/py.
"""
import argparse
import json
import os
import shutil
import sys

HOOKS_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hooks.py")
MARKER = "handoff/scripts/hooks.py"  # identifies our entries in settings.json
WRAPPER_MARKER = 'handoff/scripts/py" hooks.py '


def slash(p):
    # Forward slashes work in every shell Claude Code may run hooks with,
    # including on Windows, and avoid JSON/shell backslash escaping.
    return p.replace("\\", "/")


def command(event, extra=""):
    if os.name != "nt":
        wrapper = os.path.join(os.path.dirname(HOOKS_PY), "py")
        for char in ('\\', '"', '$', '`'):
            wrapper = wrapper.replace(char, '\\' + char)
        return f'sh "{wrapper}" hooks.py {event}{extra}'
    # Keep quotes and cmd.exe expansion characters out of the Python literal.
    path = slash(HOOKS_PY).translate(str.maketrans({
        "'": r"\x27", '"': r"\x22", "%": r"\x25", "!": r"\x21",
    }))
    loader = (f"import os,runpy,sys;p='{path}';sys.argv=[p]+sys.argv[1:];"
              "os.path.isfile(p) and runpy.run_path(p,run_name='__main__')")
    return f'"{slash(sys.executable)}" -c "{loader}" {event}{extra}'


def strip_ours(hooks):
    """Remove every hook entry whose command points at our hooks.py."""
    for event in list(hooks):
        groups = []
        for g in hooks[event]:
            kept = [h for h in g.get("hooks", [])
                    if not any(marker in slash(h.get("command", "") if isinstance(h.get("command", ""), str) else "")
                               for marker in (MARKER, WRAPPER_MARKER))]
            if kept:
                groups.append({**g, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["install", "uninstall"])
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    ap.add_argument("--settings", default=os.path.join(base, "settings.json"))
    ap.add_argument("--window", type=int, default=200000, help="context window in tokens")
    ap.add_argument("--warn", default="45,70", help="warning thresholds, percent of window")
    ap.add_argument("--notify", action="store_true", help="also show macOS notifications for warnings")
    ap.add_argument("--no-compact-hold", action="store_true",
                    help="don't postpone the first auto-compaction")
    args = ap.parse_args()
    parts = args.warn.split(",")
    if not all(p.strip().isdigit() and 0 < int(p) < 100 for p in parts) or args.window <= 0:
        print("hooks: --warn must be percentages between 1 and 99 like 45,70, and --window > 0")
        return 2
    args.warn = ",".join(str(int(p)) for p in parts)

    path = os.path.realpath(args.settings)
    exists = os.path.exists(path)
    if args.action == "uninstall" and not exists:
        return 0

    settings = {}
    if exists:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            settings = json.loads(text) if text.strip() else {}
        except ValueError as ex:
            print(f"hooks: {args.settings} is not valid JSON ({ex}); left unchanged, hooks not installed.")
            return 1
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        print(f"hooks: {args.settings} and its 'hooks' field must be JSON objects. Left unchanged.")
        return 1

    hooks = settings.setdefault("hooks", {})
    strip_ours(hooks)
    if args.action == "install":
        extra = f" --window {args.window} --warn {args.warn}"
        if args.notify:
            extra += " --notify"
        hooks.setdefault("UserPromptSubmit", []).append({"hooks": [{
            "type": "command",
            "command": command("prompt", extra)}]})
        if not args.no_compact_hold:
            hooks.setdefault("PreCompact", []).append({"matcher": "auto", "hooks": [{
                "type": "command", "command": command("precompact")}]})
    if not hooks:
        del settings["hooks"]

    backup = args.settings + ".handoff-bak"
    if exists and not os.path.lexists(backup):
        shutil.copy2(path, backup)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)

    if args.action == "install":
        pcts = ", ".join(f"{p}%" for p in args.warn.split(","))
        print(f"hooks: warnings at {pcts} of a {args.window:,}-token window; "
              f"compaction hold {'off' if args.no_compact_hold else 'on'} -> {args.settings}")
    else:
        print(f"hooks: removed from {args.settings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
