# 提权重启:精确杀掉maple_route_ui进程,再启动新版(继承管理员)。
$py = 'E:\conda\envs\yolo26\python.exe'
$wd = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*maple_route_ui*' } |
    ForEach-Object { taskkill /PID $_.ProcessId /F /T | Out-Null }
Start-Sleep -Seconds 2
Start-Process -FilePath $py -ArgumentList 'maple_route_ui.py' -WorkingDirectory $wd
Start-Sleep -Seconds 3
$up = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*maple_route_ui*' }
if ($up) { Write-Output ("NEW_PID=" + ($up.ProcessId -join ',')) } else { Write-Output "NOT_UP" }
