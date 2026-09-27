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

## Install / update

Requires Claude Code, `git`, and Python 3.8+ (standard library only). The
skill finds whichever of `python3`, `python` or `py -3` works.

Running the installer again is also how you **update**: it pulls the latest
version first, reinstalls, and keeps the last 3 installs in
`~/.claude/skill-backups/`.

Set `--window` / `-Window` to your model's context window. Typing `/context`
in Claude Code shows it (e.g. `191.9k / 1m`). The default is 200000.

### macOS / Linux

```sh
git clone https://github.com/shaswat28/handoff-skill.git ~/handoff-skill
cd ~/handoff-skill && ./install.sh --window 1000000
```

Later updates: `cd ~/handoff-skill && ./install.sh --window 1000000`.
With `--link` (symlink instead of copy), a plain `git pull` is enough.
`--project /path/to/repo` installs the skill for one repo only.

### Windows

Claude Code on Windows uses Git Bash, which comes with Git for Windows. You
also need Python from [python.org](https://www.python.org/downloads/). Tick
"Add python.exe to PATH" in its installer. In **PowerShell**:

```powershell
git clone https://github.com/shaswat28/handoff-skill.git $HOME\handoff-skill
powershell -ExecutionPolicy Bypass -File $HOME\handoff-skill\install.ps1 -Window 1000000
```

Later updates: run the second line again. `-ExecutionPolicy Bypass` is
needed because Windows blocks downloaded scripts by default, and it applies
only to that one run. The installer also converts any Windows (CRLF) line
endings back to LF. CRLF line endings made `/handoff` fail silently on the
first Windows install.

### Installer options

| sh | PowerShell | Effect |
|---|---|---|
| `--window N` | `-Window N` | context window in tokens (default 200000) |
| `--warn 45,70` | `-Warn 45,70` | warning thresholds, % of the window |
| `--no-compact-hold` | `-NoCompactHold` | don't postpone the first auto-compaction |
| `--no-hooks` | `-NoHooks` | skill only; removes the hooks if installed |
| `--project DIR` | `-Project DIR` | install the skill into one repo (hooks stay global) |
| `--link` | — | symlink instead of copy |

Restart Claude Code (or the desktop app) after installing.

## Context warnings

The installer adds two hooks to `~/.claude/settings.json`. It backs the file
up first, to `settings.json.handoff-bak`, and leaves your other settings and
hooks alone.

- **Warnings at 45% and 70%** of the context window, each shown once per chat.
  45% is the cheapest point to start fresh. Every message re-sends the whole
  chat, so each message costs more from there on. At 70%, long chats get slower
  and less precise. If one jump crosses both, you only see the later warning.
- **Compaction hold.** The first time Claude Code tries to compact a chat
  automatically, the hook skips it once and tells you to run `/handoff` while
  the whole chat is still in context. The next attempt goes through as normal.
  `/compact` that you run yourself is never held.

**Cost:** zero tokens. The hooks are small local scripts. Their messages go
to you, not the model. That was checked in a real session: the model didn't
see the warning, and it wasn't in the chat log. They run only when you send
a message (or when compaction starts), take about 30 ms and 11 MB, and exit.
Nothing runs between messages.

**How they measure:** Claude Code passes each hook the path to that chat's
own log. After every reply, the log records how many tokens the model
processed, and the hook reads that number from the end of the log. The log
doesn't record the window size, so it comes from `--window`.

**Limits.** The warning checks when you *send* a message, so a long run of
Claude working on its own can pass a threshold without a warning until your
next message. If compaction triggers in the middle of such a run, the hold
lasts only until Claude's next step. Blocking compaction was verified with
`/compact` in a headless session. The hold on an automatic compaction, and
how the desktop app displays the warnings, haven't been seen yet.

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
environment variable containing "desktop". This worked on the Windows desktop
app. If you ever get a terminal window from the app instead, use `/handoff --paste`.

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
  scripts/hooks.py     context warnings (UserPromptSubmit) and compaction hold (PreCompact)
  scripts/hooks_install.py  adds/removes those hooks in settings.json
install.sh             macOS/Linux install + update (git pull, copy/symlink, hooks)
install.ps1            Windows install + update (git pull, copy, LF fix, hooks)
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
- **Windows:** confirmed working in the desktop app, which used paste mode.
  Launching Windows Terminal / `cmd` from a terminal session hasn't been
  run for real. `install.ps1` was tested under PowerShell 7 on Linux, not on
  Windows PowerShell 5.1. Tests also simulated the Store
  `python3` placeholder, a missing Python, and backslash paths.
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
