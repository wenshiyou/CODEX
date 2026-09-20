# -*- coding: utf-8 -*-
"""回滚:范围和门槛全改回原值,只保留用户说的"红橙渐变"颜色这一处。
- 范围±50/70→±30/50原值;门槛35/25→80/70原值。颜色保留m_red 0-18、m_org 10-35。
maple(utf-8-sig/LF),唯一锚点assert。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(CP, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()

# 1.范围改回原值
old1 = (
"        # 用户2026-09-20按新样本重新取样:伤害数字是红橙渐变大字(99红/137黄),又大又飘高;搜索区放宽±30→±50X、头顶上方50→70Y\n"
"        rx1 = max(0, target_cx - 50)\n"
"        rx2 = min(w, target_cx + 50)\n"
"        ry1 = max(0, target_y1 - 70)  # 头顶上方70px\n"
"        ry2 = min(h, target_y1 + 5)   # 包含头顶位置\n"
)
new1 = (
"        # 搜索区域：限定在目标头顶附近(±30px，垂直头顶-50~+5)，别把附近怪/背景的误判成伤害数字(用户2026-09-05)\n"
"        rx1 = max(0, target_cx - 30)\n"
"        rx2 = min(w, target_cx + 30)\n"
"        ry1 = max(0, target_y1 - 50)  # 头顶上方50px\n"
"        ry2 = min(h, target_y1 + 5)   # 包含头顶位置\n"
)
assert s.count(old1) == 1, "范围锚点命中%d" % s.count(old1)
s = s.replace(old1, new1)

# 2.门槛改回原值80/70(颜色保留红橙渐变0-18/10-35)
old2 = (
"        n_red, n_org = int(np.sum(m_red > 0)), int(np.sum(m_org > 0))\n"
"        # 用户2026-09-20:伤害数字红橙黄渐变多种色,检测到一部分就算;门槛60/50→35/25\n"
"        if n_red < 35 or n_org < 25:\n"
"            return False  # 红簇不足=暖色背景/绿血条，不是伤害数字\n"
)
new2 = (
"        n_red, n_org = int(np.sum(m_red > 0)), int(np.sum(m_org > 0))\n"
"        if n_red < 80 or n_org < 70:\n"
"            return False  # 红簇不足=暖色背景/绿血条，不是伤害数字\n"
)
assert s.count(old2) == 1, "门槛锚点命中%d" % s.count(old2)
s = s.replace(old2, new2)

with io.open(CP, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("REVERT_TO_USER_SPEC_OK")
