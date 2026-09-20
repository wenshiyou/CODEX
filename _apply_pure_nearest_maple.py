# -*- coding: utf-8 -*-
"""maple_route_ui 纯最近锁怪清理(UTF-8带BOM/LF):
删 空怪黑名单+压制侧(两filter方法/B选怪删怪/主线怪表删怪/drop拉黑/abort拉黑压制/字段init)、
锁怪冻结(combat_step恒传False,保留_is_lock_frozen爬梯动作主权门控)、
预选怪next(B计算/packet键/调用参数)、蒙板黄框(绘制/yellow_pen/next_target/show_next/开关)。
保留: 判死drop(只放手不拉黑)、_note_phantom_drop空打二次日志、硬裁/metric、aoe群攻、爬梯主权门控。
全内存+唯一断言,失败不写回。"""
import io, py_compile

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(P, "r", encoding="utf-8-sig", newline="") as f:
    c = f.read()
assert "\r\n" not in c, "maple含CRLF,预期LF"

def rep(old, new, tag):
    global c
    assert c.count(old) == 1, "%s 锚点%d次" % (tag, c.count(old))
    c = c.replace(old, new)

def cut(s_anchor, e_anchor, tag, must_contain=None):
    global c
    assert c.count(s_anchor) == 1, "%s 起点%d次" % (tag, c.count(s_anchor))
    si = c.index(s_anchor)
    assert e_anchor in c[si:], "%s 终点缺失" % tag
    ei = c.index(e_anchor, si)
    if must_contain:
        assert must_contain in c[si:ei], "%s 区间不含%s" % (tag, must_contain)
    c = c[:si] + c[ei:]

def drop_lines(names, tag):
    global c
    before = c.count(names[0]) if names else 0
    ls = c.split("\n")
    keep = [ln for ln in ls if not any(n in ln for n in names)]
    c = "\n".join(keep)
    for n in names:
        assert n not in c, "%s 残留:%s" % (tag, n)

# ---- M-1 B选怪不再黑名单/压制删怪 ----
rep("_cand = self._phantom_filter_readonly(list(merged), px)",
    "_cand = list(merged)   # 纯最近(2026-09-20):不黑名单/不压制删怪,当帧检出全留,真假靠出手后无血无伤判死",
    "M1-B选怪不删怪")

# ---- M-2 主线怪表不再过滤 ----
rep("                            self._monsters = self._filter_dropped_phantoms(list(_rmons))",
    "                            self._monsters = list(_rmons)",
    "M2a-主线怪表不过滤(metric包)")
rep("                            self._monsters = self._filter_dropped_phantoms(list(self._raw_monsters))",
    "                            self._monsters = list(self._raw_monsters)",
    "M2b-主线怪表不过滤(裸表)")

# ---- M-3 物理删两个filter方法(到_merge_detections前) ----
cut("    def _filter_dropped_phantoms(self, monsters):",
    "    def _merge_detections(self, yolo_monsters, feature_monsters):",
    "M3-删两filter方法", must_contain="_phantom_filter_readonly")

# ---- M-4 drop善后不再拉黑(保留空打日志/清反馈) ----
old_m4 = ("        if _dl.get('drop'):\n"
          "            _dpos = _dl.get('drop_pos') or (t_cx, t_cy)\n"
          "            self._combat_dropped_phantoms.append((_dpos[0], _dpos[1], now))\n"
          "            self._note_phantom_drop('空怪')\n")
new_m4 = ("        if _dl.get('drop'):\n"
          "            self._note_phantom_drop('空怪')   # 纯最近(2026-09-20):判死只放手当帧重选,不再拉黑位置\n")
rep(old_m4, new_m4, "M4-drop不拉黑")

