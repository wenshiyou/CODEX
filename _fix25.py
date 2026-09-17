# -*- coding: utf-8 -*-
# 阶段cross: combat_logic.py 跨层判定改为用户2026-09-17定稿唯一条件(Y差>=200 且 X差<300)
import io, sys

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"
with io.open(P, "r", encoding="utf-8") as f:
    lines = f.readlines()

# 1) 定位并替换分桶块: 从 "_x_cross_line = skill_range" 行 到 该循环 "cross.append((x_gap, cx, cy))" 行
start = None
for i, ln in enumerate(lines):
    if ln.startswith("        _x_cross_line = skill_range"):
        start = i
        break
assert start is not None, "未找到 _x_cross_line 起始行"
end = None
for j in range(start, min(start + 20, len(lines))):
    if "cross.append((x_gap, cx, cy))" in lines[j]:
        end = j
        break
assert end is not None, "未找到分桶 cross.append 结束行"
old_block = "".join(lines[start:end + 1])
print("=== 待替换块 行%d-%d ===" % (start + 1, end + 1))
print(old_block)

new_block = (
"        # 【用户2026-09-17定稿·cross唯一条件,固定阈值百分百死守,不再用攻击Y带/X射程线/锁定滞回分桶】\n"
"        # ①X差>=300:再高也先pursue水平走近(走近后仍Y>=200才跨层);②abs(Y差)>=200且X<300:跳高也够不到=cross梯子/下跳;\n"
"        # ③其余(Y在攻击带~跳高可达,<200):原地打/跳高打/走近,一律cand。选定阶段cand优先、cand空才取cross=同层清空才上梯。\n"
"        if x_gap >= CROSS_X_MAX:\n"
"            cand.append((x_gap, cx, cy))   # X还很远,先水平走近,不判跨层\n"
"        elif abs(dy) >= CROSS_DY_MIN and allow_cross:\n"
"            cross.append((x_gap, cx, cy))  # 跳高也够不到、X<300=真要梯子/下跳\n"
"        else:\n"
"            cand.append((x_gap, cx, cy))   # Y差<200(攻击带/跳高可达):原地打或跳高打或走近\n"
)
lines[start:end + 1] = [new_block]

# 2) 加入两个常量(在 CROSS_X_HYST = 30 行之后)
text = "".join(lines)
anchor = "CROSS_X_HYST = 30\n"
assert text.count(anchor) == 1, "CROSS_X_HYST常量锚点不唯一/未找到: %d" % text.count(anchor)
const = (
"CROSS_X_HYST = 30\n"
"\n"
"# 【用户2026-09-17定稿·跨层(要梯子/下跳)唯一条件】跳高也够不到 且 X差不远:\n"
"# abs(Y差)>=CROSS_DY_MIN 且 X差<CROSS_X_MAX 才判cross;X差>=CROSS_X_MAX 再高也先水平走近;Y差<CROSS_DY_MIN(攻击带~跳高可达)原地/跳高打。\n"
"CROSS_DY_MIN = 200   # 跨层最小Y差:超过跳高上限、必须梯子/下跳(用户:Y差>=200)\n"
"CROSS_X_MAX = 300    # 跨层最大X差:X差>=300先pursue水平走近,靠近后仍Y>=200才跨层(用户:X差<300)\n"
)
text = text.replace(anchor, const, 1)

with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(text)
print("=== 写入完成 ===")
