# -*- coding: utf-8 -*-
"""判活检测端探针(用户2026-09-20):只观测不改决策。
1) combat_logic 血条A/B垂直范围 -150 -> -180
2) maple: 主攻/群攻出手计数; _detect_damage_number 加 dbg 输出中间量(红/橙簇、连通域、失败原因);
   B线程在出手反馈窗内"绕开门控"无条件跑一次伤害检测(探针),与门控结果对比,直接区分:
   探针见字/门控不见=B门控对接问题; 探针也不见=检测端(色值/ROI/时机)问题;
   血条A/B命中复算; 每5秒一行[判活汇总]。"""
import io, sys, ast

BASE = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"

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

# ---------- combat_logic.py: -150 -> -180 (utf-8 无BOM) ----------
cl = BASE + r"\combat_logic.py"
patch(cl, "utf-8", [
    (
"    # 用户2026-09-20定稿:判活血条区域=两部分并集。A=怪物基点X±35(Y在人物上方150px内,血条在怪头顶);\n"
"    # B=人物技能范围(人物X±skill_range,Y向上150px)。血条落A或B任一=打着怪/怪活着。\n",
"    # 用户2026-09-20定稿:判活血条区域=两部分并集。A=怪物基点X±35(Y在人物上方180px内,血条在怪头顶);\n"
"    # B=人物技能范围(人物X±skill_range,Y向上180px)。血条落A或B任一=打着怪/怪活着。垂直范围2026-09-20由150改180。\n",
"cl-comment"),
    (
"            in_a = (lcx - 35) <= bxc <= (lcx + 35) and (lcy - 150) <= byc <= lcy   # A:怪物基点X前35~后35,Y怪物上方150\n"
"            in_b = abs(bxc - px) <= skill_range and (py - 150) <= byc <= py  # B:血条中心X离人物基点X不超过技能范围,Y人物上方150\n",
"            in_a = (lcx - 35) <= bxc <= (lcx + 35) and (lcy - 180) <= byc <= lcy   # A:怪物基点X前35~后35,Y怪物上方180\n"
"            in_b = abs(bxc - px) <= skill_range and (py - 180) <= byc <= py  # B:血条中心X离人物基点X不超过技能范围,Y人物上方180\n",
"cl-ab"),
])

# ---------- maple_route_ui.py (utf-8-sig) ----------
mp = BASE + r"\maple_route_ui.py"
reps = []

# A) __init__ 探针计数器
reps.append((
"        self._combat_first_strike_time = 0         # 对当前锁定目标【首次】出手时间(ms)：出手后留POST_STRIKE_CHECK_MS(130ms)反馈窗口再判空怪/打死，换目标清零\n",
"        self._combat_first_strike_time = 0         # 对当前锁定目标【首次】出手时间(ms)：出手后留POST_STRIKE_CHECK_MS(130ms)反馈窗口再判空怪/打死，换目标清零\n"
"        self._dbg_probe = {'atk':0,'aoe':0,'win':0,'probe_dmg':0,'gate_dmg':0,'hpframe':0,'abhit':0,'misalign':0,'early':0,'notskill':0,'t0':0}  # 判活检测端探针计数(只观测不改决策,2026-09-20)\n",
"init-counter"))

# B) _detect_damage_number 签名加 dbg
reps.append((
"    def _detect_damage_number(self, target_cx, target_cy, frame=None, monsters=None):",
"    def _detect_damage_number(self, target_cx, target_cy, frame=None, monsters=None, dbg=None):",
"dmg-signature"))

# B1) 没找到怪
reps.append((
"        if target_y1 is None:\n            return False  # 没找到对应怪物，无法检测\n",
"        if target_y1 is None:\n            if dbg is not None: dbg['reason'] = 'no_monster'\n            return False  # 没找到对应怪物，无法检测\n",
"dmg-nomonster"))

# B2) frame None
reps.append((
"        if frame is None:\n            return False\n",
"        if frame is None:\n            if dbg is not None: dbg['reason'] = 'no_frame'\n            return False\n",
"dmg-noframe"))

