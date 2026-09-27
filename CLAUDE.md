# CLAUDE.md

A Claude Code skill (`/handoff`) that writes `handoff.md` from a token-cheap
digest and launches a fresh session to read it. See README.md for usage.

## Architecture at a glance

- `skills/handoff/SKILL.md` is the product. The Python scripts only feed it.
- The digest is injected with `` !`sh "${CLAUDE_SKILL_DIR}/scripts/py" digest.py context …` ``
  at skill load time. The current conversation (already in Claude's context) is
  the primary source. The digest only adds git/.md/session-index facts.
- `digest.py transcript` is a fallback, used only when `compactions > 0`.
- `hooks.py` (context warnings + compaction hold) is separate from the skill. It
  is registered in `~/.claude/settings.json` by `hooks_install.py`, which both
  installers call. Its settings live in the hook command's arguments
  (`--window`, `--warn`). Per-chat "already warned" markers are kept in
  `~/.claude/handoff-state/`.
- Stdlib-only Python and no dependencies, deliberately. Users install by copying.

## Commands

```sh
python3 -m unittest discover -s tests -v    # 19 tests, ~2s
./install.sh --link --window 1000000        # dev install/update: symlink + hooks
CLAUDE_CONFIG_DIR=$(mktemp -d) ./install.sh # try the installer without touching ~/.claude
```

`install.ps1` can be tested on Linux with a PowerShell 7 tarball from
github.com/PowerShell/PowerShell/releases (`pwsh -NoProfile -File install.ps1`).
Windows ships PowerShell 5.1, so keep the script free of 7-only syntax
(`??`, `?:`, `&&`, `||`).

```sh
```

End-to-end check (uses real tokens, about $0.11): make a temp git repo,
`install.sh --project <it>`, run `claude -p "<small task>" --permission-mode acceptEdits`,
then `claude -p "/handoff --no-launch" --continue …` in that repo, and inspect `handoff.md`.

## Current state (2026-09-27)

Context warnings (45% / 70%) and the compaction hold were added this session,
and verified in headless Claude Code sessions (see DESIGN.md). They haven't
been seen in the desktop app yet.


Working and verified end to end on Linux: injection, `${CLAUDE_SKILL_DIR}` /
`${CLAUDE_SESSION_ID}` / `${CLAUDE_PROJECT_DIR}` substitution, and the handoff
output. **The owner reports `/handoff` working in the Windows desktop app**
after the LF fix, and paste mode triggered correctly there. macOS and
desktop-Linux launching are still untested on real machines.

## Gotchas

- **Scripts must exit 0.** A non-zero exit from a `!` injection aborts the
  whole `/handoff` invocation. Both scripts catch everything and `sys.exit(0)`.
- **Don't count `isCompactSummary` and `compact_boundary` both.** One
  compaction writes both entries, which double-counted before the fix. Count
  boundaries, and fall back to summaries only if no boundaries exist.
- **Installer backups must not sit in `skills/`.** A `handoff.bak` folder
  there has the same `name: handoff` frontmatter and loads as a duplicate
  skill. Backups go to `~/.claude/skill-backups/`.
- **Nested headless `claude` inherits `CLAUDE_CODE_SESSION_ID`.** Running
  `claude -p` from inside a Claude session reuses the parent's session ID. Its
  transcript still goes to the child cwd's project folder, so lookup by
  `*/<id>.jsonl` can match several files. `find_transcript` takes the newest
  by mtime, which is the live one.
- **Don't use `context: fork` in SKILL.md.** A forked subagent has no access
  to the conversation, which is the main thing being handed off.
- **Wait for osascript/tmux/wt/cmd, don't detach them.** They pass the
  command on and exit, so their exit code tells you whether it worked. A
  detached `Popen` reported `LAUNCHED` even when macOS refused Automation
  permission (error -1743). Only terminal emulators that block are detached.
- **Desktop-app detection is a heuristic.** Paste mode starts when
  `CLAUDE_CODE_ENTRYPOINT` contains "desktop". It was confirmed working in the
  Windows desktop app, but the exact value there wasn't captured.
  `--paste` / `--terminal` override it. The launcher tests have to clear this variable, or they fail when run
  inside the app.
- **Always call the scripts through `sh scripts/py`, never `python3` directly.**
  On Windows `python3` is often missing or is the Microsoft Store placeholder,
  which exits non-zero. A non-zero exit from the `!` injection aborts the skill.
  The wrapper tests each Python before using it and exits 0 if none works.
- **Files must stay LF. `.gitattributes` forces `eol=lf`.** Git for Windows
  checks files out as CRLF by default. With CRLF, `scripts/py` stops working
  (`shift: not found`, `Syntax error`), and `/handoff` then prints nothing and
  writes no file. This happened on the owner's first Windows install and was
  reproduced here. A test checks for CRLF in `skills/`.
- **`hooks.py prompt` must never exit 2.** On UserPromptSubmit, exit 2 blocks
  the prompt and erases what the user typed. Only `precompact` returns 2, which
  skips that compaction. That behaviour and the `trigger` input field were both
  verified with a real `/compact`. Everything else exits 0, including bad
  arguments (it catches `BaseException`, because argparse raises `SystemExit`).
- **The hook command uses an absolute Python path** (`sys.executable` at
  install time), quoted and with forward slashes, so it runs in any shell,
  cmd included. If that Python is removed or moved, the hooks fail until the
  installer is run again.
- **Hook settings are command arguments, not `env`.** It isn't verified that
  a settings.json `env` block reaches hook processes. Arguments always do.
- **PowerShell turns `-Warn 45,70` into an array.** A `[string]` parameter
  would receive "45 70". `install.ps1` declares `[string[]]` and joins with commas.
- **Don't set `$ErrorActionPreference = "Stop"` in install.ps1.** In
  Windows PowerShell 5.1 it turns native stderr (git, python) into fatal errors.
- **`section()` must not `strip()` leading spaces.** Stripping them
  corrupted the first `git status --short` line (` M` became `M`).
- **The template's outer fence in SKILL.md is four backticks.** It contains
  a ```` ```sh ```` block, and a three-backtick outer fence ends early.
