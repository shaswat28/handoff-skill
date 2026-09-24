#!/usr/bin/env python3
"""Open a new terminal in DIR running `claude "<prompt>"`.

  launch.py --cwd DIR [--prompt TEXT] [--mode auto|terminal|paste] [--dry-run]

`claude "<prompt>"` starts an interactive session with the prompt already
submitted, so the new chat starts reading handoff.md right away. If no
terminal can be opened (Claude desktop/web app, SSH, CI), the command is
printed and copied to the clipboard instead. Always exits 0.

Paste mode (for the Claude desktop app, where a terminal window is the wrong
place for the new chat) copies just the prompt, for pasting into a new app
session. `auto` picks paste mode when CLAUDE_CODE_ENTRYPOINT mentions "desktop".
"""
import argparse
import os
import platform
import shlex
import shutil
import subprocess
import sys

DEFAULT_PROMPT = (
    "Read handoff.md in this folder: it is the handoff from the previous Claude session. "
    "Also read CLAUDE.md if it exists. Verify anything that looks stale against the code "
    "(git status, the files it names). Then give me a short summary of where things stand "
    "and what you plan to do next, and wait for my go-ahead before changing anything."
)


def is_desktop_app():
    # Heuristic: the exact entrypoint value for the desktop app is not documented,
    # so match loosely and let the user force a mode with --mode.
    return "desktop" in os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").lower()


def paste_mode(cwd, prompt, dry_run):
    clip = None if dry_run else copy_to_clipboard(prompt)
    print("PASTE_MODE: start a new session in the Claude app for this folder and paste the prompt.")
    print(f"Folder: {cwd}")
    print(f"Clipboard: {'prompt copied via ' + clip if clip else 'unavailable, copy it from below'}")
    print(f"(entrypoint: {os.environ.get('CLAUDE_CODE_ENTRYPOINT', 'unset')})")
    print("\nPrompt:\n")
    print(prompt)


def sh_command(cwd, prompt):
    return f"cd {shlex.quote(cwd)} && claude {shlex.quote(prompt)}"


# Launchers that pass the command on and exit, so their exit code is meaningful.
RETURNS_QUICKLY = {"osascript", "tmux", "wt", "cmd"}


def clip_err(text):
    return " ".join((text or "").split())[:200]


def applescript_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def candidates(cwd, prompt):
    """Yield (label, argv) launch attempts for this platform, most specific first."""
    cmd = sh_command(cwd, prompt)
    system = platform.system()

    if os.environ.get("TMUX") and shutil.which("tmux"):
        # Keep the pane open with a shell if claude exits.
        yield "tmux window", ["tmux", "new-window", "-c", cwd, f"{cmd}; exec $SHELL"]

    if system == "Darwin":
        if os.environ.get("TERM_PROGRAM") == "iTerm.app":
            yield "iTerm2", ["osascript",
                             "-e", 'tell application "iTerm2" to create window with default profile',
                             "-e", f'tell application "iTerm2" to tell current session of current window '
                                   f'to write text {applescript_str(cmd)}']
        yield "Terminal.app", ["osascript",
                               "-e", f'tell application "Terminal" to do script {applescript_str(cmd)}',
                               "-e", 'tell application "Terminal" to activate']

    elif system == "Windows":
        # Windows Terminal first, then a plain cmd window.
        if shutil.which("wt"):
            yield "Windows Terminal", ["wt", "-d", cwd, "cmd", "/k", "claude", prompt]
        yield "cmd", ["cmd", "/c", "start", "", "/D", cwd, "cmd", "/k", "claude", prompt]

    elif os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        keep = f"{cmd}; exec bash"
        linux = [
            ("gnome-terminal", ["gnome-terminal", f"--working-directory={cwd}", "--", "bash", "-lc", keep]),
            ("konsole", ["konsole", "--workdir", cwd, "-e", "bash", "-lc", keep]),
            ("kitty", ["kitty", "--directory", cwd, "bash", "-lc", keep]),
            ("wezterm", ["wezterm", "start", "--cwd", cwd, "--", "bash", "-lc", keep]),
            ("alacritty", ["alacritty", "--working-directory", cwd, "-e", "bash", "-lc", keep]),
            ("xfce4-terminal", ["xfce4-terminal", f"--working-directory={cwd}", "-x", "bash", "-lc", keep]),
            ("x-terminal-emulator", ["x-terminal-emulator", "-e", "bash", "-lc", keep]),
            ("xterm", ["xterm", "-e", "bash", "-lc", keep]),
        ]
        for label, argv in linux:
            if shutil.which(argv[0]):
                yield label, argv


def copy_to_clipboard(text):
    for argv in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"],
                 ["xsel", "--clipboard", "--input"], ["clip.exe"], ["clip"]):
        if shutil.which(argv[0]):
            try:
                subprocess.run(argv, input=text, text=True, timeout=5, check=True)
                return argv[0]
            except Exception:
                continue
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--mode", choices=["auto", "terminal", "paste"], default="auto")
    ap.add_argument("--dry-run", action="store_true", help="print what would run, launch nothing")
    args = ap.parse_args()
    cwd = os.path.abspath(args.cwd)

    if args.mode == "paste" or (args.mode == "auto" and is_desktop_app()):
        return paste_mode(cwd, args.prompt, args.dry_run)

    if not shutil.which("claude"):
        print("WARNING: `claude` is not on PATH here; the new terminal may not find it either.")

    for label, argv in candidates(cwd, args.prompt):
        if args.dry_run:
            print(f"[dry-run] would launch via {label}: {argv}")
            return
        try:
            if argv[0] in RETURNS_QUICKLY:
                # These hand the command to a terminal and exit, so wait and check
                # the exit code. A detached Popen would report success even when
                # macOS denies osascript permission to control Terminal/iTerm2.
                r = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                                   text=True, timeout=20)
                if r.returncode != 0:
                    raise RuntimeError(clip_err(r.stderr) or f"exit {r.returncode}")
            else:
                # Terminal emulators may block until closed: detach so they outlive us.
                subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            print(f"LAUNCHED: new Claude Code session via {label} in {cwd}")
            return
        except Exception as ex:
            print(f"({label} failed: {ex}; trying next)")
            if "not allowed" in str(ex) or "-1743" in str(ex):
                print("  macOS blocked automation: allow it in System Settings → Privacy & Security "
                      "→ Automation (let your terminal control Terminal/iTerm2), then retry.")

    cmd = sh_command(cwd, args.prompt)
    clip = None if args.dry_run else copy_to_clipboard(cmd)
    print("NOT_LAUNCHED: could not open a new terminal from here.")
    print(f"Clipboard: {'copied via ' + clip if clip else 'unavailable'}")
    print("Run this in a new terminal:\n")
    print(cmd)
    print("\nOr, to reuse this terminal: type /clear, then paste this prompt:\n")
    print(args.prompt)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"(launch.py failed: {ex})")
    sys.exit(0)
