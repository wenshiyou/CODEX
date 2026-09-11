@echo off
chcp 65001 >nul
echo ========================================
echo   2D横版游戏挂机助手 - 打包脚本
echo ========================================
echo.

echo [1/3] 检查依赖...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo 依赖安装失败，请检查网络或手动安装
    pause
    exit /b 1
)

echo [2/3] 开始打包...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "MapleBot" ^
    --add-data "config;config" ^
    --add-data "data;data" ^
    --hidden-import ultralytics ^
    --hidden-import cv2 ^
    --hidden-import mss ^
    --hidden-import PyQt5 ^
    --hidden-import sklearn ^
    main.py

if %errorlevel% neq 0 (
    echo 打包失败！
    pause
    exit /b 1
)

echo [3/3] 打包完成！
echo.
echo 可执行文件位置: dist\MapleBot.exe
echo.
echo 注意:
echo   1. 将训练好的 YOLO 模型放到 data\models\best.pt
echo   2. 首次运行会在同目录生成 config 和 data 文件夹
echo   3. 如需修改配置，编辑 config\config.json
echo.
pause
