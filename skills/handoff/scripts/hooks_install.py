#!/usr/bin/env python3
"""Add or remove the /handoff hooks in a Claude Code settings.json.

  hooks_install.py install   [--settings PATH] [--window N] [--warn 45,70] [--no-compact-hold]
  hooks_install.py uninstall [--settings PATH]

Idempotent: existing /handoff entries are replaced, never duplicated, and every
other setting and hook is left untouched. The previous file is backed up next
to it as settings.json.handoff-bak. The hook command uses the absolute path of
the Python running this script, so it works from bash, zsh, cmd or PowerShell;
re-run the installer if that Python is moved or uninstalled.
"""
import argparse
import json
import os
import shutil
import sys

HOOKS_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hooks.py")
MARKER = "handoff/scripts/hooks.py"  # identifies our entries in settings.json


def slash(p):
    # Forward slashes work in every shell Claude Code may run hooks with,
    # including on Windows, and avoid JSON/shell backslash escaping.
    return p.replace("\\", "/")


def command(event, extra=""):
    return f'"{slash(sys.executable)}" "{slash(HOOKS_PY)}" {event}{extra}'


def strip_ours(hooks):
    """Remove every hook entry whose command points at our hooks.py."""
    for event in list(hooks):
        groups = []
        for g in hooks[event]:
            kept = [h for h in g.get("hooks", []) if MARKER not in slash(h.get("command", ""))]
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
    ap.add_argument("--no-compact-hold", action="store_true",
                    help="don't postpone the first auto-compaction")
    args = ap.parse_args()
    parts = args.warn.split(",")
    if not all(p.strip().isdigit() and 0 < int(p) < 100 for p in parts) or args.window <= 0:
        print("hooks: --warn must be percentages between 1 and 99 like 45,70, and --window > 0")
        return 2
    args.warn = ",".join(str(int(p)) for p in parts)

    settings = {}
    if os.path.exists(args.settings):
        try:
            with open(args.settings, encoding="utf-8") as f:
                text = f.read()
            settings = json.loads(text) if text.strip() else {}
        except ValueError as ex:
            print(f"hooks: {args.settings} is not valid JSON ({ex}); left unchanged, hooks not installed.")
            return 1
        shutil.copy2(args.settings, args.settings + ".handoff-bak")

    hooks = settings.setdefault("hooks", {})
    strip_ours(hooks)
    if args.action == "install":
        hooks.setdefault("UserPromptSubmit", []).append({"hooks": [{
            "type": "command",
            "command": command("prompt", f" --window {args.window} --warn {args.warn}")}]})
        if not args.no_compact_hold:
            hooks.setdefault("PreCompact", []).append({"matcher": "auto", "hooks": [{
                "type": "command", "command": command("precompact")}]})
    if not hooks:
        del settings["hooks"]

    os.makedirs(os.path.dirname(os.path.abspath(args.settings)), exist_ok=True)
    tmp = args.settings + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(tmp, args.settings)

    if args.action == "install":
        pcts = ", ".join(f"{p}%" for p in args.warn.split(","))
        print(f"hooks: warnings at {pcts} of a {args.window:,}-token window; "
              f"compaction hold {'off' if args.no_compact_hold else 'on'} -> {args.settings}")
    else:
        print(f"hooks: removed from {args.settings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
