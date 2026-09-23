# -*- coding: utf-8 -*-
# 只读排查：上小地图梯子时，是否计算了"梯底Y 与 光点Y 的距离"，阈值多少、在哪判。
import io, re
p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
L = io.open(p, "rb").read().decode("utf-8-sig").replace("\r\n", "\n").split("\n")

def line_no(sub):
    return [i for i, x in enumerate(L) if sub in x]

print("=== 小地图选梯/上梯相关函数定义 ===")
for i, x in enumerate(L):
    s = x.strip()
    if re.match(r"def (_pick_ladder|_ladder_mm|_pin_ladder|_enter_to_ladder|_climb)", s):
        print(i + 1, ":", s[:120])

print("\n=== 含 梯底/底端/y_bottom/y_bot/'bot' 的行 ===")
for i, x in enumerate(L):
    s = x.strip()
    if ("梯底" in x or "底端" in x or "y_bottom" in x or "y_bot" in x
            or re.search(r"['\"]bot['\"]", x) or "bottom" in x.lower()):
        if "ladder" in x.lower() or "梯" in x or "bot" in x.lower() or "bottom" in x.lower():
            print(i + 1, ":", s[:150])
