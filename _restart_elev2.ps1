$ErrorActionPreference = 'Continue'
$dir = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
$log = Join-Path $dir '_restart_elev2.txt'
("start " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) | Out-File $log -Encoding UTF8
# 按命令行匹配 maple_route_ui.py 的 python 进程(不写死PID),提权下结束
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*maple_route_ui.py*' }
if ($procs) {
    foreach ($p in $procs) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; ("killed pid " + $p.ProcessId) | Out-File $log -Append -Encoding UTF8 }
        catch { ("kill fail " + $p.ProcessId + ": " + $_.Exception.Message) | Out-File $log -Append -Encoding UTF8 }
    }
} else {
    "no old bot" | Out-File $log -Append -Encoding UTF8
}
Start-Sleep -Seconds 2
try {
    Start-Process -FilePath 'E:\conda\envs\yolo26\python.exe' -ArgumentList 'maple_route_ui.py' -WorkingDirectory $dir
    "started new bot (elevated)" | Out-File $log -Append -Encoding UTF8
} catch {
    ("start fail: " + $_.Exception.Message) | Out-File $log -Append -Encoding UTF8
}
"end" | Out-File $log -Append -Encoding UTF8
