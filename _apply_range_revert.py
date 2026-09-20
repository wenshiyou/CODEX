# -*- coding: utf-8 -*-
"""回滚搜索区放宽(用户2026-09-20:不动范围,只换颜色):±50→±30X、头顶上方70→50Y改回原值。
只保留红橙渐变颜色调整。maple(utf-8-sig/LF),唯一锚点assert。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(CP, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()

new1_now = (
"        # 用户2026-09-20按新样本重新取样:伤害数字是红橙渐变大字(99红/137黄),又大又飘高;搜索区放宽±30→±50X、头顶上方50→70Y\n"
"        rx1 = max(0, target_cx - 50)\n"
"        rx2 = min(w, target_cx + 50)\n"
"        ry1 = max(0, target_y1 - 70)  # 头顶上方70px\n"
"        ry2 = min(h, target_y1 + 5)   # 包含头顶位置\n"
)
orig = (
"        # 搜索区域：限定在目标头顶附近(±30px，垂直头顶-50~+5)，别把附近怪/背景的误判成伤害数字(用户2026-09-05)\n"
"        rx1 = max(0, target_cx - 30)\n"
"        rx2 = min(w, target_cx + 30)\n"
"        ry1 = max(0, target_y1 - 50)  # 头顶上方50px\n"
"        ry2 = min(h, target_y1 + 5)   # 包含头顶位置\n"
)
assert s.count(new1_now) == 1, "放宽段命中%d" % s.count(new1_now)
s = s.replace(new1_now, orig)
with io.open(CP, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("RANGE_REVERT_OK")
