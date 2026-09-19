# -*- coding: utf-8 -*-
"""阶段3g: pick站定等稳梯期间,若B线决策state=cast(技能范围有近身怪正在打),暂缓建锁(不锁梯/不关扫/不累计失败),
先打完边上的怪(用户:起跳前可以先打完边上的怪);cast结束再二帧稳梯建锁。下行下跳失败锁梯不受此门控。"""
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s = open(P, "rb").read().decode("utf-8-sig")
log = []
def rep(old, new, n=1, tag=""):
    global s
    c = s.count(old)
    assert c == n, "[%s] 命中%d次(期望%d) old=%r" % (tag, c, n, old[:80])
    s = s.replace(old, new); log.append("OK " + tag)

# 1) 加 _busy_cast 读取
rep(
'''                                _up_pick = (_climb_st == 'to_ladder' and _ap == 'pick')
                                # 下行(下跳失败转走梯,cdir=-1,不走approach、phase=none):保持原"方向带每帧选中即锁",范围用默认下行带(用户:下行不碰)
                                _down_fast = (_climb_st == 'to_ladder' and _cdir < 0 and _ap not in ('settle', 'pick', 'repos'))
                                if _up_pick or _down_fast:''',
'''                                _up_pick = (_climb_st == 'to_ladder' and _ap == 'pick')
                                # 下行(下跳失败转走梯,cdir=-1,不走approach、phase=none):保持原"方向带每帧选中即锁",范围用默认下行带(用户:下行不碰)
                                _down_fast = (_climb_st == 'to_ladder' and _cdir < 0 and _ap not in ('settle', 'pick', 'repos'))
                                # 上行pick站定期间,B线正在cast=技能范围有近身怪开打→暂缓建锁(不关扫/不累计失败),先打完边上的怪再锁梯(用户2026-09-19)
                                _pkt = getattr(self, '_combat_decision_packet', None)
                                _busy_cast = bool(_pkt and _pkt.get('state') == 'cast')
                                if _up_pick or _down_fast:''',
    tag="加cast门控变量")

# 2) 上行二帧稳梯前插 cast 暂缓分支
rep(
'''                                    elif _scan_t != self._ladder_pick_beat_scan_t:
                                        self._ladder_pick_beat_scan_t = _scan_t   # 一个新扫描节拍
                                        if _pick_l is not None:
                                            _bx, _by = int(_pick_l[0]), int(_pick_l[1])
                                            _stb = self._ladder_pick_stable''',
'''                                    elif _busy_cast:
                                        _stage = '近身怪优先·暂缓锁梯'
                                    elif _scan_t != self._ladder_pick_beat_scan_t:
                                        self._ladder_pick_beat_scan_t = _scan_t   # 一个新扫描节拍
                                        if _pick_l is not None:
                                            _bx, _by = int(_pick_l[0]), int(_pick_l[1])
                                            _stb = self._ladder_pick_stable''',
    tag="cast暂缓建锁")

open(P, "wb").write(s.encode("utf-8-sig"))
import py_compile
py_compile.compile(P, doraise=True)
print("\n".join(log)); print("阶段3g写回并编译通过")
