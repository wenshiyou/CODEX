@echo off
chcp 65001 >nul
cd /d "C:\Users\wenwen\Desktop\MXD\maple_bot"
echo ================================================
echo   MapleBot crash-capture mode
echo   PYTHONFAULTHANDLER=1 : C层硬崩也打印Python栈
echo   输出同时显示在本窗口并写入 crash_capture.log
echo ================================================
echo.
set PYTHONFAULTHANDLER=1
set PYTHONUNBUFFERED=1
E:\conda\envs\yolo26\python.exe -u maple_route_ui.py 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath crash_capture.log"
echo.
echo ================================================
echo   Script finished. 崩溃栈见 crash_capture.log
echo ================================================
pause
