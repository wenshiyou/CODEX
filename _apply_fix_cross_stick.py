# -*- coding: utf-8 -*-
"""根因修复:同层模式脱检误判cross呆住。
combat(无BOM): select脱检分支的cross续命加allow_cross门控,并删掉cur_cross自比恒真条件;
maple(带BOM): combat_step的cur_cross实参从当前锁_bl改为None(同层不续cross)。
全内存+唯一断言,失败不写回。"""
import io, py_compile

# ---------- combat_logic.py (无BOM) ----------
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"
with io.open(CP, "r", encoding="utf-8", newline="") as f:
    c = f.read()
assert "\r\n" not in c

s_anchor = "            # 锁定目标本帧从怪表脱检。cross 例外保留同层同侧粘滞"
e_anchor = "                           cross, tier='cross')\n"
assert c.count(s_anchor) == 1, "脱检注释锚点%d次" % c.count(s_anchor)
si = c.index(s_anchor)
assert e_anchor in c[si:], "脱检cross返回终点缺失"
ei = c.index(e_anchor, si) + len(e_anchor)
assert "cur_cross is not None" in c[si:ei], "区间不含恒真条件,定位错"
new_block = (
"            # 锁定目标本帧从怪表脱检(YOLO漏帧/特效遮挡/硬裁)。纯最近(2026-09-20):一律落函数尾pick从当帧真实怪表重选最近,\n"
"            # 表空=idle,绝不沿旧坐标续命(治:近身怪漏一帧被误判cross→跨层状态机呆住不打、背景怪被钉着不换)。\n"
"            # 仅跨层模式allow_cross=True且上帧确为cross tier才续cross给梯子状态机;同层模式(False)一律不续。\n"
"            if allow_cross and lock_tier == 'cross':\n"
"                return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px),\n"
"                           cross, tier='cross')\n"
)
c = c[:si] + new_block + c[ei:]

# 同层模式残余断言:脱检分支不得再有 cur_cross 自比续命
assert "cur_cross is not None and" not in c, "cur_cross自比续命未删净"
with io.open(CP, "w", encoding="utf-8", newline="") as f:
    f.write(c)
py_compile.compile(CP, doraise=True)

# ---------- maple_route_ui.py (带BOM) ----------
MP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(MP, "r", encoding="utf-8-sig", newline="") as f:
    m = f.read()
assert "\r\n" not in m
old_arg = "            self._b_lock_time, self._b_hp_confirmed, self._b_gone, _bl,\n"
new_arg = ("            self._b_lock_time, self._b_hp_confirmed, self._b_gone, None,  "
           "# cur_cross同层传None:脱检不续cross(此前错传当前锁_bl致续命条件恒真→漏帧误cross呆住);未来跨层才传真cross目标\n")
assert m.count(old_arg) == 1, "cur_cross实参锚点%d次" % m.count(old_arg)
m = m.replace(old_arg, new_arg)
with io.open(MP, "w", encoding="utf-8-sig", newline="") as f:
    f.write(m)
py_compile.compile(MP, doraise=True)
print("CROSS_STICK_FIX_OK")
