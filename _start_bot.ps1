$ErrorActionPreference = 'Continue'
$py  = 'E:\conda\envs\yolo26\python.exe'
$wd  = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
$log = Join-Path $wd 'debug.log'

$base = 0
if (Test-Path $log) { $base = (Get-Content $log -Encoding UTF8 | Measure-Object -Line).Lines }
Write-Output ("BASE_LINES=" + $base)

try {
    Start-Process -FilePath $py -ArgumentList 'maple_route_ui.py' -WorkingDirectory $wd -Verb RunAs
    Write-Output "UAC_TRIGGERED"
} catch {
    Write-Output ("UAC_ERR=" + $_.Exception.Message)
    exit 0
}

$proc = $null
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 2
    $proc = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue
    if ($proc) { break }
}
if (-not $proc) { Write-Output "NO_PYTHON_90S"; exit 0 }
Write-Output ("PYTHON_UP pids=" + (($proc | Select-Object -Expand ProcessId) -join ','))
Start-Sleep -Seconds 16

Write-Output "===== KEY DIAG (tail) ====="
Get-Content $log -Encoding UTF8 -Tail 200 |
    Select-String 'window fixed|target|client|role track|light dot|capture cost|person cost|FPS|draw|busy|exception|Traceback|unbind|' |
    Select-Object -Last 5 | ForEach-Object { $_.Line }
Get-Content $log -Encoding UTF8 -Tail 200 |
    Select-String '窗口固定诊断|窗口绑定|角色跟踪|光点锁定|截图耗时|人物耗时|FPS统计|draw分段|忙帧|未绑定|客户区|异常|Traceback' |
    Select-Object -Last 55 | ForEach-Object { $_.Line }
