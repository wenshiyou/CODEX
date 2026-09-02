@echo off
cd /d "%~dp0"
echo ==========================================
echo   MapleBot scroll test: let character move RIGHT
echo   Then check cumulative dx and press q / Ctrl+C
echo ==========================================
py temp\test_scroll.py
pause
