$ErrorActionPreference = 'Continue'
Add-Type @"
using System;using System.Runtime.InteropServices;
public class K {
 [DllImport("user32.dll")] public static extern void keybd_event(byte k,byte s,uint f,IntPtr e);
}
"@
$wd  = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
$log = Join-Path $wd 'debug.log'
$out = Join-Path $wd '_f10_probe_out.txt'
if (Test-Path $out) { Remove-Item $out -Force }
function W($s){ $s | Out-File -FilePath $out -Encoding UTF8 -Append }
W ("START " + (Get-Date).ToString('HH:mm:ss'))

# F10 down/up (VK 0x79)
[K]::keybd_event(0x79,0,0,[IntPtr]::Zero)
Start-Sleep -Milliseconds 90
[K]::keybd_event(0x79,0,2,[IntPtr]::Zero)
W ("F10 sent " + (Get-Date).ToString('HH:mm:ss'))
Start-Sleep -Seconds 7

# safety F12 stop (VK 0x7B)
[K]::keybd_event(0x7B,0,0,[IntPtr]::Zero)
Start-Sleep -Milliseconds 90
[K]::keybd_event(0x7B,0,2,[IntPtr]::Zero)
W ("F12 sent " + (Get-Date).ToString('HH:mm:ss'))
Start-Sleep -Seconds 2

W "===== recent key/start/stop/perf lines ====="
Get-Content $log -Encoding UTF8 -Tail 320 |
    Select-String '热键|启动|停止|F10|F12|FPS统计|截图耗时|draw分段|忙帧|周期忙|随机|运行层|runtime|锁怪|cross|爬梯' |
    Select-Object -Last 70 | ForEach-Object { $_.Line } | Out-File -FilePath $out -Encoding UTF8 -Append
W ("END " + (Get-Date).ToString('HH:mm:ss'))
