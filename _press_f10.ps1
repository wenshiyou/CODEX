$ErrorActionPreference = 'SilentlyContinue'
$sig = @'
[DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, System.UIntPtr dwExtraInfo);
'@
$u = Add-Type -Member $sig -Name KU -Namespace W -PassThru
# F10 vk=0x79 scan=0x44, 完整按下/抬起, bot用全局GetAsyncKeyState边沿检测
$u::keybd_event(0x79, 0x44, 0, [System.UIntPtr]::Zero)
Start-Sleep -Milliseconds 80
$u::keybd_event(0x79, 0x44, 2, [System.UIntPtr]::Zero)
Start-Sleep -Milliseconds 300
# 再补一次确保边沿被捕获
$u::keybd_event(0x79, 0x44, 0, [System.UIntPtr]::Zero)
Start-Sleep -Milliseconds 80
$u::keybd_event(0x79, 0x44, 2, [System.UIntPtr]::Zero)
