# python 闪退监视器(加固版)：每2秒看一次，python从有变无就记录；循环整体try，单次报错不退出
$log = "C:\Users\wenwen\Desktop\MXD\maple_bot\crash_watch.log"
Add-Content $log ("[监视器启动] " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
$had = [bool](Get-Process python -ErrorAction SilentlyContinue)
while ($true) {
  try {
    $p = Get-Process python -ErrorAction SilentlyContinue
    if ($had -and -not $p) {
      $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
      $cpu = (Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction SilentlyContinue).CounterSamples.CookedValue
      $fg = (Get-Process -ErrorAction SilentlyContinue | Where-Object {$_.MainWindowTitle} | Sort-Object MainWindowHandle -Descending | Select-Object -First 1)
      $fgName = if ($fg) { "$($fg.ProcessName): $($fg.MainWindowTitle)" } else { "(无前台窗口)" }
      $msw = Get-Process msw -ErrorAction SilentlyContinue
      $grap = Get-Process grap-core64.aes,NGS-X -ErrorAction SilentlyContinue
      Add-Content $log "[$now] ===python进程消失=== 当时整机CPU=$([math]::Round($cpu))% 前台=$fgName 游戏msw在=$([bool]$msw) 反作弊在=$([bool]$grap)"
      Get-WinEvent -FilterHashtable @{LogName='Application','System'; StartTime=(Get-Date).AddMinutes(-2); Level=1,2,3} -ErrorAction SilentlyContinue |
        Select-Object -First 6 | ForEach-Object {
          $m = $_.Message; if ($m.Length -gt 220) { $m = $m.Substring(0,220) }
          Add-Content $log ("  EVT[" + $_.TimeCreated + "] " + $_.ProviderName + ": " + ($m -replace "`r?`n"," "))
        }
    }
    $had = [bool]$p
  } catch {
    Add-Content $log ("[监视器自身异常,已忽略] " + (Get-Date -Format "HH:mm:ss") + " " + $_.Exception.Message)
  }
  Start-Sleep -Seconds 2
}
