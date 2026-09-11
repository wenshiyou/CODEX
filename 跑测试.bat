@echo off
chcp 65001 >nul
cd /d "C:\Users\wenwen\Desktop\MXD\maple_bot"
echo ================================================
echo   MapleBot - Python test mode (no packaging)
echo   Close the old MapleBot.exe before this.
echo   Game window must be open.
echo ================================================
echo.
E:\conda\envs\yolo26\python.exe maple_route_ui.py
echo.
echo ================================================
echo   Script finished. Read the console output above.
echo   Press any key to close this window.
echo ================================================
pause
