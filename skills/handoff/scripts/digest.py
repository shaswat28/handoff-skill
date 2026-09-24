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
from datetime import datetime

HANDOFF_NAME = "handoff.md"
KEY_DOCS = ["CLAUDE.md", "AGENTS.md", "README.md", "DESIGN.md", "TODO.md",
            "CHANGELOG.md", "CONTRIBUTING.md", HANDOFF_NAME]
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Harness-injected pseudo-prompts that are not things the human typed.
NOISE_PREFIXES = ("<system-reminder>", "<local-command-stdout>", "<local-command-stderr>",
                  "<command-message>", "Caveat:", "[Request interrupted")


# ---------------------------------------------------------------- helpers

def git(args, cwd, limit=None):
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                             text=True, timeout=30).stdout
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


# ------------------------------------------------------------ transcripts

def projects_dir():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "projects")


def encode_cwd(cwd):
    # Claude Code names the per-project folder after the cwd with every
    # non-alphanumeric character replaced by "-" (/a/b.c -> -a-b-c).
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def find_transcript(session_id, cwd):
    root = projects_dir()
    sid = (session_id or "").strip()
    if sid and "$" not in sid and "{" not in sid:  # ignore unexpanded placeholders
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
                entries.append(json.loads(line))
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
    texts = [b.get("text", "") for b in blocks(entry) if b.get("type") == "text"]
    if not texts or any(b.get("type") == "tool_result" for b in blocks(entry)):
        return None
    text = "\n".join(texts).strip()
    m = re.search(r"<command-name>(.*?)</command-name>", text)
    if m:
        args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
        return f"{m.group(1)} {args.group(1).strip() if args else ''}".strip()
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
    tool_names = {}
    first_ts = None
    for e in entries:
        if e.get("isSidechain"):
            continue
        first_ts = first_ts or e.get("timestamp")
        if is_compaction(e):
            compactions += 1
        summaries += bool(e.get("isCompactSummary"))
        p = human_prompt(e)
        if p:
            prompts.append(p)
        for b in blocks(e):
            if b.get("type") == "tool_use":
                tool_names[b.get("id")] = tool_label(b)
                inp = b.get("input") or {}
                path = inp.get("file_path") or inp.get("notebook_path")
                if b.get("name") in EDIT_TOOLS and path:
                    edited[path] = edited.get(path, 0) + 1
            elif b.get("type") == "tool_result" and b.get("is_error"):
                errors.append((tool_names.get(b.get("tool_use_id"), "?"), result_text(b)))
    return {"prompts": prompts, "edited": edited, "errors": errors,
            "compactions": compactions or summaries, "first_ts": first_ts}


# ----------------------------------------------------------------- context

def cmd_context(args):
    cwd = os.path.abspath(args.cwd)
    print(f"# Handoff digest — {os.path.basename(cwd)}")
    print(f"cwd: {cwd}   generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # --- session index (cheap: only prompts, edited paths, errors)
    idx = None
    try:
        path = find_transcript(args.session, cwd)
        if path:
            idx = session_index(load_entries(path))
            p = idx["prompts"]
            shown = p if len(p) <= 25 else p[:5] + [f"... ({len(p) - 25} prompts omitted) ..."] + p[-20:]
            body = [f"transcript: {path}",
                    f"started: {idx['first_ts']}   human prompts: {len(p)}   "
                    f"compactions: {idx['compactions']}",
                    "", "User prompts, in order:"]
            body += [f"{i + 1}. {clip(x, 220)}" for i, x in enumerate(shown)]
            body += ["", "Files edited this session (edit count):"]
            body += [f"- {f} ({n})" for f, n in sorted(idx["edited"].items(), key=lambda kv: -kv[1])[:40]] \
                or ["- (none)"]
            if idx["errors"]:
                body += ["", "Last tool errors (possible gotchas):"]
                body += [f"- {clip(t, 80)} → {clip(r, 200)}" for t, r in idx["errors"][-6:]]
            section("Session index", "\n".join(body))
        else:
            section("Session index", f"No transcript found under {projects_dir()} for this cwd.")
    except Exception as ex:
        section("Session index", f"(failed: {ex})")

    # --- git
    if git(["rev-parse", "--is-inside-work-tree"], cwd) != "true":
        section("Git", "Not a git repository.")
        return print_docs(cwd, None)

    branch = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    upstream = git(["rev-parse", "--abbrev-ref", "@{upstream}"], cwd)
    ahead_behind = git(["rev-list", "--left-right", "--count", "@{upstream}...HEAD"], cwd) if upstream else ""
    head = [f"branch: {branch}   upstream: {upstream or '(none)'}"]
    if ahead_behind:
        behind, ahead = ahead_behind.split()
        head.append(f"ahead {ahead} / behind {behind} (unpushed commits: {ahead})")
    section("Git", "\n".join(head))
    section("Working tree (git status --short)", git(["status", "--short"], cwd, limit=40))

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
    print_docs(cwd, base or "HEAD")


def print_docs(cwd, base):
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

    if not base:
        return
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

    prev = os.path.join(cwd, HANDOFF_NAME)
    if os.path.isfile(prev):
        with open(prev, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        body = "\n".join(lines[:80]) + (f"\n... ({len(lines) - 80} more lines)" if len(lines) > 80 else "")
        section("Previous handoff.md (carry forward anything still open)", body)


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
    main()
