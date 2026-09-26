$ErrorActionPreference = 'Continue'
$wd  = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
$py  = 'E:\conda\envs\yolo26\python.exe'
$res = Join-Path $wd '_restart_result.txt'
Set-Content -Path $res -Value ("start " + (Get-Date -Format 'HH:mm:ss')) -Encoding ASCII

$killed = @()
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | ForEach-Object {
    if ($_.CommandLine -and $_.CommandLine -like '*maple_route_ui.py*') {
        taskkill /F /PID $_.ProcessId 2>&1 | Out-Null
        $killed += $_.ProcessId
    }
}
Start-Sleep -Seconds 2
Add-Content -Path $res -Value ("killed=" + ($killed -join ',')) -Encoding ASCII

Start-Process -FilePath $py -ArgumentList 'maple_route_ui.py' -WorkingDirectory $wd
Start-Sleep -Seconds 4
$up = (Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
       Where-Object { $_.CommandLine -like '*maple_route_ui.py*' } |
       ForEach-Object { $_.ProcessId }) -join ','
Add-Content -Path $res -Value ("started=" + $up + " at " + (Get-Date -Format 'HH:mm:ss')) -Encoding ASCII
