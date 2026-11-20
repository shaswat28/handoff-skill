#!/usr/bin/env python3
"""Token-cheap context digests for the /handoff skill.

  digest.py context    [--session ID] [--cwd DIR]   git + markdown + session index
  digest.py transcript [--session ID] [--cwd DIR] [--budget CHARS]
                                                    condensed chat log

Every section is size-capped and failures are reported inline. The script
always exits 0: a non-zero exit from a skill's !`command` injection aborts
the whole /handoff invocation.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import deque
from datetime import datetime
from pathlib import Path

HANDOFF_NAME = "handoff.md"
HANDOFF_DIR = ".handoff"
KEY_DOCS = ["CLAUDE.md", "AGENTS.md", "README.md", "DESIGN.md", "TODO.md",
            "CHANGELOG.md", "CONTRIBUTING.md", HANDOFF_NAME]
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Harness-injected pseudo-prompts that are not things the human typed.
NOISE_PREFIXES = ("<system-reminder>", "<local-command-stdout>", "<local-command-stderr>",
                  "<command-message>", "Caveat:", "[Request interrupted",
                  "<task-notification>", "<bash-input>", "<bash-stdout>",
                  "<bash-stderr>", "<ci-monitor-event>")


# ---------------------------------------------------------------- helpers

def git(args, cwd, limit=None):
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                             encoding="utf-8", errors="replace", timeout=30).stdout
    except Exception:
        return ""
    out = out.rstrip("\n")
    if limit is not None:
        lines = out.splitlines()
        if len(lines) > limit:
            out = "\n".join(lines[:limit] + [f"... ({len(lines) - limit} more lines cut)"])
    return out


def clip(text, n):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def section(title, body):
    body = body.strip("\n").rstrip() if body else ""
    print(f"\n### {title}\n")
    print(body if body else "(none)")


def display_path(f, cwd):
    try:
        if os.path.commonpath([cwd, os.path.abspath(f)]) == cwd:
            return os.path.relpath(f, cwd)
    except ValueError:
        pass
    return f


# ------------------------------------------------------------ transcripts

def projects_dir():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "projects")


def encode_cwd(cwd):
    # Claude Code names the per-project folder after the cwd with every
    # non-alphanumeric character replaced by "-" (/a/b.c -> -a-b-c).
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def resolved_session_id(session_id):
    sid = (session_id or "").strip()
    return sid if "$" not in sid and "{" not in sid else ""


def find_transcript(session_id, cwd):
    root = projects_dir()
    sid = resolved_session_id(session_id)
    if sid:
        hits = glob.glob(os.path.join(root, "*", f"{sid}.jsonl"))
        if hits:
            return max(hits, key=os.path.getmtime)
    # Fallback: newest transcript for this cwd (the running session is the
    # one being written to right now, so it is the most recently modified).
    hits = glob.glob(os.path.join(root, encode_cwd(cwd), "*.jsonl"))
    return max(hits, key=os.path.getmtime) if hits else None


def load_entries(path):
    entries = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get("type") in ("user", "assistant", "system"):
                    entries.append(entry)
            except ValueError:
                continue
    return entries


def blocks(entry):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def is_compaction(entry):
    # Best-effort: marker names come from observed transcripts, not a spec.
    # A compaction writes a boundary *and* a summary message; count the boundary,
    # falling back to the summary only for logs that lack boundaries.
    return entry.get("type") == "system" and entry.get("subtype") == "compact_boundary"


def human_prompt(entry):
    """Text the human typed, or None for tool results / injected messages."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain") \
            or entry.get("isCompactSummary"):
        return None
    if (entry.get("origin") or {}).get("kind") not in (None, "human"):
        return None
    content = (entry.get("message") or {}).get("content")
    texts = [b.get("text", "") for b in blocks(entry) if b.get("type") == "text"]
    if not texts or any(b.get("type") == "tool_result" for b in blocks(entry)):
        return None
    texts = [t for t in texts if t.strip() and
             (isinstance(content, str) or not t.strip().startswith(NOISE_PREFIXES))]
    text = "\n".join(texts).strip()
    m = re.search(r"<command-name>(.*?)</command-name>", text)
    if m:
        args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
        return f"{m.group(1)} {args.group(1).strip() if args else ''}".strip()
    if not text:
        return None
    while text.startswith("<system-reminder>") and "</system-reminder>" in text:
        text = text.split("</system-reminder>", 1)[1].lstrip()
    if not text or text.startswith(NOISE_PREFIXES):
        return None
    return text


