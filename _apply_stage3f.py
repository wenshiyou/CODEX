# -*- coding: utf-8 -*-
"""阶段3f(复盘修补):
1)下行(下跳失败转to_ladder,cdir=-1,phase=none)保持原"方向带每帧选中即锁",不被二帧稳梯挡死;
2)上行align跟丢3拍清锁回pick时重开怪扫(precise=False),且该回退只对上行生效,下行保身份交状态机保命;
3)状态机align无锁点:下行保留连续LADDER_MERGE_WAIT_MS找不到梯回主线(下行行为不变),上行站住等pick/挪位。"""
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s = open(P, "rb").read().decode("utf-8-sig")
log = []
def rep(old, new, n=1, tag=""):
    global s
    c = s.count(old)
    assert c == n, "[%s] 命中%d次(期望%d) old=%r" % (tag, c, n, old[:80])
    s = s.replace(old, new); log.append("OK " + tag)

# 1) 未锁建锁: 上行pick二帧稳梯 + 下行方向带每帧即锁
rep(
'''                                if _climb_st == 'to_ladder' and _ap == 'pick':
                                    _pick_l, _pick_reason, _db_band = self._dir_band_pick_ladder(
                                        _half, _psx, _psy, _cdir, _tmox,
                                        x_half=_far_x, y_far=_far_yu, y_near=0)
                                    if _scan_t != self._ladder_pick_beat_scan_t:''',
'''                                _up_pick = (_climb_st == 'to_ladder' and _ap == 'pick')
                                # 下行(下跳失败转走梯,cdir=-1,不走approach、phase=none):保持原"方向带每帧选中即锁",范围用默认下行带(用户:下行不碰)
                                _down_fast = (_climb_st == 'to_ladder' and _cdir < 0 and _ap not in ('settle', 'pick', 'repos'))
                                if _up_pick or _down_fast:
                                    if _down_fast:
                                        _pick_l, _pick_reason, _db_band = self._dir_band_pick_ladder(
                                            _half, _psx, _psy, _cdir, _tmox)
                                    else:
                                        _pick_l, _pick_reason, _db_band = self._dir_band_pick_ladder(
                                            _half, _psx, _psy, _cdir, _tmox,
                                            x_half=_far_x, y_far=_far_yu, y_near=0)
                                    if _down_fast:
                                        if _scan_t != self._ladder_pick_beat_scan_t:
                                            self._ladder_pick_beat_scan_t = _scan_t
                                            if _pick_l is not None:
                                                _bx, _by = int(_pick_l[0]), int(_pick_l[1])
                                                self._ladder_lock = (_bx, _by, _now_lm)
                                                self._ladder_snap_x = _bx
                                                self._ladder_lock_t0 = _now_lm
                                                self._freeze_ladder_patch(_bx, _by)
                                                self._ladder_lost_beats = 0
                                                self._ladder_lost_beat_scan_t = _scan_t
                                                _sel = (_bx, _by, True); _rx, _ry = _bx, _by
                                                _stage = '下行建锁'
                                                _debug_log("[选梯·建锁] 下行方向带 人=(%d,%d) 带内%d把[%s] 选中(%d,%d)" % (
                                                    _psx, _psy, len(_db_band), _pick_reason, _bx, _by))
                                            else:
                                                _stage = '下行带内无梯'
                                    elif _scan_t != self._ladder_pick_beat_scan_t:''',
    tag="下行一帧建锁")

# 2a) 已锁跟丢3拍: 仅上行(cdir>0)清锁回pick; 下行保身份(状态机超时保命)
rep(
'''                                        if (not _jumped) and self._ladder_lost_beats >= LADDER_PICK_FAIL_BEATS:
                                            # 未起跳(平地align)连续3拍补不回:清锁回pick重新二帧稳梯(再3拍无→主线挪位/冷却回主线);
                                            # 起跳后(post_jump/realign/climbing)保身份等找回,不清锁、不挪位''',
'''                                        if (not _jumped) and self._ladder_lost_beats >= LADDER_PICK_FAIL_BEATS and _cdir > 0:
                                            # 上行未起跳(平地align)连续3拍补不回:清锁回pick重新二帧稳梯(再3拍无→主线挪位/冷却回主线),并重开怪扫;
                                            # 起跳后(post_jump/realign/climbing)保身份等找回; 下行(cdir<0)不在此清锁,保身份交状态机连续找不到梯超时保命''',
    tag="跟丢回退仅上行")

# 2b) 上行清锁回pick时重开怪扫
rep(
'''                                            self._ladder_approach_phase = 'pick'
                                            self._ladder_pick_stable = None
                                            self._ladder_pick_fail_beats = 0
                                            self._ladder_pick_beat_scan_t = 0.0
                                            self._ladder_lost_beats = 0
                                            _rx = _ry = None
                                            _stage = '回pick重稳'
''',
'''                                            self._ladder_approach_phase = 'pick'
                                            self._ladder_pick_stable = None
                                            self._ladder_pick_fail_beats = 0
                                            self._ladder_pick_beat_scan_t = 0.0
                                            self._ladder_lost_beats = 0
                                            _rx = _ry = None
                                            _stage = '回pick重稳'
''',
    tag="回pick重开怪扫")

# 3) 状态机align无锁点: 下行保留1500ms保命, 上行站住等pick/挪位
rep(
'''            # align相位这帧没锁点(蒙板段跟丢):站住不发键、不拿旧点;蒙板段连续3扫描节拍补不回会清锁回pick重新稳梯,
            # 再3拍无稳梯由_ladder_approach_step走挪位/冷却回主线,不会永久空转(用户2026-09-19,删固定1500ms超时)。
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            return False''',
'''            # 没锁点:上行approach体系站住等pick/挪位(蒙板段3拍回pick→_ladder_approach_step挪位/冷却回主线,不另设时间兜底);
            # 下行(下跳失败转走梯,cdir=-1,不进approach)保留连续LADDER_MERGE_WAIT_MS找不到梯回主线的保命(用户:下行行为不变)。
            if self._climb_direction < 0 and getattr(self, '_ladder_approach_phase', 'none') not in ('settle', 'pick', 'repos'):
                if getattr(self, '_lad_scr_enter_t', 0) == 0:
                    self._lad_scr_enter_t = now_ms
                if now_ms - self._lad_scr_enter_t >= LADDER_MERGE_WAIT_MS:
                    self._rlog("下行屏幕连续%.0fms找不到梯子,松键回主线(不死等)" % LADDER_MERGE_WAIT_MS, LOG_RED, log='exception')
                    _debug_log("[梯子·掉锁] 下行连续%.0fms一把白框都没识别到,松左右键回主线打怪" % LADDER_MERGE_WAIT_MS)
                    self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                    self._reset_climb(); self._decide_climb_fail_action()
                    return False
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            return False''',
    tag="下行超时保命")

open(P, "wb").write(s.encode("utf-8-sig"))
import py_compile
py_compile.compile(P, doraise=True)
print("\n".join(log)); print("阶段3f写回并编译通过")
