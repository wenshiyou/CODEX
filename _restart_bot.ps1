$ErrorActionPreference = 'SilentlyContinue'
$py = 'E:\conda\envs\yolo26\python.exe'
$wd = 'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
# 1) kill old bot python: 提权后命令行可读, 精确匹配脚本; 回退按窗口标题(不写死PID)
$targets = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*maple_route_ui.py*' }
if ($targets) {
    $targets | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
} else {
    Get-Process python,pythonw | Where-Object { $_.MainWindowTitle -eq 'PLAY AND HAPPY' } | Stop-Process -Force
}
Start-Sleep -Milliseconds 1500
# 2) 在项目目录重启(继承工作目录, 保证 data/ 与 debug.log 相对路径正确)
Start-Process -FilePath $py -ArgumentList 'maple_route_ui.py' -WorkingDirectory $wd
