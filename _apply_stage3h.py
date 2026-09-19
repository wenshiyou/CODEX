# -*- coding: utf-8 -*-
"""阶段3h(稳态):
1)approach_step只收屏幕坐标,缺失(None)时其内部松键等帧,不拿小地图px顶替(坐标系不同会乱走);
2)上行align无锁点且锁身份已清(_ladder_lock=None)但相位残留align(异常/竞态)→自愈回pick重新稳梯,不永久站住发呆。
   短暂空帧(锁身份还在、仅snap=None)不触发,仍站住等蒙板段3拍判定。"""
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s = open(P, "rb").read().decode("utf-8-sig")
log = []
def rep(old, new, n=1, tag=""):
    global s
    c = s.count(old)
    assert c == n, "[%s] 命中%d次(期望%d) old=%r" % (tag, c, n, old[:80])
    s = s.replace(old, new); log.append("OK " + tag)

# 1) approach 只传屏幕坐标
rep(
'''            _ap = getattr(self, '_ladder_approach_phase', 'align')
            if _ap in ('settle', 'pick', 'repos'):
                return self._ladder_approach_step(self._player_screen_pos or (px, py), now_ms)''',
'''            _ap = getattr(self, '_ladder_approach_phase', 'align')
            if _ap in ('settle', 'pick', 'repos'):
                return self._ladder_approach_step(self._player_screen_pos, now_ms)''',
    tag="approach只收屏幕坐标")

# 2) 上行 align 锁已清但相位残留 → 自愈回 pick
rep(
'''            # 没锁点:上行approach体系站住等pick/挪位(蒙板段3拍回pick→_ladder_approach_step挪位/冷却回主线,不另设时间兜底);
            # 下行(下跳失败转走梯,cdir=-1,不进approach)保留连续LADDER_MERGE_WAIT_MS找不到梯回主线的保命(用户:下行行为不变)。
            if self._climb_direction < 0 and getattr(self, '_ladder_approach_phase', 'none') not in ('settle', 'pick', 'repos'):''',
'''            # 没锁点:上行approach体系站住等pick/挪位(蒙板段3拍回pick→_ladder_approach_step挪位/冷却回主线,不另设时间兜底);
            # 下行(下跳失败转走梯,cdir=-1,不进approach)保留连续LADDER_MERGE_WAIT_MS找不到梯回主线的保命(用户:下行行为不变)。
            # 上行状态一致性自愈:锁身份已清(_ladder_lock=None,非短暂空帧)但相位残留align(异常/竞态)→回pick重新稳梯,不永久站住。
            if self._climb_direction >= 0 and _ap == 'align' and getattr(self, '_ladder_lock', None) is None:
                self._ladder_approach_phase = 'pick'
                self._ladder_pick_beat_scan_t = 0.0
                self._ladder_pick_stable = None
                self._ladder_pick_fail_beats = 0
                _debug_log("[选梯·自愈] align无锁且锁身份已清,回pick重新二帧稳梯(防发呆)")
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                return False
            if self._climb_direction < 0 and getattr(self, '_ladder_approach_phase', 'none') not in ('settle', 'pick', 'repos'):''',
    tag="上行align自愈回pick")

open(P, "wb").write(s.encode("utf-8-sig"))
import py_compile
py_compile.compile(P, doraise=True)
print("\n".join(log)); print("阶段3h写回并编译通过")
