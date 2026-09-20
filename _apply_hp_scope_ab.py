# -*- coding: utf-8 -*-
"""修正:判活血条区域=A怪物基点X±35(Y在人物上方150px) ∪ B人物技能范围(人物X±skill_range,Y向上150px)。
血条落A或B任一=打着怪/怪活着。combat_logic(无BOM/LF),唯一锚点assert。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"
with io.open(CP, "r", encoding="utf-8", newline="") as f:
    s = f.read()
assert "\r\n" not in s

old = (
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
new = (
"    # 用户2026-09-20定稿:判活血条区域=两部分并集。A=怪物基点X±35(Y在人物上方150px内,血条在怪头顶);\n"
"    # B=人物技能范围(人物X±skill_range,Y向上150px)。血条落A或B任一=打着怪/怪活着。\n"
"    has_hp = False\n"
"    if lock:\n"
"        for (bx, by, bw, bh) in hp_bars:\n"
"            bxc = bx + bw / 2\n"
"            byc = by + bh / 2\n"
"            in_y = (py - 150) <= byc <= py\n"
"            in_a = abs(bxc - lcx) < 35 and in_y           # A:怪物基点X±35\n"
"            in_b = abs(bxc - px) <= skill_range and in_y   # B:人物技能范围\n"
"            if in_a or in_b:\n"
"                has_hp = True\n"
"                break\n"
)
assert s.count(old) == 1, "锚点命中%d次" % s.count(old)
s = s.replace(old, new)
with io.open(CP, "w", encoding="utf-8", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("HPSCOPE_AB_OK")