# ---- M-5 abort函数:不拉黑不压制,只清锁定松键 ----
NEW_ABORT = (
"    def _abort_unreachable_target(self, cx, cy, now, why=\"\"):\n"
"        # 防卡死:连续想走却走不动/跑跳仍上不去=目标打不到,放弃它;清锁定+移动相位+松键,下帧按纯最近重选。\n"
"        # (用户2026-09-20:不再把位置拉黑1秒、不再压制整侧3秒,避免同屏近怪被黑名单/压制吞掉导致有怪不锁。)\n"
"        self._combat_locked_target = None\n"
"        self._combat_target_attacked = False\n"
"        self._combat_first_strike_time = 0\n"
"        self._move_mon = None\n"
"        self._slope_phase = 'wait_jump'\n"
"        self._slope_next_at = 0\n"
"        self._slope_high_mode = False\n"
"        self._release_combat_move()\n"
"        self._slope_high_last_jump = 0\n"
"        _debug_log(\"[防卡死] 连续移动受阻(%s)，判定目标(%d,%d)打不到→放弃，下帧纯最近重选\" % (why or \"卡住\", cx, cy))\n"
"\n")
_s5 = "    def _abort_unreachable_target(self, cx, cy, now, why=\"\"):"
_e5 = "    def _single_home_platform(self):"
assert c.count(_s5) == 1 and c.count(_e5) == 1
c = c[:c.index(_s5)] + NEW_ABORT + c[c.index(_e5):]

# ---- M-6 锁怪冻结恒False(删_freeze局部;_is_lock_frozen爬梯主权门控保留) ----
rep("        _freeze = self._is_lock_frozen()\n", "", "M6a-删锁怪_freeze局部")
rep("freeze_lock=_freeze,", "freeze_lock=False,", "M6b-锁怪永不冻结")

# ---- M-7 删B线程预备怪next计算块 + packet的next键 ----
cut("        # 备胎next给蒙板黄框",
    "        self._combat_decision_packet = {",
    "M7a-删next计算块", must_contain="pick_next")
rep("            'group': _dl.get('group'), 'next': _nxt,\n",
    "            'group': _dl.get('group'),\n",
    "M7b-packet删next键")

# ---- M-8 combat_step调用去 fallback_next ----
rep("same_platform_fn=None, metric=metric, fallback_next=None)",
    "same_platform_fn=None, metric=metric)",
    "M8-调用去fallback_next")

# ---- M-9 蒙板黄框全套删除 ----
rep("                                _next_p = data.get('next_target')\n", "", "M9a-删_next_p")
rep("                                yellow_pen = gdi32.CreatePen(0, 2, 0x00FFFF)\n", "", "M9b-删yellow画笔")
rep("                                if yellow_pen:\n", "", "M9c-删yellow判断")
rep("                                    gdi_objs.append(yellow_pen)\n", "", "M9d-删yellow入栈")
cut("                                # 预备怪next:黄色小空心框",
    "                                gdi32.SelectObject(hdc, old_pen)",
    "M9e-删黄框绘制块", must_contain="yellow_pen")
old_m9f = ('                    _dlpkt_o = getattr(self, \'_combat_decision_packet\', None)\n'
'                    self._monster_overlay_data["next_target"] = (_dlpkt_o.get(\'next\') if _dlpkt_o else None)\n'
'                    self._monster_overlay_data["show_next"] = bool(getattr(self, \'_show_next_candidate\', True))\n')
assert c.count(old_m9f) == 1, "M9f 下发块锚点%d次" % c.count(old_m9f)
c = c.replace(old_m9f, "")
rep('                self._monster_overlay_data["next_target"] = None\n', "", "M9g-删停机清next_target")

# ---- M-10 残余字段/开关init按行清扫(在定点删除之后,只剩init/注释) ----
drop_lines(['_combat_dropped_phantoms', '_combat_suppress_side'], "M10a-黑名单字段")
drop_lines(['_show_next_candidate'], "M10b-黄框开关")

# ==== 残留断言:黑科技清零 ====
for bad in ["_phantom_filter_readonly", "_filter_dropped_phantoms", "_combat_dropped_phantoms",
            "_combat_suppress_side", "pick_next", "fallback_next", "next_target", "show_next",
            "_show_next_candidate", "yellow_pen", "freeze_lock=_freeze",
            "        _freeze = self._is_lock_frozen()"]:
    assert bad not in c, "残留未清: %s" % bad
# ==== 必须保留项 ====
for keep in ["_is_lock_frozen", "_note_phantom_drop", "_phantom_streak",
             "freeze_lock=False", "allow_cross"]:
    assert keep in c, "误删保留项: %s" % keep

with io.open(P, "w", encoding="utf-8-sig", newline="") as f:
    f.write(c)
py_compile.compile(P, doraise=True)
py_compile.compile(r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py", doraise=True)
print("MAPLE_PURE_NEAREST_OK")
