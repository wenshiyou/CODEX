$ErrorActionPreference = 'Continue'
$dir = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
$log = Join-Path $dir '_restart_elev3.txt'
"start " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | Out-File $log -Encoding UTF8

function Inv-Py($p) {
    $age = [int](New-TimeSpan -Start $p.CreationDate -End (Get-Date)).TotalSeconds
    $cmd = $p.CommandLine
    $path = $p.ExecutablePath
    $hitMap = ($false)
    if ($cmd -and $cmd -like '*maple_route_ui.py*') { $hitMap = $true }
    # 兜底:yolo26环境的python、已运行>20s、且命令行读不到(提权WMI偶发取不到)=判定为bot实例
    $hitFallback = ($false)
    if ($path -and $path -like '*yolo26*' -and $age -gt 20 -and [string]::IsNullOrEmpty($cmd)) { $hitFallback = $true }
    return [pscustomobject]@{ Pid=$p.ProcessId; Age=$age; Path=$path; Cmd=$cmd; HitMap=$hitMap; HitFb=$hitFallback }
}

$all = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'")
"--- python inventory BEFORE ---" | Out-File $log -Append -Encoding UTF8
$rows = foreach ($p in $all) { Inv-Py $p }
foreach ($r in $rows) {
    ("pid={0} age={1}s hitMap={2} hitFb={3} path={4} cmd={5}" -f $r.Pid,$r.Age,$r.HitMap,$r.HitFb,$r.Path,$r.Cmd) | Out-File $log -Append -Encoding UTF8
}
$targets = $rows | Where-Object { $_.HitMap -or $_.HitFb }
foreach ($r in $targets) {
    try { Stop-Process -Id $r.Pid -Force -ErrorAction Stop; ("killed pid " + $r.Pid) | Out-File $log -Append -Encoding UTF8 }
    catch { ("kill fail " + $r.Pid + ": " + $_.Exception.Message) | Out-File $log -Append -Encoding UTF8 }
}
if (-not $targets) { "no target bot process" | Out-File $log -Append -Encoding UTF8 }
Start-Sleep -Seconds 3
try {
    Start-Process -FilePath 'E:\conda\envs\yolo26\python.exe' -ArgumentList 'maple_route_ui.py' -WorkingDirectory $dir
    "started new bot (elevated)" | Out-File $log -Append -Encoding UTF8
} catch {
    ("start fail: " + $_.Exception.Message) | Out-File $log -Append -Encoding UTF8
}
Start-Sleep -Seconds 4
"--- python inventory AFTER ---" | Out-File $log -Append -Encoding UTF8
foreach ($p in @(Get-CimInstance Win32_Process -Filter "Name='python.exe'")) {
    $age = [int](New-TimeSpan -Start $p.CreationDate -End (Get-Date)).TotalSeconds
    ("pid={0} age={1}s path={2} cmd={3}" -f $p.ProcessId,$age,$p.ExecutablePath,$p.CommandLine) | Out-File $log -Append -Encoding UTF8
}
"end" | Out-File $log -Append -Encoding UTF8
