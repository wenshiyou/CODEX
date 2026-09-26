$ErrorActionPreference = 'Continue'
$dir = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
$log = Join-Path $dir '_restart_elev.txt'
("start " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) | Out-File $log -Encoding UTF8
$old = Get-Process -Id 5600 -ErrorAction SilentlyContinue
if ($old) {
    try { Stop-Process -Id 5600 -Force -ErrorAction Stop; Start-Sleep -Seconds 2; "killed old 5600" | Out-File $log -Append -Encoding UTF8 }
    catch { ("kill fail: " + $_.Exception.Message) | Out-File $log -Append -Encoding UTF8 }
} else {
    "old 5600 not running" | Out-File $log -Append -Encoding UTF8
}
try {
    Start-Process -FilePath 'E:\conda\envs\yolo26\python.exe' -ArgumentList 'maple_route_ui.py' -WorkingDirectory $dir
    "started new bot (elevated)" | Out-File $log -Append -Encoding UTF8
} catch {
    ("start fail: " + $_.Exception.Message) | Out-File $log -Append -Encoding UTF8
}
"end" | Out-File $log -Append -Encoding UTF8
