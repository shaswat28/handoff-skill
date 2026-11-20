---
name: handoff
description: Write a session handoff under .handoff/ from the conversation and a compact digest, then open a fresh Claude Code session in the same folder to read it.
argument-hint: "[focus notes] [--no-launch] [--paste | --terminal]"
disable-model-invocation: true
allowed-tools: Bash(sh "${CLAUDE_SKILL_DIR}/scripts/py" *) Bash(git status *) Bash(git diff *) Bash(git log *) Read Write Edit
---

# /handoff

You are handing this session off to a fresh Claude Code session that has **none of
this conversation**. Write the handoff at the target path printed in the digest,
then launch the new session. User arguments: `$ARGUMENTS`

## Token budget — follow strictly

The point of this skill is a good handoff *without* burning tokens.

- **Your own memory of this conversation is the primary source.** You already have it;
  re-reading it costs nothing. The digest below fills gaps, it does not replace memory.
- The digest is pre-computed and size-capped. Do **not** re-run the git commands it
  already covers, `cat` whole files, re-read the raw `.jsonl` transcript, or spawn subagents.
- Run the condensed transcript once (capped at 30,000 characters) only if
  `compactions:` is **> 0** and your conversation memory plus **Last activity**
  leave a gap that matters for the handoff:
  `sh "${CLAUDE_SKILL_DIR}/scripts/py" digest.py transcript --session "${CLAUDE_SESSION_ID}" --cwd "${CLAUDE_PROJECT_DIR}"`
- You may open at most ~3 specific files (or line ranges) if a claim in the handoff
  needs checking. Reads of `CLAUDE.md`, `DESIGN.md` and `README.md` needed for edits
  in step 2 are outside that file count. Keep the whole run well under 20k tokens.

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
3. **Write to the digest's `Handoff target`** relative to the printed project folder.
   Write the new file directly without a Read. Never overwrite older handoffs. Carry forward open
   items from **Previous handoff** and use the template below. Aim for 50–150 lines.
   Be concrete: `path:line`, exact commands, exact error text. Mark anything you did
   not verify as *(unverified)*. Never include secrets, tokens or credentials.
   Treat `--no-launch`, `--paste` and `--terminal` as flags. Weight the handoff
   toward any remaining focus notes in `$ARGUMENTS`.
4. **Keep `.handoff/` out of commits.** It holds local session state.
5. **Launch the new session** unless `$ARGUMENTS` contains `--no-launch`:
   `sh "${CLAUDE_SKILL_DIR}/scripts/py" launch.py --cwd "${CLAUDE_PROJECT_DIR}" --file "<target path from digest>"`
   Append `--mode paste` if `$ARGUMENTS` contains `--paste`, or `--mode terminal` if it
   contains `--terminal`.
   - `LAUNCHED:` → tell the user a new terminal opened with the new session.
   - `PASTE_MODE:` → tell the user to start a new session in the Claude app on the
     printed folder and paste the prompt (say whether it is already on the clipboard),
     and show the prompt in a code block.
   - `NOT_LAUNCHED:` → show the user the printed command and the `/clear` + paste
     alternative, verbatim, in a code block.
6. In ≤5 lines, report the handoff path, any docs you updated and the launch result.

## Session handoff template

````markdown
# Session handoff — <project> — <YYYY-MM-DD HH:MM>

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
