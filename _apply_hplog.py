# -*- coding: utf-8 -*-
"""[空怪诊断]日志加:锁怪坐标+锁怪附近±35X/±45Y匹配到的血条数(和combat_logic同容差)+全局血条数,
让用户一眼看出"全局血条多、锁怪附近匹配几条"。maple(utf-8-sig),唯一锚点assert。"""
import io, py_compile
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(P, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()
assert "\r\n" not in s

old = (
"            _debug_log(\"[空怪诊断] 状态=%s 活着=%s drop=%s 伤害=%s 已出手=%s 确认血=%s gone=%d 血条数=%d\" % (\n"
"                _dl['state'], _dl.get('alive'), _dl.get('drop'), _dl.get('has_dmg'),\n"
"                _dl.get('attacked'), _dl.get('hp_confirmed'), _dl.get('gone'), len(self._monster_hp_bars)))\n"
)
new = (
"            _near_hp = 0\n"
"            for (_bx,_by,_bw,_bh) in (self._monster_hp_bars or []):\n"
"                if abs((_bx+_bw/2)-t_cx) < 35 and abs((_by+_bh/2)-t_cy) < 45:\n"
"                    _near_hp += 1\n"
"            _debug_log(\"[空怪诊断] 状态=%s 活着=%s drop=%s 伤害=%s 已出手=%s 确认血=%s | 锁怪=(%d,%d) 附近血=%d 全局血=%d\" % (\n"
"                _dl['state'], _dl.get('alive'), _dl.get('drop'), _dl.get('has_dmg'),\n"
"                _dl.get('attacked'), _dl.get('hp_confirmed'), t_cx, t_cy, _near_hp, len(self._monster_hp_bars)))\n"
)
assert s.count(old) == 1, "锚点命中%d次" % s.count(old)
s = s.replace(old, new)
with io.open(P, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
py_compile.compile(P, doraise=True)
print("HPLOG_OK")
