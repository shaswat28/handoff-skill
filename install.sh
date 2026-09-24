#!/usr/bin/env bash
# Install the /handoff skill.
#   ./install.sh                 copy to ~/.claude/skills/handoff (all projects)
#   ./install.sh --link          symlink instead, so `git pull` here updates it
#   ./install.sh --project DIR   install into DIR/.claude/skills/handoff only
set -euo pipefail

src="$(cd "$(dirname "$0")" && pwd)/skills/handoff"
dest="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/handoff"
mode=copy

while [ $# -gt 0 ]; do
  case "$1" in
    --link) mode=link ;;
    --project) dest="$(cd "$2" && pwd)/.claude/skills/handoff"; shift ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

command -v python3 >/dev/null || echo "warning: python3 not found on PATH; the skill's scripts need it" >&2

mkdir -p "$(dirname "$dest")"
if [ -e "$dest" ] || [ -L "$dest" ]; then
  # Backups must live outside skills/, or Claude Code loads them as a second /handoff.
  backup="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skill-backups/handoff.$(date +%Y%m%d%H%M%S)"
  mkdir -p "$(dirname "$backup")"
  mv "$dest" "$backup"
  echo "existing install moved to $backup"
fi

if [ "$mode" = link ]; then
  ln -s "$src" "$dest"
else
  cp -R "$src" "$dest"
fi
chmod +x "$dest"/scripts/*.py
echo "installed ($mode): $dest"
echo "restart Claude Code (or open a new session), then type /handoff"
