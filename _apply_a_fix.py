# -*- coding: utf-8 -*-
"""修正A的Y:A=怪物基点X±35,Y在【怪物基点上方150px】内(lcy-150≤byc≤lcy,血条在怪头顶);
B不变=人物技能范围(人物X±skill_range,Y人物上方150)。血条落A或B任一=打着怪/怪活着。
combat_logic(无BOM/LF),唯一锚点assert。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"
with io.open(CP, "r", encoding="utf-8", newline="") as f:
    s = f.read()
assert "\r\n" not in s

old = (
"            in_y = (py - 150) <= byc <= py\n"
"            in_a = abs(bxc - lcx) < 35 and in_y           # A:怪物基点X±35\n"
"            in_b = abs(bxc - px) <= skill_range and in_y   # B:人物技能范围\n"
"            if in_a or in_b:\n"
"                has_hp = True\n"
"                break\n"
)
new = (
"            in_a = abs(bxc - lcx) < 35 and (lcy - 150) <= byc <= lcy   # A:怪物基点X±35,Y在怪物上方150px\n"
"            in_b = abs(bxc - px) <= skill_range and (py - 150) <= byc <= py  # B:人物技能范围,Y在人物上方150px\n"
"            if in_a or in_b:\n"
"                has_hp = True\n"
"                break\n"
)
assert s.count(old) == 1, "锚点命中%d次" % s.count(old)
s = s.replace(old, new)
with io.open(CP, "w", encoding="utf-8", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("A_FIX_OK")
