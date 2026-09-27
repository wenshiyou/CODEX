$ErrorActionPreference='Continue'
$out = "C:\Users\wenwen\Desktop\MXD\maple_bot_v2\_restart_bypid.txt"
function log($m){ Add-Content -Path $out -Value $m -Encoding UTF8 }
Set-Content -Path $out -Value ("start " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
$old = 22888
$p = Get-Process -Id $old -ErrorAction SilentlyContinue
if ($p) {
    try { Stop-Process -Id $old -Force -ErrorAction Stop; log "killed pid $old" }
    catch { log "kill fail: $($_.Exception.Message)" }
} else { log "old pid $old not running" }
Start-Sleep -Milliseconds 1500
$still = Get-Process -Id $old -ErrorAction SilentlyContinue
log ("old still alive: " + [bool]$still)
$py = "E:\conda\envs\yolo26\python.exe"
$wd = "C:\Users\wenwen\Desktop\MXD\maple_bot_v2"
Start-Process -FilePath $py -ArgumentList "maple_route_ui.py" -WorkingDirectory $wd
log "new bot launch requested"
Start-Sleep -Seconds 7
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object {
    log ("after pid=" + $_.ProcessId + " start=" + $_.CreationDate)
}
log "end"
