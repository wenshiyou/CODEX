$ErrorActionPreference = 'Continue'
$wd = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
$py = 'E:\conda\envs\yolo26\python.exe'
Set-Location $wd
# 清理可能残留的旧实例(仅 maple_route_ui)
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*maple_route_ui*' } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }
Start-Sleep -Seconds 2
# 提权环境下用 cmd /c 包裹并捕获全部输出, 闪退可在 _startup_capture.log 看到 Traceback
"===== relaunch(capture) at $(Get-Date) =====" | Out-File "$wd\_startup_capture.log" -Encoding utf8
cmd /c "`"$py`" `"$wd\maple_route_ui.py`" >> `"$wd\_startup_capture.log`" 2>&1"
