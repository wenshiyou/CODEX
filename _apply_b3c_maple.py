# -*- coding: utf-8 -*-
"""块3·脚本C（maple，BOM/LF）：climbing 到顶判据改后脑为主+光点兜底+总超时;主线接入卡住解卡相位;
   每秒后脑诊断日志;解卡B出口(重新挂上梯子)清 back_top 防残留误到顶。下行 direction<0 不接后脑/解卡,维持光点+超时。"""
import io
import py_compile

P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
b = io.open(P, 'rb').read()
assert b.startswith(b'\xef\xbb\xbf'), '缺 BOM'
t = b[3:].decode('utf-8')
assert '\r\n' not in t, 'CRLF'


def replace_span(s, start_mark, end_mark, new_text, tag):
    assert s.count(start_mark) == 1, tag + ' 起点%d' % s.count(start_mark)
    assert s.count(end_mark) == 1, tag + ' 终点%d' % s.count(end_mark)
    i = s.find(start_mark)
    j = s.find(end_mark)
    assert 0 <= i < j, tag + ' 顺序错'
    return s[:i] + new_text + s[j + len(end_mark):]


def replace_one(s, old, new, tag):
    assert s.count(old) == 1, tag + ' 命中%d' % s.count(old)
    return s.replace(old, new)


