# -*- coding: utf-8 -*-
"""has_hp改:基点=人物基点(px,py);X=人物X±技能范围skill_range,Y=人物Y向上150px;
这个人物攻击矩形内有血条=打着怪/怪活着。不再用锁怪±35/45(血条在头顶对不上锁怪坐标,附近血永远0)。
combat_logic.py(无BOM/LF),唯一锚点assert。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"
with io.open(CP, "r", encoding="utf-8", newline="") as f:
    s = f.read()
assert "\r\n" not in s

old = (
"    # 存活证据：目标附近是否有血条（收紧贴近度，避免附近怪的血条被算成目标的，导致空怪不drop）\n"
"    has_hp = False\n"
"    if lock:\n"
"        for (bx, by, bw, bh) in hp_bars:\n"
"            if abs((bx + bw / 2) - lcx) < 35 and abs((by + bh / 2) - lcy) < 45:\n"
"                has_hp = True\n"
"                break\n"
)
new = (
"    # 用户2026-09-20定稿:判活基点=人物基点(px,py);X=人物X±技能范围skill_range,Y=人物Y向上150px;\n"
"    # 这个人物攻击矩形内有血条=打着怪/怪活着。不再用锁怪±35/45(血条在怪头顶,对不上锁怪脚底/中心,附近血永远0)。\n"
"    has_hp = False\n"
"    if lock:\n"
"        for (bx, by, bw, bh) in hp_bars:\n"
"            bxc = bx + bw / 2\n"
"            byc = by + bh / 2\n"
"            if abs(bxc - px) <= skill_range and (py - 150) <= byc <= py:\n"
"                has_hp = True\n"
"                break\n"
)
assert s.count(old) == 1, "锚点命中%d次" % s.count(old)
s = s.replace(old, new)
with io.open(CP, "w", encoding="utf-8", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("HPSCOPE_OK")
