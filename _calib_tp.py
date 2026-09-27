# -*- coding: utf-8 -*-
# 从 debug.log 尾部标定:一次水平瞬移在【数据坐标(FIXED_W=340)】里光点实际移动多少,
# 配合屏幕瞬移距离(面板250/实测)求 数据/屏幕 系数,替代在放大显示窗量的不可靠值。
import io, os, re, time
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
print("size", os.path.getsize(P), "mtime", time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(P))))
lines = io.open(P, encoding='utf-8', errors='ignore').read().splitlines()
print("total_lines", len(lines))
tp = [l for l in lines if '瞬移追怪' in l]
dot = [l for l in lines if '光点' in l]
print("tp_count", len(tp), "dot_count", len(dot))
print("--- last 8 TP ---")
for l in tp[-8:]:
    print(l[-220:])
print("--- last 12 DOT ---")
for l in dot[-12:]:
    print(l[-180:])
