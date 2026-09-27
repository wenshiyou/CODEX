# -*- coding: utf-8 -*-
"""修复：VK_SPACE未定义，改成VK_JUMP(=0x20)"""
import io
fp = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(fp, 'r', encoding='utf-8', newline='') as f:
    src = f.read()
old = "_kj = bool(key_pressed(VK_SPACE))  # 跳"
new = "_kj = bool(key_pressed(VK_JUMP))  # 跳"
assert old in src, "VK_SPACE锚点未找到"
src = src.replace(old, new, 1)
with io.open(fp, 'w', encoding='utf-8', newline='') as f:
    f.write(src)
print("修复完成：VK_SPACE -> VK_JUMP")
