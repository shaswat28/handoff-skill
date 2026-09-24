# CLAUDE.md

A Claude Code skill (`/handoff`) that writes `handoff.md` from a token-cheap
digest and launches a fresh session to read it. See README.md for usage.

## Architecture at a glance

- `skills/handoff/SKILL.md` is the product. The Python scripts only feed it.
- The digest is injected with `` !`python3 "${CLAUDE_SKILL_DIR}/scripts/digest.py" context …` ``
  at skill load time. The current conversation (already in Claude's context) is
  the primary source. The digest only adds git/.md/session-index facts.
- `digest.py transcript` is a fallback, used only when `compactions > 0`.
- Stdlib-only Python and no dependencies, deliberately. Users install by copying.

## Commands

```sh
python3 -m unittest discover -s tests -v    # 6 tests, <1s
./install.sh --link                         # dev install: symlink into ~/.claude/skills
```

End-to-end check (uses real tokens, about $0.11): make a temp git repo,
`install.sh --project <it>`, run `claude -p "<small task>" --permission-mode acceptEdits`,
then `claude -p "/handoff --no-launch" --continue …` in that repo, and inspect `handoff.md`.

## Current state (2026-09-24)

Working and verified end to end on Linux: injection, `${CLAUDE_SKILL_DIR}` /
`${CLAUDE_SESSION_ID}` / `${CLAUDE_PROJECT_DIR}` substitution, and the handoff
output. The launcher's macOS/Windows/desktop-Linux paths are **untested on real
machines**. Only the tmux and fallback paths have been exercised.

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
- **`section()` must not `strip()` leading spaces.** Stripping them
  corrupted the first `git status --short` line (` M` became `M`).
- **The template's outer fence in SKILL.md is four backticks.** It contains
  a ```` ```sh ```` block, and a three-backtick outer fence ends early.
