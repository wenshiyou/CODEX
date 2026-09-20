# -*- coding: utf-8 -*-
"""cast锁死:当前锁怪脱检时,只要还活着(target_alive=True)就继续锁它打,不换新怪;
只有真死了(target_alive=False)才落pick重选。治纯最近每帧换怪→出手反馈对不上→判活门永远关。
combat_logic.py(无BOM/LF),唯一锚点assert,失败不写回。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"
with io.open(CP, "r", encoding="utf-8", newline="") as f:
    s = f.read()
assert "\r\n" not in s

old = (
"        else:\n"
"            # 锁定目标本帧从怪表脱检(YOLO漏帧/特效遮挡/硬裁)。纯最近(2026-09-20):一律落函数尾pick从当帧真实怪表重选最近,\n"
"            # 表空=idle,绝不沿旧坐标续命(治:近身怪漏一帧被误判cross→跨层状态机呆住不打、背景怪被钉着不换)。\n"
"            # 仅跨层模式allow_cross=True且上帧确为cross tier才续cross给梯子状态机;同层模式(False)一律不续。\n"
"            if allow_cross and lock_tier == 'cross':\n"
"                return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px),\n"
"                           cross, tier='cross')\n"
)
new = (
"        else:\n"
"            # 锁定目标本帧从怪表脱检(YOLO漏帧/特效遮挡/硬裁)。用户2026-09-20定稿:一旦进入攻击状态就只管打完——\n"
"            # 只要它还活着(target_alive=True=血条或伤害数字在),即使漏帧也继续锁它打,不换新怪(跳打/原地打都不打断);\n"
"            # 只有它真死了(target_alive=False=血条、伤害数字都没)才落pick锁下一只最近的。\n"
"            if target_alive:\n"
"                return _mk('cast', (target_cx, target_cy), _dir_to(target_cx, px),\n"
"                           abs(target_cx - px), tier='in')\n"
"            # 目标已死/空怪 → 落pick重选(表空=idle)。跨层预留:同层allow_cross=False不进。\n"
"            if allow_cross and lock_tier == 'cross':\n"
"                return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px),\n"
"                           cross, tier='cross')\n"
)
assert s.count(old) == 1, "锚点命中%d次" % s.count(old)
s = s.replace(old, new)
with io.open(CP, "w", encoding="utf-8", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("CAST_LOCK_OK")
