# DESIGN.md — running log

## 2026-09-24 (later) — macOS launch fix

**Fixed.** `launch.py` detached every launcher with `Popen` and printed
`LAUNCHED` right away. On macOS, `osascript` can fail when Automation
permission is denied (-1743), and the skill still reported success. Now the
launchers that hand off and exit (osascript, tmux, wt, cmd) are run and waited
on, and a non-zero exit falls through to the next one or the clipboard. On an
Automation denial, it also prints where to allow it. Added 2 tests: the
AppleScript quoting and the failed-launcher fallback.

**Also this session.** The repo's single commit was re-authored as the
owner, and the default branch moved to `main`.

**Still deferred.** A run on a real Mac. Nothing has been tested outside a
Linux container.

## 2026-09-24 — initial build

**Built.** `skills/handoff/` (SKILL.md, `scripts/digest.py`, `scripts/launch.py`),
`install.sh`, unit tests, and docs. It was verified end to end with a headless
Claude Code session on a throwaway repo: 2 turns, one tool call, $0.11, and a
correct `handoff.md`.

**Key decisions and why.**
- *Conversation memory is the primary source, not the log file.* The skill
  runs inside the session being handed off, so Claude already has the chat.
  Re-reading the JSONL would pay for the same content twice. The log is only
  mined for a cheap index (prompts, edited files, errors), plus a full
  condensed read after compaction.
- *`!` injection instead of asking Claude to run commands.* This saves one
  or more model round-trips and keeps the gather step deterministic and capped.
- *Show `.md` diff hunks, not just stats.* Doc changes are the densest record
  of intent, and the user specifically asked for .md diffs. They're capped at
  60 lines per file and 250 lines total.
- *Session base = last commit before the session's first timestamp*
  (`git rev-list -1 --before=`). This shows what changed *this session* even on
  main. If there's no log, it falls back to the merge-base with the default branch.
- *Durable facts go to CLAUDE.md/DESIGN.md, and session state goes to
  handoff.md.* This stops handoff.md from growing into a second CLAUDE.md and
  keeps the long-lived docs current.
- *Launch via `claude "<prompt>"` in a new terminal.* A positional prompt
  starts an interactive session with that message already sent, which covers
  the "type an instruction into the new chat" requirement. The prompt ends
  with "wait for my go-ahead", so the new session doesn't act on stale notes.
- *`disable-model-invocation: true`.* The skill opens terminal windows, so
  it should only run when the user asks for it.

**Rejected options.**
- `context: fork` / subagent summariser: it loses the conversation, which is
  the main thing being handed off.
- Reading the raw JSONL with Read/cat: a 5-turn log measured 370KB, mostly
  system-prompt snapshots and attachments.
- A SessionStart hook that auto-injects handoff.md into every new session:
  it would also fire on unrelated sessions and stale handoffs. An explicit
  launch prompt is more predictable. Deferred, not ruled out.
- Keeping a history of handoffs (`.claude/handoffs/…`): the previous
  handoff is folded into the next one ("carry forward open items"), which
  keeps the useful part without the clutter.
- Bash scripts: Python handles JSON parsing and Windows launching better, and
  `python3` is present almost everywhere Claude Code is.

**Broke and fixed.** Compactions were double-counted, installer backups
loaded as a duplicate skill, `section()` stripped the leading space of
`git status` lines, a dry-run fell through to the fallback path, and a nested
code fence ended the template early. Details are in CLAUDE.md under Gotchas.

**Deferred.**
- Real-machine testing of the macOS (Terminal/iTerm2), Windows (wt/cmd) and
  desktop Linux launch paths.
- A `python`/`py` fallback for Windows installs without `python3`.
- Launching in a new VS Code terminal or a new Claude desktop-app chat. No
  programmatic hook was found, so these use the print-and-copy fallback.
- Per-project config (custom handoff path, custom launch prompt).
