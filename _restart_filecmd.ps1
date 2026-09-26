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
$wd='C:\Users\wenwen\Desktop\MXD\maple_bot_v2'; $py='E:\conda\envs\yolo26\python.exe'; $out=Join-Path $wd '_restart_out.txt'
if(Test-Path $out){Remove-Item $out -Force}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*maple_route_ui*' } | ForEach-Object { try{ Stop-Process -Id $_.ProcessId -Force }catch{} }
Start-Sleep 2
Start-Process -FilePath $py -ArgumentList 'maple_route_ui.py' -WorkingDirectory $wd
Start-Sleep 16
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*maple_route_ui*' }
("NEW_PID="+($procs.ProcessId -join ',')) | Out-File $out -Encoding UTF8
# 置前游戏
$g = Get-Process msw -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if($g){ $h=$g.MainWindowHandle; [FG]::ShowWindow($h,9)|Out-Null; $fg=[FG]::GetForegroundWindow(); $pa=0;$pb=0; $ta=[FG]::GetWindowThreadProcessId($fg,[ref]$pa); $tb=[FG]::GetWindowThreadProcessId($h,[ref]$pb); [FG]::AttachThreadInput($tb,$ta,$true)|Out-Null; $ok=[FG]::SetForegroundWindow($h); [FG]::AttachThreadInput($tb,$ta,$false)|Out-Null; ("GAME_FOREGROUND="+$ok) | Out-File $out -Encoding UTF8 -Append }
Start-Sleep 2
"===== tail log =====" | Out-File $out -Encoding UTF8 -Append
Get-Content (Join-Path $wd 'debug.log') -Encoding UTF8 -Tail 8 | Out-File $out -Encoding UTF8 -Append
