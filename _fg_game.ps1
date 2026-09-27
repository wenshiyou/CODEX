Add-Type @"
using System;using System.Runtime.InteropServices;
public class FG{
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int c);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a,uint b,bool f);
}
"@
$out='C:\Users\wenwen\Desktop\MXD\maple_bot_v2\_fg_out.txt'
$p = Get-Process msw -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if(-not $p){ "NO_GAME_WINDOW" | Out-File $out -Encoding UTF8; return }
$h=$p.MainWindowHandle
[FG]::ShowWindow($h,9) | Out-Null
$fg=[FG]::GetForegroundWindow()
$pa=0;$pb=0
$ta=[FG]::GetWindowThreadProcessId($fg,[ref]$pa)
$tb=[FG]::GetWindowThreadProcessId($h,[ref]$pb)
[FG]::AttachThreadInput($tb,$ta,$true) | Out-Null
$ok=[FG]::SetForegroundWindow($h)
[FG]::AttachThreadInput($tb,$ta,$false) | Out-Null
Start-Sleep -Milliseconds 600
$now=[FG]::GetForegroundWindow()
("SET_OK="+$ok+" NOW_FOREGROUND="+($now -eq $h)+" HWND="+$h) | Out-File $out -Encoding UTF8
