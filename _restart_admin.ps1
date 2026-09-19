$ErrorActionPreference = 'Continue'
$wd = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
$py = 'E:\conda\envs\yolo26\python.exe'
# 1) 结束任何持有单实例锁的旧 python(maple_route_ui)
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*maple_route_ui*' } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }
Start-Sleep -Seconds 2
# 2) 提权 + cmd /c 重定向启动(Start-Process -Redirect 在提权上下文不可靠)
$cmd = '"' + $py + '" -u "' + $wd + '\maple_route_ui.py" 1>"' + $wd + '\_v2_out3.log" 2>"' + $wd + '\_v2_err3.log"'
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cmd -WorkingDirectory $wd
"relaunched at $(Get-Date)" | Out-File "$wd\_restart.log" -Encoding utf8
