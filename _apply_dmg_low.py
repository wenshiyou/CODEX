# -*- coding: utf-8 -*-
"""保留放宽搜索区(±50/70);颜色门槛降低:数字是红橙黄渐变多种色,检测到一部分就算。
n_red 60→35、n_org 50→25。maple(utf-8-sig/LF),唯一锚点assert。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(CP, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()

old = (
"        n_red, n_org = int(np.sum(m_red > 0)), int(np.sum(m_org > 0))\n"
"        if n_red < 60 or n_org < 50:\n"
"            return False  # 红簇不足=暖色背景/绿血条，不是伤害数字\n"
)
new = (
"        n_red, n_org = int(np.sum(m_red > 0)), int(np.sum(m_org > 0))\n"
"        # 用户2026-09-20:伤害数字红橙黄渐变多种色,检测到一部分就算;门槛60/50→35/25\n"
"        if n_red < 35 or n_org < 25:\n"
"            return False  # 红簇不足=暖色背景/绿血条，不是伤害数字\n"
)
assert s.count(old) == 1, "门槛锚点命中%d" % s.count(old)
s = s.replace(old, new)
with io.open(CP, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("DMG_THRESH_LOW_OK")
