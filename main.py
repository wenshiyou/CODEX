"""
2D横版游戏挂机助手 - 入口文件
用法: python main.py
"""
import sys
import os

# 确保项目根目录在 sys.path 中
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ui.main_window import run_app


if __name__ == "__main__":
    run_app()
