@echo off
chcp 65001 >nul
cd /d C:\Users\wenwen\Desktop\MXD\maple_bot
echo ===== start %date% %time% ===== >> runtime_err.log
E:\conda\envs\yolo26\python.exe -u maple_route_ui.py 1>>runtime_out.log 2>>runtime_err.log
echo ===== exited code %errorlevel% %date% %time% ===== >> runtime_err.log
