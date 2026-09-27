#!/usr/bin/env bash
# Install or update the /handoff skill and its context-warning hooks.
#   ./install.sh                  pull latest, copy to ~/.claude/skills/handoff, add hooks
#   ./install.sh --link           symlink instead of copying (later updates: just git pull)
#   ./install.sh --project DIR    install into DIR/.claude/skills/handoff (hooks stay global)
#   ./install.sh --window N       context window in tokens (default 200000; 1M models: 1000000)
#   ./install.sh --warn 45,70     warning thresholds, % of the window (default 45,70)
#   ./install.sh --no-compact-hold   don't postpone the first auto-compaction
#   ./install.sh --no-hooks       skill only; also removes previously installed hooks
set -euo pipefail

repo="$(cd "$(dirname "$0")" && pwd)"
src="$repo/skills/handoff"
config="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
dest="$config/skills/handoff"
mode=copy
hooks=yes
hook_args=()

while [ $# -gt 0 ]; do
  case "$1" in
    --link) mode=link ;;
    --project) dest="$(cd "$2" && pwd)/.claude/skills/handoff"; shift ;;
    --window|--warn) hook_args+=("$1" "$2"); shift ;;
    --no-compact-hold) hook_args+=("$1") ;;
    --no-hooks) hooks=no ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

# Update first when run from a git clone. Failure (offline, local edits) is not fatal.
if [ -d "$repo/.git" ]; then
  git -C "$repo" pull --ff-only --quiet || echo "note: git pull failed; installing the current checkout" >&2
fi

mkdir -p "$(dirname "$dest")"
if [ -e "$dest" ] || [ -L "$dest" ]; then
  # Backups must live outside skills/, or Claude Code loads them as a second /handoff.
  backup="$config/skill-backups/handoff.$(date +%Y%m%d%H%M%S)"
  mkdir -p "$(dirname "$backup")"
  mv "$dest" "$backup"
  echo "previous install moved to $backup"
  # Every update makes a backup; keep only the newest 3.
  ls -1dt "$config"/skill-backups/handoff.* 2>/dev/null | tail -n +4 | while read -r old; do rm -rf "$old"; done
fi

if [ "$mode" = link ]; then
  ln -s "$src" "$dest"
else
  cp -R "$src" "$dest"
  rm -rf "$dest/scripts/__pycache__"
fi
chmod +x "$dest"/scripts/*.py "$dest"/scripts/py
echo "installed ($mode): $dest"

if [ "$hooks" = yes ]; then
  sh "$dest/scripts/py" hooks_install.py install ${hook_args[@]+"${hook_args[@]}"}
else
  sh "$dest/scripts/py" hooks_install.py uninstall
fi
echo "restart Claude Code (or the desktop app), then type /handoff"