def tool_label(block):
    name = block.get("name", "?")
    inp = block.get("input") or {}
    target = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") \
        or inp.get("command") or inp.get("pattern") or inp.get("url") \
        or inp.get("description") or ""
    return f"{name} {clip(target, 120)}".strip()


def result_text(block):
    c = block.get("content")
    if isinstance(c, list):
        c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
    return str(c or "")


def session_index(entries):
    prompts, edited, errors, compactions, summaries = [], {}, [], 0, 0
    recent_text, recent_tools = deque(maxlen=3), deque(maxlen=10)
    has_boundary = any(is_compaction(e) for e in entries if not e.get("isSidechain"))
    tool_names = {}
    first_ts = None
    for e in entries:
        if e.get("isSidechain"):
            continue
        first_ts = first_ts or e.get("timestamp")
        boundary = is_compaction(e)
        summary = bool(e.get("isCompactSummary"))
        compactions += boundary
        summaries += summary
        if boundary or (summary and not has_boundary):
            recent_text.clear()
            recent_tools.clear()
        p = human_prompt(e)
        if p:
            prompts.append(p)
        for b in blocks(e):
            if b.get("type") == "tool_use":
                label = tool_label(b)
                tool_names[b.get("id")] = label
                if e.get("type") == "assistant":
                    recent_tools.append(label)
                inp = b.get("input") or {}
                path = inp.get("file_path") or inp.get("notebook_path")
                if b.get("name") in EDIT_TOOLS and path:
                    edited[path] = edited.get(path, 0) + 1
            elif b.get("type") == "tool_result" and b.get("is_error"):
                errors.append((tool_names.get(b.get("tool_use_id"), "?"), result_text(b)))
            elif e.get("type") == "assistant" and b.get("type") == "text" and b.get("text", "").strip():
                recent_text.append(clip(b["text"], 300))
    return {"prompts": prompts, "edited": edited, "errors": errors,
            "compactions": compactions or summaries, "first_ts": first_ts,
            "recent_text": recent_text, "recent_tools": recent_tools}


# ----------------------------------------------------------------- context

def prepare_handoff(cwd, session_id, now):
    sid = resolved_session_id(session_id)[:8]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        sid = "session"
    directory = Path(cwd, HANDOFF_DIR)
    try:
        directory.mkdir(exist_ok=True)
        with (directory / ".gitignore").open("x", encoding="utf-8", newline="\n") as f:
            f.write("*\n")
    except OSError:
        # The ignore file may already exist, or the project may be read-only.
        pass
    return f"{HANDOFF_DIR}/{now:%Y%m%d-%H%M}-{sid}.md"


