$ErrorActionPreference = 'Continue'
$py  = 'E:\conda\envs\yolo26\python.exe'
$wd  = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
$log = Join-Path $wd 'debug.log'
$out = Join-Path $wd '_restart_verify_out.txt'
if (Test-Path $out) { Remove-Item $out -Force }

Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*maple_route_ui*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
Start-Process -FilePath $py -ArgumentList 'maple_route_ui.py' -WorkingDirectory $wd
Start-Sleep -Seconds 20

"===== AFTER LOGWRAP-CACHE PATCH (idle, " + (Get-Date).ToString('HH:mm:ss') + ") =====" | Out-File -FilePath $out -Encoding UTF8
Get-Content $log -Encoding UTF8 -Tail 400 |
    Select-String 'FPS统计|draw分段|截图耗时|人物耗时|窗口固定诊断' |
    Select-Object -Last 28 | ForEach-Object { $_.Line } |
    Out-File -FilePath $out -Encoding UTF8 -Append
