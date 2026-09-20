# -*- coding: utf-8 -*-
"""伤害数字重新取样(用户样本"99红橙/137黄橙",红橙渐变大字):
1)搜索区放宽 ±30→±50X、头顶上方50→70Y(数字大飘高,原框框不住);
2)红橙渐变:红H0-18、橙黄H10-35连续;门槛n_red 80→60、n_org 70→50。
maple(utf-8-sig/LF),唯一锚点assert。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(CP, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()

old1 = (
"        # 搜索区域：限定在目标头顶附近(±30px，垂直头顶-50~+5)，别把附近怪/背景的误判成伤害数字(用户2026-09-05)\n"
"        rx1 = max(0, target_cx - 30)\n"
"        rx2 = min(w, target_cx + 30)\n"
"        ry1 = max(0, target_y1 - 50)  # 头顶上方50px\n"
"        ry2 = min(h, target_y1 + 5)   # 包含头顶位置\n"
)
new1 = (
"        # 用户2026-09-20按新样本重新取样:伤害数字是红橙渐变大字(99红/137黄),又大又飘高;搜索区放宽±30→±50X、头顶上方50→70Y\n"
"        rx1 = max(0, target_cx - 50)\n"
"        rx2 = min(w, target_cx + 50)\n"
"        ry1 = max(0, target_y1 - 70)  # 头顶上方70px\n"
"        ry2 = min(h, target_y1 + 5)   # 包含头顶位置\n"
)
assert s.count(old1) == 1, "区锚点命中%d" % s.count(old1)
s = s.replace(old1, new1)

old2 = (
"        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)\n"
"        m_red = cv2.inRange(hsv, np.array([0, 70, 70]),  np.array([12, 255, 255]))   # 红(描边/阴影)\n"
"        m_org = cv2.inRange(hsv, np.array([14, 70, 70]), np.array([35, 255, 255]))   # 橙黄(主体)\n"
"        n_red, n_org = int(np.sum(m_red > 0)), int(np.sum(m_org > 0))\n"
"        if n_red < 80 or n_org < 70:\n"
"            return False  # 红簇不足=暖色背景/绿血条，不是伤害数字\n"
)
new2 = (
"        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)\n"
"        m_red = cv2.inRange(hsv, np.array([0, 70, 70]),  np.array([18, 255, 255]))   # 红橙渐变(用户2026-09-20:0-12→0-18,覆盖99的橙红)\n"
"        m_org = cv2.inRange(hsv, np.array([10, 70, 70]), np.array([35, 255, 255]))  # 橙黄主体(137黄)\n"
"        n_red, n_org = int(np.sum(m_red > 0)), int(np.sum(m_org > 0))\n"
"        if n_red < 60 or n_org < 50:\n"
"            return False  # 红簇不足=暖色背景/绿血条，不是伤害数字\n"
)
assert s.count(old2) == 1, "阈锚点命中%d" % s.count(old2)
s = s.replace(old2, new2)

with io.open(CP, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("DMG_RESAMPLE_OK")