def cmd_context(args):
    cwd = os.path.abspath(args.cwd)
    now = datetime.now()
    target = prepare_handoff(cwd, args.session, now)
    print(f"# Handoff digest — {os.path.basename(cwd)}")
    print(f"cwd: {cwd}   generated: {now:%Y-%m-%d %H:%M}")
    print(f"Handoff target: {target}")
    if os.path.lexists(os.path.join(cwd, target)):
        print("Handoff target already exists.")

    # --- session index and capped activity after compaction
    idx = None
    try:
        path = find_transcript(args.session, cwd)
        if path:
            idx = session_index(load_entries(path))
            p = idx["prompts"]
            shown = list(enumerate(p, 1)) if len(p) <= 25 else list(enumerate(p[:5], 1)) + [(None, f"... ({len(p) - 25} prompts omitted) ...")] + list(enumerate(p[-20:], len(p) - 19))
            body = [f"transcript: {path}",
                    f"started: {idx['first_ts']}   human prompts: {len(p)}   "
                    f"compactions: {idx['compactions']}",
                    "", "User prompts, in order:"]
            body += [f"{i}. {clip(x, 220)}" if i is not None else x for i, x in shown]
            body += ["", "Files edited this session (edit count):"]
            body += [f"- {display_path(f, cwd)} ({n})" for f, n in sorted(idx["edited"].items(), key=lambda kv: -kv[1])[:40]] \
                or ["- (none)"]
            if idx["errors"]:
                body += ["", "Last tool errors (possible gotchas):"]
                body += [f"- {clip(t, 80)} → {clip(r, 200)}" for t, r in idx["errors"][-6:]]
            section("Session index", "\n".join(body))
            if idx["compactions"]:
                activity = [f"- Claude: {text}" for text in idx["recent_text"]]
                activity += [f"- Tool: {label}" for label in idx["recent_tools"]]
                section("Last activity", "\n".join(activity))
        else:
            section("Session index", f"No transcript found under {projects_dir()} for this cwd.")
    except Exception as ex:
        section("Session index", f"(failed: {ex})")

    # --- git
    if git(["rev-parse", "--is-inside-work-tree"], cwd) != "true":
        section("Git", "Not a git repository.")
        return print_docs(cwd, None, target)

    branch = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    upstream = git(["rev-parse", "--abbrev-ref", "@{upstream}"], cwd)
    ahead_behind = git(["rev-list", "--left-right", "--count", "@{upstream}...HEAD"], cwd) if upstream else ""
    head = [f"branch: {branch}   upstream: {upstream or '(none)'}"]
    if ahead_behind:
        behind, ahead = ahead_behind.split()
        head.append(f"ahead {ahead} / behind {behind} (unpushed commits: {ahead})")
    if upstream:
        commits = git(["log", "--oneline", "-15", "@{u}..HEAD"], cwd)
        if commits:
            head += ["", "Unpushed commits:", commits]
    untracked = [line for line in git(["status", "--porcelain", "--untracked-files=all"], cwd).splitlines()
                 if line.startswith("?? ")]
    if untracked:
        head += ["", "Untracked files:", *untracked[:30]]
        if len(untracked) > 30:
            head.append(f"+{len(untracked) - 30} more")
    section("Git", "\n".join(head))
    section("Working tree (git status --short)", git(["status", "--short", "--untracked-files=no"], cwd, limit=40))

    # Base = last commit before this session started; else merge-base with default branch.
    base, base_why = None, ""
    if idx and idx["first_ts"]:
        base = git(["rev-list", "-1", f"--before={idx['first_ts']}", "HEAD"], cwd)
        base_why = "last commit before this session started"
    if not base:
        for ref in [git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], cwd),
                    "origin/main", "origin/master", "main", "master"]:
            if ref and ref != branch and git(["rev-parse", "--verify", "--quiet", ref], cwd):
                base = git(["merge-base", "HEAD", ref], cwd)
                base_why = f"merge-base with {ref}"
                break

    if base:
        section(f"Commits since base {base[:9]} ({base_why})",
                git(["log", "--oneline", "--no-decorate", f"{base}..HEAD"], cwd, limit=30))
        section("Diffstat base → working tree",
                git(["diff", "--stat=100", base], cwd, limit=45))
    else:
        section("Recent commits", git(["log", "--oneline", "--no-decorate", "-15"], cwd))
        section("Uncommitted diffstat", git(["diff", "--stat=100", "HEAD"], cwd, limit=45))
    print_docs(cwd, base or "HEAD", target)


