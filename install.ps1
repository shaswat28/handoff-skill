<#
Install or update the /handoff skill and its context-warning hooks on Windows.

  powershell -ExecutionPolicy Bypass -File install.ps1 [options]

  -Window 1000000     context window in tokens (default 200000; 1M models: 1000000)
  -Warn 45,70         warning thresholds, % of the window (default 45,70)
  -NoCompactHold      don't postpone the first auto-compaction
  -NoHooks            skill only; also removes previously installed hooks
  -Project DIR        install into DIR\.claude\skills\handoff (hooks stay global)

Pulls the latest version first when run from a git clone, so re-running it is
also how you update. Written for Windows PowerShell 5.1 and PowerShell 7.
#>
param(
  [int]$Window = 200000,
  [string[]]$Warn = @("45", "70"),  # "-Warn 45,70" arrives as an array
  [switch]$NoCompactHold,
  [switch]$NoHooks,
  [string]$Project = ""
)
# Not "Stop": in PowerShell 5.1 that turns any stderr from git/python into a fatal error.
$ErrorActionPreference = "Continue"

$repo = $PSScriptRoot
$src = Join-Path $repo "skills/handoff"
if ($env:CLAUDE_CONFIG_DIR) { $config = $env:CLAUDE_CONFIG_DIR } else { $config = Join-Path $HOME ".claude" }
if ($Project) {
  $dest = Join-Path (Resolve-Path $Project).Path ".claude/skills/handoff"
} else {
  $dest = Join-Path $config "skills/handoff"
}

# 1. Update when run from a git clone. Failure (offline, local edits) is not fatal.
if ((Test-Path (Join-Path $repo ".git")) -and (Get-Command git -ErrorAction SilentlyContinue)) {
  git -C $repo pull --ff-only --quiet
  if ($LASTEXITCODE -ne 0) { Write-Warning "git pull failed; installing the current checkout" }
}

# 2. Find a real Python 3.8+. "python3"/"python" may be the Microsoft Store placeholder.
$py = $null
foreach ($candidate in @("py -3", "python", "python3")) {
  $parts = $candidate.Split(" ")
  if (-not (Get-Command $parts[0] -ErrorAction SilentlyContinue)) { continue }
  $rest = @($parts | Select-Object -Skip 1)
  & $parts[0] @rest -c "import sys; sys.exit(sys.version_info < (3, 8))" 2>$null | Out-Null
  if ($LASTEXITCODE -eq 0) { $py = $parts; break }
}
if (-not $py) {
  Write-Error "No Python 3.8+ found (tried py -3, python, python3). Install it from python.org, tick 'Add python.exe to PATH', then re-run."
  exit 1
}

# 3. Copy the skill. Backups go outside skills\, or Claude Code loads them as a second /handoff.
New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
if (Test-Path $dest) {
  $backup = Join-Path $config ("skill-backups/handoff." + (Get-Date -Format "yyyyMMddHHmmss"))
  New-Item -ItemType Directory -Force (Split-Path $backup) | Out-Null
  Move-Item $dest $backup
  Write-Host "previous install moved to $backup"
  # Every update makes a backup; keep only the newest 3.
  Get-ChildItem (Split-Path $backup) -Directory -Filter "handoff.*" | Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 3 | Remove-Item -Recurse -Force
}
Copy-Item -Recurse $src $dest
Remove-Item -Recurse -Force (Join-Path $dest "scripts/__pycache__") -ErrorAction SilentlyContinue

# 4. Force LF line endings. A CRLF checkout breaks scripts/py and /handoff then fails silently.
$utf8 = New-Object System.Text.UTF8Encoding($false)
Get-ChildItem -Recurse -File $dest | ForEach-Object {
  $text = [System.IO.File]::ReadAllText($_.FullName)
  if ($text.Contains("`r`n")) {
    [System.IO.File]::WriteAllText($_.FullName, $text.Replace("`r`n", "`n"), $utf8)
  }
}
Write-Host "installed (copy): $dest"

# 5. Hooks.
$installer = Join-Path $dest "scripts/hooks_install.py"
$pyRest = @($py | Select-Object -Skip 1)
if ($NoHooks) {
  $hookArgs = @("uninstall")
} else {
  $hookArgs = @("install", "--window", "$Window", "--warn", (($Warn -join ",") -replace "\s", ""))
  if ($NoCompactHold) { $hookArgs += "--no-compact-hold" }
}
& $py[0] @pyRest $installer @hookArgs
if ($LASTEXITCODE -ne 0) { Write-Warning "hooks were not installed (see message above)" }

Write-Host "restart Claude Code (or the desktop app), then type /handoff"