# B3) ROI 非法
reps.append((
"        if rx2 <= rx1 or ry2 <= ry1:\n            return False\n",
"        if rx2 <= rx1 or ry2 <= ry1:\n            if dbg is not None: dbg['reason'] = 'bad_roi'\n            return False\n",
"dmg-badroi"))

# B4) 颜色量 + 不足原因
reps.append((
"        n_red, n_org = int(np.sum(m_red > 0)), int(np.sum(m_org > 0))\n"
"        if n_red < 80 or n_org < 70:\n"
"            return False  # 红簇不足=暖色背景/绿血条，不是伤害数字\n",
"        n_red, n_org = int(np.sum(m_red > 0)), int(np.sum(m_org > 0))\n"
"        if dbg is not None:\n"
"            dbg.update(n_red=n_red, n_org=n_org, ty=int(target_y1))\n"
"        if n_red < 80 or n_org < 70:\n"
"            if dbg is not None: dbg['reason'] = 'color_low'\n"
"            return False  # 红簇不足=暖色背景/绿血条，不是伤害数字\n",
"dmg-color"))

# B5) 连通域最大量 + hit/no_contour
reps.append((
"        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)\n"
"        for cnt in contours:\n"
"            _cx, _cy, _cw, _ch = cv2.boundingRect(cnt)\n"
"            _is_bar = (_cw > _ch * 2 and _ch <= 8)   # 扁横条=血条，排除\n"
"            if cv2.contourArea(cnt) >= 50 and _ch >= 9 and not _is_bar:\n"
"                return True\n"
"        return False\n",
"        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)\n"
"        _max_area, _max_h = 0, 0\n"
"        for cnt in contours:\n"
"            _cx, _cy, _cw, _ch = cv2.boundingRect(cnt)\n"
"            _ar = cv2.contourArea(cnt)\n"
"            if dbg is not None:\n"
"                _max_area = max(_max_area, int(_ar)); _max_h = max(_max_h, int(_ch))\n"
"            _is_bar = (_cw > _ch * 2 and _ch <= 8)   # 扁横条=血条，排除\n"
"            if _ar >= 50 and _ch >= 9 and not _is_bar:\n"
"                if dbg is not None: dbg.update(reason='hit', max_area=int(_ar), max_h=int(_ch))\n"
"                return True\n"
"        if dbg is not None:\n"
"            dbg.update(reason='no_contour', max_area=_max_area, max_h=_max_h)\n"
"        return False\n",
"dmg-contour"))

# C) 群攻出手计数
reps.append((
"                self._combat_target_attacked = True  # 群攻也算对锁定目标出手：空放无反馈时同样走130ms空怪drop换目标\n",
"                self._combat_target_attacked = True  # 群攻也算对锁定目标出手：空放无反馈时同样走130ms空怪drop换目标\n"
"                self._dbg_probe['aoe'] += 1  # 探针:群攻真实出手计数(写debug.log可统计)\n",
"aoe-count"))

# D) 主攻出手计数
reps.append((
"                self._combat_target_attacked = True  # 已对锁定目标出手：空怪判定用\n",
"                self._combat_target_attacked = True  # 已对锁定目标出手：空怪判定用\n"
"                self._dbg_probe['atk'] += 1  # 探针:主攻真实出手计数(写debug.log可统计)\n",
"atk-count"))

