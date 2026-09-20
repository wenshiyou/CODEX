# -*- coding: utf-8 -*-
"""A/B血条匹配改成用户看得懂的区间写法(逻辑不变):
A: lcx-35≤bxc≤lcx+35 且 lcy-150≤byc≤lcy
B: px-skill_range≤bxc≤px+skill_range 且 py-150≤byc≤py
combat_logic(无BOM/LF),唯一锚点assert。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"
with io.open(CP, "r", encoding="utf-8", newline="") as f:
    s = f.read()
assert "\r\n" not in s

old = (
"            in_a = abs(bxc - lcx) < 35 and (lcy - 150) <= byc <= lcy   # A:怪物基点X±35,Y在怪物上方150px\n"
"            in_b = abs(bxc - px) <= skill_range and (py - 150) <= byc <= py  # B:人物技能范围,Y在人物上方150px\n"
)
new = (
"            in_a = (lcx - 35) <= bxc <= (lcx + 35) and (lcy - 150) <= byc <= lcy   # A:怪物基点X前35~后35,Y怪物上方150\n"
"            in_b = (px - skill_range) <= bxc <= (px + skill_range) and (py - 150) <= byc <= py  # B:人物X前~后各技能范围,Y人物上方150\n"
)
assert s.count(old) == 1, "锚点命中%d" % s.count(old)
s = s.replace(old, new)
with io.open(CP, "w", encoding="utf-8", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("RANGE_WRAP_OK")
