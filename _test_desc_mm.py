# -*- coding: utf-8 -*-
"""离线单测: 下行方式二小地图 _desc_mm_ladder_tick(对齐直接抓梯 / 选不到超时放弃)。"""
import maple_route_ui as M
C = M.MinimapRouteRecorder
VK_LEFT, VK_RIGHT, VK_DOWN = M.VK_LEFT, M.VK_RIGHT, M.VK_DOWN
M._debug_log = lambda *a, **k: None

def make(ladders, px=100.0, py=100.0):
    o = object.__new__(C)
    o.ladders = ladders
    o._player_screen_pos = (200.0, 300.0)
    o._random_move_keys = set()
    o._climb_ladder_x = 0; o._climb_ladder_y_top = 0; o._climb_ladder_y_bottom = 0
    o._climb_fail_pause_until = 0
    o._desc_mm_no_pick_t = 0
    o._desc_phase = 'mm_to_lad'
    o.reset_called = False; o.grabbed = False
    o._key_down = lambda vk: o._random_move_keys.add(vk)
    o._key_up = lambda vk: o._random_move_keys.discard(vk)
    o._release_move_conflicts = lambda: None
    o._rlog = lambda *a, **k: None
    o._decide_climb_fail_action = lambda: None
    def _reset():
        o.reset_called = True; o._desc_phase = 'none'
    o._reset_climb = _reset
    def _grab(py2, now):
        o.grabbed = True; o._desc_phase = 'lad_grab'; o._desc_base_y = py2
    o._enter_desc_lad_grab = _grab
    def _walk(tx, px2, now, on_stall, dbg):
        # 模拟按住朝梯走(本测试不走stall分支)
        return False
    o._desc_horiz_walk = _walk
    return o

fails = []
def ck(n, cond, extra=''):
    print(('PASS ' if cond else 'FAIL ') + n + ('  ' + str(extra) if extra else ''))
    if not cond: fails.append(n)

# 下行梯: 梯顶95(光点100差5<=10)、梯身向下通到160
ld_down = [{'id': 1, 'x': 100.0, 'y_top': 95.0, 'y_bottom': 160.0, 'duration_sec': 5.0}]

# D1 光点已对齐梯X(差0.5<=1) -> 直接 lad_grab 按↓
o = make(ld_down, px=100.5)
o._desc_mm_ladder_tick(100.5, 100.0, 1000)
ck('D1 对齐直接抓梯', o.grabbed and o._desc_phase == 'lad_grab', (o.grabbed, o._desc_phase))

# D2 没对齐(差8) -> 不抓、走水平移动(不放弃)
o = make(ld_down, px=92.0)
o._desc_mm_ladder_tick(92.0, 100.0, 1000)
ck('D2 未对齐不抓梯不放弃', (not o.grabbed) and (not o.reset_called) and o._climb_ladder_x == 100.0)

# D3 无任何下行梯: 首次不放弃, 连续超时放弃回主线
o = make([], px=100.0)
o._desc_mm_ladder_tick(100.0, 100.0, 1000)
ck('D3 首次选不到不立即放弃', not o.reset_called)
o._desc_mm_ladder_tick(100.0, 100.0, 1000 + M.LADDER_MM_NOPICK_TIMEOUT_MS + 1)
ck('D3 超时选不到放弃回主线', o.reset_called)

# D4 上行梯(梯身在光点上方、不下通)不应被选为下行梯 -> 视为无下行梯
ld_up = [{'id': 2, 'x': 100.0, 'y_top': 20.0, 'y_bottom': 90.0}]
o = make(ld_up, px=100.0)
o._desc_mm_ladder_tick(100.0, 100.0, 1000)
ck('D4 上通梯不当下行梯(不抓)', not o.grabbed)

print()
if fails:
    print('==== %d FAILED: %s' % (len(fails), fails)); raise SystemExit(1)
print('==== ALL DESCEND-MINIMAP TESTS PASSED ====')
