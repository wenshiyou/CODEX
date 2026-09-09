# ============================================================
# MapleBot Full Snapshot Backup Script
# Packs all recoverable files into backup\snapshot_<timestamp>\
# Each run creates a NEW timestamped dir; NEVER overwrites old ones.
# Usage: powershell -ExecutionPolicy Bypass -File full_snapshot.ps1
# ============================================================

$root = $PSScriptRoot
if ([string]::IsNullOrEmpty($root)) { $root = "C:\Users\wenwen\Desktop\MXD\maple_bot" }

$backupBase = Join-Path $root "backup"
if (-not (Test-Path $backupBase)) { New-Item -ItemType Directory -Path $backupBase -Force | Out-Null }

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$destDir = Join-Path $backupBase ("snapshot_" + $timestamp)
if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }

Write-Host "=== Full snapshot to: $destDir ==="

# 1. Source files
$srcFiles = @("maple_route_ui.py", "main.py", "requirements.txt", ".gitignore",
              "README.md", "BUILD_GUIDE.md", "CODING_STANDARDS.md", "PROJECT_STATE.md",
              "xiao_dibao_rate.md")
foreach ($f in $srcFiles) {
    $p = Join-Path $root $f
    if (Test-Path $p) { Copy-Item $p $destDir -Force }
}

# 2. Whole dirs
foreach ($d in @("config", "data", "core", "ui", "utils")) {
    $p = Join-Path $root $d
    if (Test-Path $p) { Copy-Item $p $destDir -Recurse -Force }
}

# 3. exe
if (Test-Path (Join-Path $root "dist\MapleBot.exe")) {
    New-Item -ItemType Directory -Path (Join-Path $destDir "dist") -Force | Out-Null
    Copy-Item (Join-Path $root "dist\MapleBot.exe") (Join-Path $destDir "dist") -Force
}

# 4. log
if (Test-Path (Join-Path $root "dist\debug.log")) {
    if (-not (Test-Path (Join-Path $destDir "dist"))) { New-Item -ItemType Directory -Path (Join-Path $destDir "dist") -Force | Out-Null }
    Copy-Item (Join-Path $root "dist\debug.log") (Join-Path $destDir "dist") -Force
}

# 5. loose root files (scripts/deps/config/docs)
Get-ChildItem $root -File | Where-Object { $_.Extension -in ".py", ".json", ".spec", ".bat", ".vbs", ".ps1", ".txt", ".md" } | ForEach-Object {
    Copy-Item $_.FullName $destDir -Force
}

$size = (Get-ChildItem $destDir -Recurse -File | Measure-Object Length -Sum).Sum
$count = (Get-ChildItem $destDir -Recurse -File | Measure-Object).Count
Write-Host ("=== Done: {0} files, {1:N1} MB -> {2} ===" -f $count, ($size/1MB), $destDir)
Write-Host "(new timestamped dir; no old snapshot overwritten)"
