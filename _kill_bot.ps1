# 提权:精确杀掉maple_route_ui的python进程
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*maple_route_ui*' } |
    ForEach-Object { taskkill /PID $_.ProcessId /F /T | Out-Null }
Start-Sleep -Seconds 2
$left = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*maple_route_ui*' }
if ($left) { Write-Output ("STILL_UP=" + ($left.ProcessId -join ',')) } else { Write-Output "KILLED_ALL" }
