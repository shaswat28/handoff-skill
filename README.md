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

Requires Claude Code, `git`, and Python 3.8+ (standard library only). The
skill finds whichever of `python3`, `python` or `py -3` works.

```sh
git clone https://github.com/shaswat28/handoff-skill.git
cd handoff-skill
./install.sh            # copies to ~/.claude/skills/handoff (all projects)
./install.sh --link     # or symlink it, so `git pull` updates it
./install.sh --project /path/to/repo   # or install for one repo only
```

Restart Claude Code, then type `/handoff`.

### Windows

Claude Code on Windows uses Git Bash, which comes with Git for Windows. The
skill's commands also run in that shell. You also need Python from
[python.org](https://www.python.org/downloads/). Tick "Add python.exe to PATH"
in the installer.

In **PowerShell**:

```powershell
git clone https://github.com/shaswat28/handoff-skill.git $HOME\handoff-skill
New-Item -ItemType Directory -Force $HOME\.claude\skills | Out-Null
Copy-Item -Recurse -Force $HOME\handoff-skill\skills\handoff $HOME\.claude\skills\
```

If `/handoff` shows nothing, check that the files have Unix line endings.
In PowerShell, this should print `False`:
`(Get-Content -Raw $HOME\.claude\skills\handoff\scripts\py).Contains("`r")`.
Clones made before `.gitattributes` was added have Windows line endings.
Delete both folders and repeat the three steps above.

Or in **Git Bash**: `cd ~/handoff-skill && ./install.sh`. Don't use `--link`
on Windows. Git Bash's `ln -s` usually makes a copy rather than a real link.
To update later, `git pull` in `~\handoff-skill` and run the copy step again.

## Usage

```
/handoff                          # write handoff.md, open a new session
/handoff focus on the auth bug    # weight the handoff toward something
/handoff --no-launch              # write handoff.md only
/handoff --paste                  # copy the prompt instead of opening a terminal
/handoff --terminal               # force a terminal window (e.g. from the desktop app)
```

### Claude desktop app

The skill works in the desktop app's **Code** tab. Sessions there run Claude
Code on your machine, so they load `~/.claude/skills`. It doesn't work in the
regular **Chat** tab, which has no access to your project folder or git.

A terminal window is the wrong place for the new chat when you work in the app,
so the skill switches to paste mode instead. It copies the "read handoff.md"
prompt to your clipboard, and you start a new session in the app on the same
folder and paste it. The app is detected from the `CLAUDE_CODE_ENTRYPOINT`
environment variable containing "desktop". That value isn't documented, so if
you get a terminal window from the app anyway, use `/handoff --paste`.
The skill prints the entrypoint it saw, so you can report it.

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
  scripts/py           picks a working Python (python3 / python / py -3), always exits 0
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

## macOS notes

- The skill opens a new **Terminal.app** window. If you run Claude Code
  inside **iTerm2**, it opens an iTerm2 window instead. Inside tmux, it
  opens a tmux window.
- The first time, macOS asks whether your terminal may control
  Terminal/iTerm2. Click **OK**. If you clicked Don't Allow, turn it on in
  System Settings → Privacy & Security → Automation. Until then the skill
  falls back to copying the command to your clipboard with `pbcopy`.
- `python3` comes with the Xcode Command Line Tools. If running `python3`
  offers to install them, accept.

## Limits and constraints

- Personal skills (`~/.claude/skills`) don't load in claude.ai cloud sessions
  unless skill sync is on. Use `--project` to commit the skill into a repo instead.
- `!` injection can be turned off with `disableSkillShellExecution`. The skill
  then tells Claude to run the digest itself, which costs one extra tool call.
- **Windows is untested on a real machine.** Tests simulated the Store
  `python3` placeholder, a missing Python, and backslash paths. Launching Windows
  Terminal / `cmd` has not been run for real.
- The macOS, Windows and desktop Linux launch paths have **not been tested on
  real machines yet**. The macOS AppleScript commands and the fallback
  behaviour are covered by unit tests, but nothing has run on a real Mac.
  Please report what happens on yours.
- Compaction is detected from `compact_boundary` / `isCompactSummary` entries.
  Those names come from what the logs look like in practice, not from a
  documented format, so a future Claude Code version could change them.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 skills/handoff/scripts/digest.py context          # digest for the cwd
python3 skills/handoff/scripts/launch.py --dry-run        # show launch plan
```
