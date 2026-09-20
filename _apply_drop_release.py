# -*- coding: utf-8 -*-
"""drop善后加松键:打完/空怪后,松战斗套(含面板设定攻击键,动态遍历_held_keys不写死)+巡路套全部键,
干净收势再进下一只。maple_route_ui.py(utf-8-sig保BOM/LF),唯一锚点assert,失败不写回。"""
import io, py_compile
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(P, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()
assert "\r\n" not in s

old = (
"            self._combat_exec_feedback = None\n"
"            self._rlog(\"怪无血条/无伤害(已死或假怪),放弃并重新锁怪\", LOG_RED)\n"
)
new = (
"            self._combat_exec_feedback = None\n"
"            # 用户2026-09-20:打完/空怪干净利落收势——松战斗套(动态遍历_held_keys=面板设定攻击键,不写死)+巡路套全部键,再进下一只\n"
"            self._release_combat_move()\n"
"            self._release_all_keys()\n"
"            self._rlog(\"怪无血条/无伤害(已死或假怪),放弃并重新锁怪\", LOG_RED)\n"
)
assert s.count(old) == 1, "锚点命中%d次" % s.count(old)
s = s.replace(old, new)
with io.open(P, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
py_compile.compile(P, doraise=True)
print("DROP_RELEASE_OK")
