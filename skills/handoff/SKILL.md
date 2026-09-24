---
name: handoff
description: Write handoff.md capturing what matters in this codebase and what was done this session (from git, changed .md files and the chat log, cheaply), then open a fresh Claude Code session in the same folder that reads it.
argument-hint: "[focus notes] [--no-launch] [--paste | --terminal]"
disable-model-invocation: true
allowed-tools: Bash(sh "${CLAUDE_SKILL_DIR}/scripts/py" *) Bash(git status *) Bash(git diff *) Bash(git log *) Read Write Edit
---

# /handoff

You are handing this session off to a fresh Claude Code session that has **none of
this conversation**. Produce `handoff.md` in the project root, then launch the new
session. User arguments: `$ARGUMENTS`

## Token budget — follow strictly

The point of this skill is a good handoff *without* burning tokens.

- **Your own memory of this conversation is the primary source.** You already have it;
  re-reading it costs nothing. The digest below fills gaps, it does not replace memory.
- The digest is pre-computed and size-capped. Do **not** re-run the git commands it
  already covers, `cat` whole files, re-read the raw `.jsonl` transcript, or spawn subagents.
- Only if `compactions:` in the Session index is **> 0** (earlier conversation was
  summarised away) run the condensed transcript once:
  `sh "${CLAUDE_SKILL_DIR}/scripts/py" digest.py transcript --session "${CLAUDE_SESSION_ID}" --cwd "${CLAUDE_PROJECT_DIR}"`
- You may open at most ~3 specific files (or line ranges) if a claim in the handoff
  needs checking. Budget: the whole skill run should read well under 20k tokens.

## Pre-computed digest

!`sh "${CLAUDE_SKILL_DIR}/scripts/py" digest.py context --session "${CLAUDE_SESSION_ID}" --cwd "${CLAUDE_PROJECT_DIR}"`

(If the line above shows a raw command instead of its output, shell injection is
disabled in this environment: run that command yourself once.)

## Steps

1. **Decide what matters.** From memory + digest, separate:
   - *durable* project knowledge (architecture, conventions, gotchas that stay true), and
   - *session state* (what we were doing, where it stands, what's next).
   Rank by "what would the next session get wrong without this". Skip anything the
   next session can learn in 30 seconds by reading a file.
2. **Durable knowledge goes to the durable docs, not the handoff.** If the project has
   `CLAUDE.md` / `DESIGN.md` / `README.md` and this session produced durable facts they
   lack (or made them wrong), update those files now with small targeted edits, and
   say which you changed. Don't create them if the project doesn't use them.
3. **Write `handoff.md`** (overwrite any previous one; carry forward items from the
   previous handoff that are still open). Use the template below. Aim for 50–150 lines.
   Be concrete: `path:line`, exact commands, exact error text. Mark anything you did
   not verify as *(unverified)*. Never include secrets, tokens or credentials.
   If `$ARGUMENTS` has focus notes, weight the handoff toward them.
4. **Don't commit `handoff.md`** unless the user asked; it's session state.
5. **Launch the new session** unless `$ARGUMENTS` contains `--no-launch`:
   `sh "${CLAUDE_SKILL_DIR}/scripts/py" launch.py --cwd "${CLAUDE_PROJECT_DIR}"`
   Append `--mode paste` if `$ARGUMENTS` contains `--paste`, or `--mode terminal` if it
   contains `--terminal`.
   - `LAUNCHED:` → tell the user a new terminal opened with the new session.
   - `PASTE_MODE:` → tell the user to start a new session in the Claude app on the
     printed folder and paste the prompt (say whether it is already on the clipboard),
     and show the prompt in a code block.
   - `NOT_LAUNCHED:` → show the user the printed command and the `/clear` + paste
     alternative, verbatim, in a code block.
6. Finish with ≤5 lines: where handoff.md is, which docs you updated, launch result.

## handoff.md template

````markdown
# Handoff — <project> — <YYYY-MM-DD HH:MM>

> Written by the previous Claude session for the next one. Read this first, then
> CLAUDE.md. Trust the code over this file if they disagree.

## TL;DR
<3 lines max: goal, where it stands, the very next action>

## What the user wants
<the goal in the user's terms, plus preferences/constraints they stated this session>

## State of play
- Done: <what, and how it was verified — tests run, output seen>
- In progress: <what, exact place it stopped>
- Uncommitted / unpushed: <from the digest; branch name>

## Next steps
1. <concrete, ordered; file:line; command to run>

## Decisions made (and rejected options)
- <decision> — because <reason>. Rejected: <option> because <reason>.

## Gotchas hit this session
- <symptom> → <cause> → <fix/workaround>

## Files that matter
- `path` — <why it matters for the next steps>

## Open questions for the user
- <anything blocked on a human decision>

## Verify quickly
```sh
<the 1–3 commands that show the current state: tests, build, run>
```
````
