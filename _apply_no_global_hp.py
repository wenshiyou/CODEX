# -*- coding: utf-8 -*-
"""删全局血条扫描(用户2026-09-20:打怪不是找人,没怪/扫不到也不要全屏,全屏血条是别的玩家打的无意义):
1)函数空区域不退化全屏,空就不扫;2)调用直接传_search不再None;3)日志'全局血'列名改'血条'(即范围内条数)。
maple(utf-8-sig/LF),唯一锚点assert。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(CP, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()

# 1.函数:空区域不退化全屏
old1 = "        areas = search_areas if search_areas else [(0, 0, w, h)]\n"
new1 = "        # 用户2026-09-20:删除全屏退化——没传区域/没怪就不扫,全屏血条多是别的玩家打的,无意义\n        areas = search_areas or []\n"
assert s.count(old1) == 1, "函数锚点%d" % s.count(old1)
s = s.replace(old1, new1)

# 2.调用:不再None全屏
old2 = "                        self._bars_cache = self._detect_monster_hp_bars(_frame, _search if _search else None)\n"
new2 = "                        self._bars_cache = self._detect_monster_hp_bars(_frame, _search)  # 用户2026-09-20:只扫技能范围内怪头顶,没怪_search=空→不扫\n"
assert s.count(old2) == 1, "调用锚点%d" % s.count(old2)
s = s.replace(old2, new2)

# 3.日志列名
old3 = '"[空怪诊断] 状态=%s 活着=%s drop=%s 伤害=%s 已出手=%s 确认血=%s | 锁怪=(%d,%d) 附近血=%d 全局血=%d"'
new3 = '"[空怪诊断] 状态=%s 活着=%s drop=%s 伤害=%s 已出手=%s 确认血=%s | 锁怪=(%d,%d) 血条数=%d"'
assert s.count(old3) == 1, "日志锚点%d" % s.count(old3)
s = s.replace(old3, new3)
old4 = "                _dl.get('attacked'), _dl.get('hp_confirmed'), t_cx, t_cy, _near_hp, len(self._monster_hp_bars)))\n"
new4 = "                _dl.get('attacked'), _dl.get('hp_confirmed'), t_cx, t_cy, len(self._monster_hp_bars)))\n"
assert s.count(old4) == 1, "日志参数锚点%d" % s.count(old4)
s = s.replace(old4, new4)

with io.open(CP, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("NO_GLOBAL_HP_OK")
