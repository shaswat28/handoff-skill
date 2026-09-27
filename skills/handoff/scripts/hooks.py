#!/usr/bin/env python3
"""Claude Code hooks that nudge you to run /handoff before a chat gets too long.

  hooks.py prompt [--window TOKENS] [--warn PCT,PCT,...]
      UserPromptSubmit. Warns once per chat per threshold, e.g. 45% ("cheapest
      point to start fresh") and 70% ("long chats get slower and less precise").
  hooks.py precompact
      PreCompact, registered with matcher "auto". Postpones the first automatic
      compaction in a chat once, so /handoff can still see the whole chat.

Messages go to the user only (systemMessage, or stderr on a block). Nothing is
added to the model's context, so the hooks cost no tokens. They run only when
Claude Code fires the event, take ~30 ms, and exit 0 on anything unexpected
so they can never break a session. install.sh / install.ps1 register them.
"""
import argparse
import json
import os
import sys
import time

DEFAULT_WINDOW = 200000
DEFAULT_WARN = "45,70"
TAIL_BYTES = 512 * 1024  # the last reply's usage is near the end of the log


def state_dir():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    d = os.path.join(base, "handoff-state")
    os.makedirs(d, exist_ok=True)
    return d


def seen(session_id, key):
    return os.path.exists(os.path.join(state_dir(), f"{session_id or 'unknown'}.{key}"))


def mark(session_id, key):
    d = state_dir()
    with open(os.path.join(d, f"{session_id or 'unknown'}.{key}"), "w") as f:
        f.write(str(time.time()))
    # Keep the folder small: drop markers older than a week.
    cutoff = time.time() - 7 * 86400
    for name in os.listdir(d):
        p = os.path.join(d, name)
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
        except OSError:
            pass


def context_tokens(transcript_path):
    """Tokens the model saw on its most recent reply, read from the log tail."""
    with open(transcript_path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - TAIL_BYTES))
        lines = f.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue  # includes the partial first line of the tail
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        u = (e.get("message") or {}).get("usage")
        if u:
            return (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0))
    return 0


def warning_text(pct, used, window, is_first, is_last):
    head = f"/handoff: this chat is at ~{used // 1000}k tokens ({used * 100 // window}% of context)."
    if is_last and not is_first:
        return (f"{head} Long chats get slower and less precise from here. "
                f"Recommended: run /handoff now and continue in a fresh chat.")
    if is_first and not is_last:
        return (f"{head} Cheapest point to start fresh: run /handoff and continue in a new chat "
                f"(every message re-sends the whole chat, so costs grow from here).")
    return f"{head} Good moment to run /handoff and continue in a fresh chat."


def on_prompt(data, args):
    levels = sorted({int(x) for x in args.warn.split(",") if x.strip().isdigit() and 0 < int(x) < 100})
    if not levels or args.window <= 0:
        return 0
    used = context_tokens(data.get("transcript_path") or "")
    sid = data.get("session_id")
    crossed = [p for p in levels if used >= args.window * p / 100]
    if not crossed:
        return 0
    top = crossed[-1]
    if seen(sid, f"warn{top}"):
        return 0
    for p in crossed:  # show only the highest; mark lower ones so they never fire late
        mark(sid, f"warn{p}")
    print(json.dumps({"systemMessage": warning_text(
        top, used, args.window, top == levels[0], top == levels[-1])}))
    return 0


def on_precompact(data, args):
    if data.get("trigger") == "manual":  # the matcher should already exclude /compact
        return 0
    sid = data.get("session_id")
    if seen(sid, "compact-postponed"):
        return 0
    mark(sid, "compact-postponed")
    sys.stderr.write(
        "/handoff: auto-compaction postponed once so you can run /handoff while the whole "
        "chat is still in context. Keep chatting instead and it will compact next time.\n")
    return 2  # exit 2 = skip this compaction


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("event", nargs="?", default="")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    ap.add_argument("--warn", default=DEFAULT_WARN)
    try:
        args = ap.parse_args()
        data = json.load(sys.stdin)
        handler = {"prompt": on_prompt, "precompact": on_precompact}.get(args.event)
        code = handler(data, args) if handler else 0
    except BaseException:  # includes argparse's SystemExit: never break the session
        code = 0
    sys.exit(code)


if __name__ == "__main__":
    main()
