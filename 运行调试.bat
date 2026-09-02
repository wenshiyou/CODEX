@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在以管理员权限启动 MapleBot...
echo 日志将输出到 debug_log.txt
:: 以管理员权限运行，工作目录设为当前目录，错误输出到文件
powershell -Command "Start-Process python -ArgumentList 'maple_route_ui.py' -Verb RunAs -WorkingDirectory '%~dp0' -RedirectStandardOutput '%~dp0debug_log.txt' -RedirectStandardError '%~dp0debug_err.txt'"
timeout /t 3 >nul
if exist debug_err.txt (
    echo === 错误日志 ===
    type debug_err.txt
)
pause
