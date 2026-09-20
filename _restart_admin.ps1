$ErrorActionPreference = 'Continue'
$wd = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
$py = 'E:\conda\envs\yolo26\python.exe'
# 1) 结束所有持有单实例锁的旧 python(maple_route_ui)
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*maple_route_ui*' } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }
Start-Sleep -Seconds 2
# 2) 直接提权启动(不经 cmd /c 重定向,避免子进程随控制台退出)
Start-Process -FilePath $py -ArgumentList ('"' + $wd + '\maple_route_ui.py"') -WorkingDirectory $wd
"relaunched at $(Get-Date)" | Out-File "$wd\_restart.log" -Encoding utf8