climb_start = '        if self._climb_state == "climbing":\n'
climb_end = "                self._reset_lock_after_arrival('梯到顶')\n            return False\n"
climb_new = (
    "        if self._climb_state == \"climbing\":\n"
    "            now_ms = time.time() * 1000\n"
    "            _up = self._climb_direction > 0\n"
    "            # 卡住解卡相位优先(仅上行):监管线程置令后由主线这里非阻塞发物理键横跳解卡;相位期间独占,不按↑、不做到顶判定\n"
    "            if _up and self._ladder_stuck_phase is None and getattr(self, '_ladder_stuck_cmd', None) is not None:\n"
    "                self._ladder_stuck_phase = 'start'\n"
    "                self._ladder_stuck_t = now_ms\n"
    "            if _up and self._ladder_stuck_phase is not None:\n"
    "                return self._ladder_stuck_recover_tick(px, py, now_ms)\n"
    "            # 持续按住↑/↓：按↑前先松↓、按↓前先松↑，上下互斥防抖动\n"
    "            if self._climb_direction > 0:\n"
    "                if VK_DOWN in self._random_move_keys:\n"
    "                    self._key_up(VK_DOWN)\n"
    "                if VK_UP not in self._random_move_keys:\n"
    "                    self._key_down(VK_UP)\n"
    "            elif self._climb_direction < 0:\n"
    "                if VK_UP in self._random_move_keys:\n"
    "                    self._key_up(VK_UP)\n"
    "                if VK_DOWN not in self._random_move_keys:\n"
    "                    self._key_down(VK_DOWN)\n"
    "            # === 到顶主判据(用户2026-09-18,仅上行):后脑勺连续BACK_TOP_LOST_MS看不到=人已翻出台子到顶。\n"
    "            # 小地图光点重合梯端仅作兜底(后脑漏检/没录到梯端时);下行不接后脑,仍只认光点对y_bottom。总超时保命不变。 ===\n"
    "            _bv, _bs = (self._back_head_visible() if _up else (False, 0.0))\n"
    "            if _up:\n"
    "                if _bv:\n"
    "                    self._ladder_back_lost_since = 0\n"
    "                else:\n"
    "                    if self._ladder_back_lost_since == 0:\n"
    "                        self._ladder_back_lost_since = now_ms\n"
    "                    elif now_ms - self._ladder_back_lost_since >= BACK_TOP_LOST_MS:\n"
    "                        self._ladder_back_top = True\n"
    "                if now_ms - self._ladder_back_diag_t >= 1000:\n"
    "                    self._ladder_back_diag_t = now_ms\n"
    "                    _lostms = (now_ms - self._ladder_back_lost_since) if self._ladder_back_lost_since else 0\n"
    "                    _debug_log(\"[爬梯·后脑] back=%.2f 可见=%s 连续无后脑=%.0fms 到顶标志=%s 光点Y=%.0f 梯端Y=%.0f 解卡=%s 失败=%d\" % (\n"
    "                        _bs, ('是' if _bv else '否'), _lostms, self._ladder_back_top, py,\n"
    "                        (self._climb_ladder_y_top or 0), (self._ladder_stuck_phase or '-'), self._ladder_stuck_fails))\n"
    "            _end_y = self._climb_ladder_y_top if _up else self._climb_ladder_y_bottom\n"
    "            if not _end_y:\n"
    "                # 端点为0(没录到梯端):光点贴梯共用X,用状态机入参小地图光点X直配录制梯钉端点(禁倍率/屏幕换算);每帧重试,配不到保持0靠后脑/超时收尾\n"
    "                self._pin_ladder_by_player_dot(px, py)\n"
    "                _end_y = self._climb_ladder_y_top if _up else self._climb_ladder_y_bottom\n"
    "            _arrived = False\n"
    "            _arrive_why = \"\"\n"
    "            _map_ok = False\n"
    "            if _end_y:\n"
    "                _map_ok = (py <= _end_y + LADDER_TOP_ARRIVE_TOL) if _up else (py >= _end_y - LADDER_TOP_ARRIVE_TOL)\n"
    "            _top_by_back = bool(_up and self._ladder_back_top)\n"
    "            if _top_by_back or _map_ok:\n"
    "                # 触发到顶那一刻不立刻松,继续按住↑多走LADDER_TOP_HOLD_MS确保整个人翻上台/踩稳(本段每帧补按方向键,hold期天然保持)\n"
    "                if not self._climb_top_hold:\n"
    "                    self._climb_top_hold = True\n"
    "                    self._climb_top_hold_t = now_ms\n"
    "                    self._climb_top_hold_why = (\"后脑连续%dms看不到=翻台到顶,补按%dms\" % (BACK_TOP_LOST_MS, LADDER_TOP_HOLD_MS)) if _top_by_back \\\n"
    "                        else (\"光点重合梯端后多按%dms翻稳\" % LADDER_TOP_HOLD_MS)\n"
    "                elif now_ms - self._climb_top_hold_t >= LADDER_TOP_HOLD_MS:\n"
    "                    _arrived = True\n"
    "                    _arrive_why = self._climb_top_hold_why\n"
    "            # 总超时保命(没录到梯端/后脑误判防永久卡梯);已进hold(200ms内必收尾)不再被超时打断\n"
    "            # 阈值=这把梯录制爬升耗时+2s(用户2026-09-17);取不到有效录制耗时(旧梯/录坏<1s)才回退写死12s\n"
    "            _cdur = getattr(self, '_climb_ladder_duration', None)\n"
    "            _climb_to = int((float(_cdur) + 2.0) * 1000) if isinstance(_cdur, (int, float)) and float(_cdur) >= 1.0 else CLIMB_TOTAL_TIMEOUT_MS\n"
    "            if not _arrived and not self._climb_top_hold and self._climb_action_time and now_ms - self._climb_action_time > _climb_to:\n"
    "                _arrived = True\n"
    "                _arrive_why = \"总超时%dms保命收尾(录制爬升%s+2s)\" % (_climb_to, (\"%.1fs\" % float(_cdur)) if isinstance(_cdur, (int, float)) and float(_cdur) >= 1.0 else \"无录制默认12s\")\n"
    "            if _arrived:\n"
    "                _debug_log(\"[爬梯] %s(光点Y=%.0f 梯端Y=%.0f),松键开主线\" % (_arrive_why, py, _end_y or 0))\n"
    "                if str(_arrive_why).startswith(\"总超时\"):\n"
    "                    self._rlog(\"爬梯保命超时收尾:%s(没录到梯端或判据没触发,强制松键开打)\" % _arrive_why, LOG_RED, log='exception')\n"
    "                else:\n"
    "                    self._rlog(\"%s,到顶开打\" % _arrive_why, LOG_OK, log='behavior')\n"
    "                if VK_UP in self._random_move_keys:\n"
    "                    self._key_up(VK_UP)\n"
    "                if VK_DOWN in self._random_move_keys:\n"
    "                    self._key_up(VK_DOWN)\n"
    "                self._reset_climb()\n"
    "                # 到顶清梯子上测的旧怪表+寻怪范围重扫重锁(防拿下方旧怪判cross一上去就下来)\n"
    "                self._reset_lock_after_arrival('梯到顶')\n"
    "            return False\n"
)
t = replace_span(t, climb_start, climb_end, climb_new, 'climbing段')

# 解卡B出口:重新挂上梯子继续爬,后脑到顶标志/计时一并清零(只清lost_since不够,防back_top残留误到顶)
b_old = (
    "            self._rlog(\"解卡后恢复移动,继续爬梯\", log='behavior')\n"
    "            self._ladder_stuck_clear()\n"
    "            self._ladder_back_lost_since = 0\n"
)
b_new = b_old + "            self._ladder_back_top = False   # B出口重新挂上梯子在爬,后脑到顶标志清零重计,防残留误到顶\n"
t = replace_one(t, b_old, b_new, '解卡B出口')

io.open(P, 'wb').write(b'\xef\xbb\xbf' + t.encode('utf-8'))
py_compile.compile(P, doraise=True)
print('BLOCK3-C maple OK(climbing后脑到顶+解卡相位接入+诊断日志+B出口清标志), py_compile pass')