def print_docs(cwd, base, target=None):
    # Key docs: presence and size only, so Claude can decide what to open.
    rows = []
    for name in KEY_DOCS:
        p = os.path.join(cwd, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                n = sum(1 for _ in f)
            mtime = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
            rows.append(f"- {name}: {n} lines, modified {mtime}")
    section("Key docs present", "\n".join(rows))

    if base:
        git_root = git(["rev-parse", "--show-toplevel"], cwd) or cwd
        print_markdown_changes(git_root, base)

    target_path = os.path.normpath(os.path.join(cwd, target)) if target else None
    candidates = [path for path in glob.glob(os.path.join(cwd, HANDOFF_DIR, "*.md"))
                  if path != target_path and os.path.isfile(path)]
    prev = max(candidates, key=os.path.getmtime) if candidates else os.path.join(cwd, HANDOFF_NAME)
    if os.path.isfile(prev):
        with open(prev, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        body = "\n".join(lines[:80]) + (f"\n... ({len(lines) - 80} more lines)" if len(lines) > 80 else "")
        section(f"Previous handoff ({os.path.relpath(prev, cwd)}; carry forward anything still open)", body)


def print_markdown_changes(cwd, base):
    # Markdown diffs are the densest signal of intent, so show the actual
    # hunks (capped), not just a stat. The old handoff is shown separately.
    changed = [f for f in git(["diff", "--name-only", base, "--", "*.md", "*.mdx"], cwd).splitlines()
               if os.path.basename(f) != HANDOFF_NAME]
    untracked = [f for f in git(["ls-files", "--others", "--exclude-standard", "--", "*.md", "*.mdx"], cwd).splitlines()
                 if os.path.basename(f) != HANDOFF_NAME]
    out, total = [], 0
    for f in changed[:12]:
        d = git(["diff", "-U1", base, "--", f], cwd).splitlines()
        d = [l for l in d if not l.startswith(("diff --git", "index ", "--- ", "+++ "))]
        take = d[:60]
        if len(d) > 60:
            take.append(f"... ({len(d) - 60} more diff lines; open the file if needed)")
        out += [f"#### {f}", "```diff", *take, "```"]
        total += len(take)
        if total > 250:
            out.append(f"... stopped at 250 diff lines; other changed .md: {', '.join(changed[changed.index(f) + 1:])}")
            break
    if untracked:
        out.append("New untracked .md files: " + ", ".join(untracked[:20]))
    section("Markdown changes since base", "\n".join(out))


# -------------------------------------------------------------- transcript

def cmd_transcript(args):
    cwd = os.path.abspath(args.cwd)
    path = find_transcript(args.session, cwd)
    if not path:
        print(f"No transcript found under {projects_dir()} for {cwd}.")
        return
    lines = []
    entries = load_entries(path)
    has_boundary = any(is_compaction(e) for e in entries)
    for e in entries:
        if e.get("isSidechain"):
            continue
        if is_compaction(e) or (e.get("isCompactSummary") and not has_boundary):
            lines.append("===== context compacted here =====")
            continue
        p = human_prompt(e)
        if p:
            lines.append(f"\nUSER: {clip(p, 700)}")
            continue
        for b in blocks(e):
            t = b.get("type")
            if e.get("type") == "assistant" and t == "text" and b.get("text", "").strip():
                lines.append(f"CLAUDE: {clip(b['text'], 450)}")
            elif t == "tool_use":
                lines.append(f"  → {tool_label(b)}")
            elif t == "tool_result" and b.get("is_error"):
                lines.append(f"  ✗ error: {clip(result_text(b), 220)}")
            # thinking blocks and successful tool output are skipped on purpose:
            # they are the bulk of the file and the least useful for a handoff.
    text = "\n".join(lines)
    if len(text) > args.budget:
        # Keep a little of the start (the original goal) and most of the end (current state).
        head = int(args.budget * 0.25)
        text = text[:head] + f"\n\n..... [{len(text) - args.budget} chars of middle omitted] .....\n\n" \
            + text[-(args.budget - head):]
    print(f"# Condensed transcript: {path}\n")
    print(text)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("context", "transcript"):
        p = sub.add_parser(name)
        p.add_argument("--session", default="")
        p.add_argument("--cwd", default=os.getcwd())
        if name == "transcript":
            p.add_argument("--budget", type=int, default=30000, help="max chars of output")
    args = ap.parse_args()
    try:
        (cmd_context if args.cmd == "context" else cmd_transcript)(args)
    except Exception as ex:  # never fail the skill invocation
        print(f"\n(digest.py {args.cmd} failed: {ex})")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        pass
    except Exception as ex:
        print(f"(digest.py failed: {ex})")
    sys.exit(0)
