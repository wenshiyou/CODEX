# -*- coding: utf-8 -*-
"""B的X改回:|血条中心X-人物基点X| <= 技能范围(不写减号坐标);Y不变(py-150≤byc≤py)。
A保持区间写法。combat_logic(无BOM/LF)。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"
with io.open(CP, "r", encoding="utf-8", newline="") as f:
    s = f.read()
assert "\r\n" not in s

old = (
"            in_b = (px - skill_range) <= bxc <= (px + skill_range) and (py - 150) <= byc <= py  # B:人物X前~后各技能范围,Y人物上方150\n"
)
new = (
"            in_b = abs(bxc - px) <= skill_range and (py - 150) <= byc <= py  # B:血条中心X离人物基点X不超过技能范围,Y人物上方150\n"
)
assert s.count(old) == 1, "锚点命中%d" % s.count(old)
s = s.replace(old, new)
with io.open(CP, "w", encoding="utf-8", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("B_X_ABS_OK")