# E) B线程:门控dbg + 无条件探针 + 血条AB复算 + 5秒汇总
old_gate = (
"        _has_dmg = False\n"
"        if _in_skill and _detect_open:\n"
"            try:\n"
"                _has_dmg = self._detect_damage_number(_bl[0], _bl[1], frame=frame, monsters=merged)\n"
"            except Exception as _e:\n"
"                _debug_log(\"[B决策] 伤害数字检测异常: %s\" % _e)\n"
"                _has_dmg = False\n"
)
new_gate = old_gate + (
"        # ===== 判活检测端探针(2026-09-20,只观测不改决策):先证画面里能不能检出伤害数字/血条,再证门控对接 =====\n"
"        try:\n"
"            P = self._dbg_probe\n"
"            if not P.get('t0'):\n"
"                P['t0'] = now_ms\n"
"            _fposP = _fb.get('pos') if _fb else None\n"
"            _alignP = bool(_bl is not None and _fposP and abs(_fposP[0] - _bl[0]) <= 40 and abs(_fposP[1] - _bl[1]) <= 50)\n"
"            if _bl is not None and _fposP and _fb.get('first'):\n"
"                _elP = now_ms - (_fb.get('first') or 0)\n"
"                if not _alignP:\n"
"                    P['misalign'] += 1\n"
"                elif _elP <= POST_STRIKE_CHECK_MS:\n"
"                    P['early'] += 1\n"
"                elif not _in_skill:\n"
"                    P['notskill'] += 1\n"
"            # 无条件探针:出手后100~650ms,绕开_in_skill/_detect_open,直接对出手目标头顶跑颜色检测\n"
"            if _fposP and _fb.get('first'):\n"
"                _elP = now_ms - (_fb.get('first') or 0)\n"
"                if POST_STRIKE_CHECK_MS < _elP < 650:\n"
"                    P['win'] += 1\n"
"                    _pdb = {}\n"
"                    try:\n"
"                        _p_hit = self._detect_damage_number(_fposP[0], _fposP[1], frame=frame, monsters=merged, dbg=_pdb)\n"
"                    except Exception:\n"
"                        _p_hit = False\n"
"                    if _p_hit:\n"
"                        P['probe_dmg'] += 1\n"
"                    if _has_dmg:\n"
"                        P['gate_dmg'] += 1\n"
"                    _debug_log(\"[伤害探针] 出手后%dms 对齐=%s 射程内=%s 门开=%s | 探针见字=%s 门控见字=%s n红=%s n橙=%s 最大面积=%s 最大高=%s 顶y=%s 原因=%s\" % (\n"
"                        int(_elP), _alignP, _in_skill, _detect_open, _p_hit, _has_dmg,\n"
"                        _pdb.get('n_red'), _pdb.get('n_org'), _pdb.get('max_area'), _pdb.get('max_h'),\n"
"                        _pdb.get('ty'), _pdb.get('reason')))\n"
"            # 血条A/B命中复算(与combat_logic同口径,垂直180)\n"
"            if bars and _bl is not None:\n"
"                P['hpframe'] += 1\n"
"                for (_bxP, _byP, _bwP, _bhP) in bars:\n"
"                    _bxcP = _bxP + _bwP / 2.0; _bycP = _byP + _bhP / 2.0\n"
"                    _inaP = (_bl[0] - 35) <= _bxcP <= (_bl[0] + 35) and (_bl[1] - 180) <= _bycP <= _bl[1]\n"
"                    _inbP = abs(_bxcP - px) <= _skr and (py - 180) <= _bycP <= py\n"
"                    if _inaP or _inbP:\n"
"                        P['abhit'] += 1\n"
"                        break\n"
"            if now_ms - P['t0'] >= 5000:\n"
"                _debug_log(\"[判活汇总] 近5秒: 主攻%d 群攻%d | 检测窗%d帧 探针见伤害%d 门控见伤害%d | 血条帧%d A/B命中%d | 门未开[对不齐%d 太早%d 非射程%d]\" % (\n"
"                    P['atk'], P['aoe'], P['win'], P['probe_dmg'], P['gate_dmg'], P['hpframe'], P['abhit'],\n"
"                    P['misalign'], P['early'], P['notskill']))\n"
"                for _kP in ('atk','aoe','win','probe_dmg','gate_dmg','hpframe','abhit','misalign','early','notskill'):\n"
"                    P[_kP] = 0\n"
"                P['t0'] = now_ms\n"
"        except Exception as _pe:\n"
"            _debug_log(\"[判活探针] 异常: %s\" % _pe)\n"
)
reps.append((old_gate, new_gate, "b-probe"))

patch(mp, "utf-8-sig", reps)
print("ALL_PROBE_OK")
