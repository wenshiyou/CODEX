# -*- coding: utf-8 -*-
"""判活门控根因修复(用户2026-09-20定稿):
1) 判活只看"出手后100~500ms窗 + 检测范围",删除与当帧锁±40/±50对齐门、删除_in_skill射程门;
   窗内判活/保锁目标钉成出手那只 feedback.pos,见伤害/血条=活着,满500ms无=drop。
2) 主攻/群攻出手前方向键短点 40ms -> 50ms(站定单独掰脸那处不动)。
只改 maple_route_ui.py(utf-8-sig),combat_logic.py 不动。"""
import io, ast

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(P, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()

reps = []

# --- 1) B线程判活门控块整体替换 ---
old_gate = (
"        # 主线出手反馈→必须与当前b_lock是同一只(±40X/±50Y)才算数,防换目标后旧出手污染新怪\n"
"        _bl = self._b_lock\n"
"        _fb = getattr(self, '_combat_exec_feedback', None)\n"
"        _attacked = False\n"
"        _detect_open = False   # 用户2026-09-20:100ms开始看伤害数字(判死仍走500ms截止)\n"
"        if _bl is not None and _fb and _fb.get('pos'):\n"
"            _fpos = _fb['pos']\n"
"            if abs(_fpos[0] - _bl[0]) <= 40 and abs(_fpos[1] - _bl[1]) <= 50:\n"
"                _first = _fb.get('first', 0) or 0\n"
"                _el = now_ms - _first\n"
"                # 用户2026-09-20:100ms起开始看血条/伤害(检测门);满500ms仍无血无伤才判死(判死门)\n"
"                if _first and now_ms >= _first and _el > POST_STRIKE_CHECK_MS:\n"
"                    _detect_open = True\n"
"                if _first and now_ms >= _first and _el > STRIKE_DEADLINE_MS:\n"
"                    _attacked = True\n"
"        # can_strike=锁在停步线+主攻Y带(真打得到);只有成立时才用\"无血无伤\"判死\n"
"        _in_skill = bool(_bl) and abs(_bl[0] - px) <= _stop and -_yup <= (_bl[1] - py) <= _ydn\n"
"        _has_dmg = False\n"
"        if _in_skill and _detect_open:\n"
"            try:\n"
"                _has_dmg = self._detect_damage_number(_bl[0], _bl[1], frame=frame, monsters=merged)\n"
"            except Exception as _e:\n"
"                _debug_log(\"[B决策] 伤害数字检测异常: %s\" % _e)\n"
"                _has_dmg = False\n"
)
new_gate = (
"        # 出手反馈判活(用户2026-09-20定稿):只看\"出手后100~500ms窗+检测范围\",【不再要求与当帧锁对齐、不再要求当帧站定射程内】。\n"
"        # 判活窗内把判活/保锁目标钉成\"出手那只怪 feedback.pos\"(打了没出结果前不被别的怪抢走);窗内见伤害数字或血条A/B=活着续锁,\n"
"        # 满500ms仍无血无伤=空怪/打死→drop。对齐仅留作日志参考(有对齐更好),不做门控(探针实测旧两门挡掉约1/3真实飘字)。\n"
"        _bl = self._b_lock\n"
"        _fb = getattr(self, '_combat_exec_feedback', None)\n"
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
"        # can_strike=判活目标在停步线+主攻Y带;只影响\"曾见血后走近/跳打中\"的保锁,满窗无血无伤两分支都drop\n"
"        _in_skill = bool(_judge_pos) and abs(_judge_pos[0] - px) <= _stop and -_yup <= (_judge_pos[1] - py) <= _ydn\n"
"        _has_dmg = False\n"
"        # 伤害数字:窗内100~650ms对出手怪头顶检测(旧\"_in_skill且对齐\"两道门已删,移动/跳打/高处帧一样判活)\n"
"        if _detect_open and _judge_pos is not None and _fb and _fb.get('first') and (now_ms - (_fb.get('first') or 0)) < 650:\n"
"            try:\n"
"                _has_dmg = self._detect_damage_number(_judge_pos[0], _judge_pos[1], frame=frame, monsters=merged)\n"
"            except Exception as _e:\n"
"                _debug_log(\"[B决策] 伤害数字检测异常: %s\" % _e)\n"
"                _has_dmg = False\n"
)
reps.append((old_gate, new_gate, "gate"))

# --- 2) combat_step 的 lock 传参:窗内用判活目标 _judge_pos ---
reps.append((
"            _bl, bars, _has_dmg, True, True,\n",
"            _judge_pos, bars, _has_dmg, True, True,   # 判活窗内lock=出手怪(钉保锁),窗外_judge_pos=_bl等价原逻辑\n",
"step-lock"))

# --- 3) 主攻出手前方向键 40->50 ---
reps.append((
"                _fvk = VK_RIGHT if t_cx >= px else VK_LEFT\n"
"                self._send_win_key(_fvk, keyup=False)\n"
"                self._combat_timed_keys.append((_fvk, now + 40))\n"
"                self._press_game_key(atk_key)  # keybd_event tap(keydown+keyup)，能松开(用户：用特定模式)\n",
"                _fvk = VK_RIGHT if t_cx >= px else VK_LEFT\n"
"                self._send_win_key(_fvk, keyup=False)\n"
"                self._combat_timed_keys.append((_fvk, now + 50))  # 用户2026-09-20:40ms经常不转向,改50ms(与攻击同帧不位移)\n"
"                self._press_game_key(atk_key)  # keybd_event tap(keydown+keyup)，能松开(用户：用特定模式)\n",
"atk-face50"))

# --- 4) 群攻出手前方向键 40->50 ---
reps.append((
"                _afvk = VK_RIGHT if t_cx >= px else VK_LEFT\n"
"                self._send_win_key(_afvk, keyup=False)\n"
"                self._combat_timed_keys.append((_afvk, now + 40))\n"
"                self._press_game_key(aoe_key)\n",
"                _afvk = VK_RIGHT if t_cx >= px else VK_LEFT\n"
"                self._send_win_key(_afvk, keyup=False)\n"
"                self._combat_timed_keys.append((_afvk, now + 50))  # 用户2026-09-20:40ms经常不转向,改50ms\n"
"                self._press_game_key(aoe_key)\n",
"aoe-face50"))

for old, new, tag in reps:
    c = s.count(old)
    assert c == 1, "锚点不唯一/缺失 [%s] count=%d" % (tag, c)
    s = s.replace(old, new)

ast.parse(s)
with io.open(P, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
print("GATEFIX_OK")
