# /handoff — a Claude Code skill for clean session handoffs

When a Claude Code chat gets long, type `/handoff`. The skill:

1. Builds a small digest of what matters: git state, commits and diffstat
   since this session started, the actual diffs of changed `.md` files, the
   previous `handoff.md`, and an index of the chat log (your prompts in order,
   files edited, tool errors hit). All of it is size-capped.
2. Has Claude write `handoff.md` in the project root: TL;DR, goal, state of
   play, next steps, decisions (including rejected options), gotchas, key files,
   open questions, and how to verify. If the project keeps `CLAUDE.md` /
   `DESIGN.md` / `README.md`, lasting facts go there instead.
3. Opens a **new terminal in the same folder** running
   `claude "Read handoff.md … summarize where things stand … wait for my go-ahead"`,
   so the fresh chat starts already reading the handoff.

## Install

Requires Claude Code, `git`, and `python3` (3.8+, standard library only).

```sh
git clone https://github.com/shaswat28/handoff-skill.git
cd handoff-skill
./install.sh            # copies to ~/.claude/skills/handoff (all projects)
./install.sh --link     # or symlink it, so `git pull` updates it
./install.sh --project /path/to/repo   # or install for one repo only
```

Restart Claude Code, then type `/handoff`.

## Usage

```
/handoff                          # write handoff.md, open a new session
/handoff focus on the auth bug    # weight the handoff toward something
/handoff --no-launch              # write handoff.md only
```

If no new terminal can be opened (Claude desktop/web app, SSH, VS Code's
built-in terminal), the skill prints the `claude "…"` command and tries to copy
it to your clipboard. You can also type `/clear` in the same terminal and paste
the printed prompt.

`handoff.md` holds the state of one session and is not committed automatically.
Add it to your project's `.gitignore` if you don't want it to show up in `git status`.

## How it keeps token use low

- **The chat you're in is the main source.** Claude already has the
  conversation in context, so the skill doesn't re-read it.
- **The digest runs before Claude sees the prompt.** `SKILL.md` uses
  `` !`command` `` injection, so `scripts/digest.py context` runs while the skill
  loads and its output (usually 1–5k tokens) is pasted in. Claude makes no
  tool calls to gather it.
- **Raw chat logs are never read.** Claude Code logs are JSONL and mostly
  system-prompt snapshots and attachments. In one measured case, a 5-turn log
  was 370KB, and its digest was about 1.5KB. The digest keeps only your prompts,
  files edited and tool errors. It drops thinking blocks and successful tool
  output.
- **The full condensed transcript is only used after compaction.** If
  `/compact` or auto-compaction removed earlier turns from Claude's context,
  the skill runs `digest.py transcript` once. It is capped at 30k characters
  (about 7.5k tokens) and keeps 25% from the start and 75% from the end.

Measured: an end-to-end `/handoff --no-launch` on a small repo took 2 model
turns and one tool call, the write of `handoff.md`. It cost $0.11 on a
fresh session, and most of that was the system prompt. On a long session,
expect the cost to be dominated by the context the chat already holds.

## How the pieces fit

```
skills/handoff/
  SKILL.md             the prompt: token rules, injected digest, steps, handoff template
  scripts/digest.py    `context`: git + .md diffs + session index (injected at load)
                       `transcript`: condensed chat log (only after compaction)
  scripts/launch.py    opens a terminal running `claude "<prompt>"`, else prints + copies
install.sh             copy/symlink into ~/.claude/skills or a project's .claude/skills
tests/test_scripts.py  unit tests with a synthetic transcript and temp git repo
```

**Finding the chat log.** Claude Code writes each session to
`~/.claude/projects/<cwd with non-alphanumerics replaced by '-'>/<session-id>.jsonl`
(or under `$CLAUDE_CONFIG_DIR`). The skill passes `${CLAUDE_SESSION_ID}`. If
that doesn't resolve, it falls back to the newest log for the current folder.

**Opening a terminal.** The launcher tries these in order: tmux (new window, if
you're inside tmux), then iTerm2 or Terminal.app on macOS, Windows Terminal or
`cmd` on Windows, and on Linux with a display gnome-terminal, konsole, kitty,
wezterm, alacritty, xfce4-terminal, x-terminal-emulator or xterm.

## Limits and constraints

- Personal skills (`~/.claude/skills`) don't load in claude.ai cloud sessions
  unless skill sync is on. Use `--project` to commit the skill into a repo instead.
- `!` injection can be turned off with `disableSkillShellExecution`. The skill
  then tells Claude to run the digest itself, which costs one extra tool call.
- On Windows the commands call `python3`. If you only have `py`/`python`,
  edit the two commands in `SKILL.md`.
- The macOS, Windows and desktop Linux launch paths have **not been tested on
  real machines yet**. Only the tmux and fallback paths were exercised, with
  `--dry-run` and unit tests. Please report what happens on yours.
- Compaction is detected from `compact_boundary` / `isCompactSummary` entries.
  Those names come from what the logs look like in practice, not from a
  documented format, so a future Claude Code version could change them.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 skills/handoff/scripts/digest.py context          # digest for the cwd
python3 skills/handoff/scripts/launch.py --dry-run        # show launch plan
```
