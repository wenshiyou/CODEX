$ErrorActionPreference = 'SilentlyContinue'
$py = 'E:\conda\envs\yolo26\python.exe'
$wd = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
# 1) kill old admin bot python: prefer exact command-line match (readable once elevated), fallback known PID 10124
$targets = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*maple_route_ui.py*' }
if ($targets) {
    $targets | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
} else {
    Stop-Process -Id 10124 -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 1500
# 2) start new build elevated, correct working directory
Start-Process -FilePath $py -ArgumentList 'maple_route_ui.py' -WorkingDirectory $wd
