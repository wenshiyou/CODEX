# -*- coding: utf-8 -*-
"""判活窗改 攻击后0~500ms、锚最近一击t(每按一次攻击重新计时)(用户2026-09-21定稿):
窗内血条或伤害数字任一=怪活着续打;满500ms两者皆无=换怪;不攻击不检测。
- maple _publish_combat_decision: 时间锚从 first(首击) 改为 t(最近一击), 窗 100~650 -> 0~500;
  伤害检测并入0~500窗; attacked=最近一击满500ms。探针无条件窗同步同锚同窗(验收时 gate_dmg 应==probe_dmg)。
- combat_logic.lock_status: 命中确认 hp_confirmed 由"仅血条"改为"血条或伤害数字任一"。"""
import io, ast

MP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
CL = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"

def patch(path, enc, reps):
    with io.open(path, "r", encoding=enc, newline="") as f:
        s = f.read()
    for old, new, tag in reps:
        c = s.count(old)
        assert c == 1, "锚点不唯一/缺失 [%s] count=%d" % (tag, c)
        s = s.replace(old, new)
    ast.parse(s)
    with io.open(path, "w", encoding=enc, newline="") as f:
        f.write(s)
    print("PATCHED", path)

# ============ maple_route_ui.py (utf-8-sig) ============
A1_old = (
"        _attacked = False\n"
"        _detect_open = False   # 出手100ms后开始看伤害数字(判死仍走500ms截止)\n"
"        _judge_pos = _bl       # 判活/保锁目标:默认当帧锁;出手反馈窗内=出手那只怪\n"
"        if _fb and _fb.get('pos') and _fb.get('first'):\n"
"            _fpos = _fb['pos']\n"
"            _first = _fb.get('first', 0) or 0\n"
"            _el = now_ms - _first\n"
"            if _first and now_ms >= _first and _el > POST_STRIKE_CHECK_MS:\n"
"                _detect_open = True\n"
"                _judge_pos = _fpos   # 窗内判活/保锁钉死出手怪,不要求±40/±50对齐\n"
"            if _first and now_ms >= _first and _el > STRIKE_DEADLINE_MS:\n"
"                _attacked = True\n"
"                _judge_pos = _fpos   # 满窗判死这一帧仍针对出手怪\n"
)
A1_new = (
"        _attacked = False\n"
"        _detect_open = False   # 攻击后0~500ms检测窗是否在窗内(探针日志用)\n"
"        _judge_pos = _bl       # 判活/保锁目标:默认当帧锁;攻击反馈窗内=最近一击那只怪\n"
"        _has_dmg = False\n"
"        # 判活(用户2026-09-21定稿):计时器与攻击同步,每按一次攻击用feedback.t重新计时;攻击后0~STRIKE_DEADLINE_MS(500ms)\n"
"        # 为检测窗,窗内血条(combat_step A∪B)或伤害数字任一=怪活着续锁续打;满500ms两者皆无=空怪/打死→drop换怪;不攻击(_fb无)不检测。\n"
"        if _fb and _fb.get('pos') and _fb.get('t'):\n"
"            _fpos = _fb['pos']\n"
"            _last_t = _fb.get('t', 0) or 0\n"
"            _el = now_ms - _last_t\n"
"            if _last_t and now_ms >= _last_t and 0 <= _el < STRIKE_DEADLINE_MS:\n"
"                _detect_open = True\n"
"                _judge_pos = _fpos   # 0~500窗内判活/保锁钉死最近一击那只怪,不要求对齐/射程\n"
"                try:\n"
"                    _has_dmg = self._detect_damage_number(_fpos[0], _fpos[1], frame=frame, monsters=merged)\n"
"                except Exception as _e:\n"
"                    _debug_log(\"[B决策] 伤害数字检测异常: %s\" % _e)\n"
"                    _has_dmg = False\n"
"            if _last_t and now_ms >= _last_t and _el >= STRIKE_DEADLINE_MS:\n"
"                _attacked = True    # 最近一击满500ms这一帧仍针对出手怪,血条/伤害皆无则lock_status判死drop\n"
"                _judge_pos = _fpos\n"
)

A2_old = (
"        _has_dmg = False\n"
"        # 伤害数字:窗内100~650ms对出手怪头顶检测(旧\"_in_skill且对齐\"两道门已删,移动/跳打/高处帧一样判活)\n"
"        if _detect_open and _judge_pos is not None and _fb and _fb.get('first') and (now_ms - (_fb.get('first') or 0)) < 650:\n"
"            try:\n"
"                _has_dmg = self._detect_damage_number(_judge_pos[0], _judge_pos[1], frame=frame, monsters=merged)\n"
"            except Exception as _e:\n"
"                _debug_log(\"[B决策] 伤害数字检测异常: %s\" % _e)\n"
"                _has_dmg = False\n"
)
A2_new = (
"        # 伤害数字已在上方攻击后0~500窗内对最近一击怪头顶检测(_has_dmg);此处不再另开检测(旧100~650/对齐/射程门全去)\n"
)

B_old = (
"            if _fposP and _fb.get('first'):\n"
"                _elP = now_ms - (_fb.get('first') or 0)\n"
"                if POST_STRIKE_CHECK_MS < _elP < 650:\n"
)
B_new = (
"            if _fposP and _fb.get('t'):\n"
"                _elP = now_ms - (_fb.get('t') or 0)\n"
"                if 0 <= _elP < STRIKE_DEADLINE_MS:\n"
)

patch(MP, "utf-8-sig", [
    (A1_old, A1_new, "A1_gate"),
    (A2_old, A2_new, "A2_dmg"),
    (B_old, B_new, "probe_window"),
])

# ============ combat_logic.py (utf-8 无BOM) ============
C1_old = (
"    if not can_strike:\n"
"        if has_hp and not hp_confirmed:\n"
"            hp_confirmed = True\n"
"        if attacked and (not hp_confirmed) and not has_hp and not has_dmg:\n"
)
C1_new = (
"    if not can_strike:\n"
"        if (has_hp or has_dmg) and not hp_confirmed:\n"
"            hp_confirmed = True\n"
"        if attacked and (not hp_confirmed) and not has_hp and not has_dmg:\n"
)
C2_old = (
"    # 首次检测到血条 = 攻击命中确认\n"
"    if has_hp and not hp_confirmed:\n"
"        hp_confirmed = True\n"
)
C2_new = (
"    # 首次见到血条或伤害数字 = 攻击命中确认(用户2026-09-21:二者出一即真怪)\n"
"    if (has_hp or has_dmg) and not hp_confirmed:\n"
"        hp_confirmed = True\n"
)
patch(CL, "utf-8", [
    (C1_old, C1_new, "C1_confirm_outrange"),
    (C2_old, C2_new, "C2_confirm_inrange"),
])
print("ALIVE500_OK")
