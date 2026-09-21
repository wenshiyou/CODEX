# -*- coding: utf-8 -*-
"""离线单测: 小地图上梯 goto 状态机 _ladder_mm_goto_tick / fine_tick / mm_realign。
object.__new__ 绕过UI初始化,mock按键与reset,喂光点序列断言状态转换/起跳次数/放弃。"""
import maple_route_ui as M
C = M.MinimapRouteRecorder
VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN = M.VK_LEFT, M.VK_RIGHT, M.VK_UP, M.VK_DOWN
M._debug_log = lambda *a, **k: None

def make(lad_x=100.0, ytop=40.0, ybot=105.0, mon_x=None, spx=200.0):
    o = object.__new__(C)
    o.ladders = [{'id': 1, 'x': lad_x, 'y_top': ytop, 'y_bottom': ybot, 'duration_sec': 5.0}] if lad_x is not None else []
    o._player_screen_pos = (spx, 300.0)
    o._ladder_target_mon_x = mon_x
    o._ladder_jump_cfg = {'rj_l': 7, 'rj_r': 7, 'vl_l': 1, 'vl_r': 1}
    o._random_move_keys = set()
    o._climb_state = 'to_ladder'; o._climb_direction = 1
    o._ladder_run_jumped = False; o._ladder_vert_jumped = False
    o._ladder_jump_phase = 'mm_goto'; o._ladder_post_jump_step = None; o._ladder_post_jump_t = 0
    o._ladder_realign_round = 0
    o._ladder_mm_fine_phase = ''; o._ladder_mm_fine_t = 0
    o._ladder_mm_fine_round = 0; o._ladder_mm_no_pick_t = 0
    o._climb_ladder_x = 0; o._climb_ladder_y_top = 0; o._climb_ladder_y_bottom = 0
    o._climb_ladder_duration = None; o._climb_start_y = 0; o._climb_fail_pause_until = 0
    o.reset_called = False; o.jumps = []
    o._key_down = lambda vk: o._random_move_keys.add(vk)
    o._key_up = lambda vk: o._random_move_keys.discard(vk)
    o._press_game_key = lambda key, duration=120: o.jumps.append((key, duration))
    o._rlog = lambda *a, **k: None
    o._decide_climb_fail_action = lambda: None
    def _reset():
        o.reset_called = True; o._climb_state = 'none'; o._ladder_jump_phase = None
    o._reset_climb = _reset
    return o

fails = []
def ck(name, cond, extra=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(extra) if extra else ''))
    if not cond: fails.append(name)

# T1 跑跳->没抓住回goto->微调2拍对不齐->放弃
o = make(mon_x=260.0)
o._ladder_mm_goto_tick(80.0, 100.0, 1000, 'c'); ck('T1 远距按住右', VK_RIGHT in o._random_move_keys)
o._ladder_mm_goto_tick(93.0, 100.0, 1000, 'c')
ck('T1 跑跳带起跳', o._ladder_jump_phase == 'post_jump' and o._ladder_run_jumped and len(o.jumps) == 1, len(o.jumps))
o._ladder_mm_realign(100.0, 1100, "跑跳满窗没后脑")
ck('T1 跑跳失败回goto不占轮次', o._ladder_jump_phase == 'mm_goto' and o._ladder_realign_round == 0 and not o.reset_called)
o._ladder_mm_goto_tick(96.0, 100.0, 1200, 'c'); ck('T1 near段不再跳(只1跳)', len(o.jumps) == 1)
for t, px in [(1300, 97.5), (1360, 97.5), (1410, 97.5), (1470, 97.5), (1520, 97.5)]:
    o._ladder_mm_goto_tick(px, 100.0, t, 'c')
ck('T1 微调2拍对不齐放弃', o.reset_called and len(o.jumps) == 1, (o.reset_called, len(o.jumps)))

# T2 一开始就在梯下:直跳最多3次后放弃
o = make(mon_x=None)
o._ladder_mm_goto_tick(99.5, 100.0, 2000, 'c'); o._ladder_mm_realign(100.0, 2100, "直跳满窗没后脑")  # 跳1 r1
o._ladder_mm_goto_tick(99.5, 100.0, 2200, 'c'); o._ladder_mm_realign(100.0, 2300, "直跳满窗没后脑")  # 跳2 r2
ck('T2 前两次直跳后未放弃', not o.reset_called and len(o.jumps) == 2, len(o.jumps))
o._ladder_mm_goto_tick(99.5, 100.0, 2400, 'c')   # 跳3
ck('T2 第3跳后尚未判放弃', not o.reset_called and len(o.jumps) == 3, len(o.jumps))
o._ladder_mm_realign(100.0, 2500, "直跳满窗没后脑")   # r3 -> 放弃
ck('T2 第3次直跳失败放弃', o.reset_called and len(o.jumps) == 3, (o.reset_called, len(o.jumps)))

# T3 微调gap后进0~1 -> 直跳
o = make(mon_x=None)
o._ladder_mm_goto_tick(97.5, 100.0, 3000, 'c')   # fine move
o._ladder_mm_goto_tick(97.5, 100.0, 3060, 'c')   # ->gap
o._ladder_mm_goto_tick(99.3, 100.0, 3110, 'c')   # ad0.7 vert
ck('T3 微调后进入直跳窗起跳', o._ladder_jump_phase == 'post_jump' and o._ladder_vert_jumped and len(o.jumps) == 1,
   (o._ladder_jump_phase, len(o.jumps)))

# T4 选不到合格梯超时放弃
o = make(lad_x=None)
o._ladder_mm_goto_tick(100.0, 100.0, 4000, 'c')
ck('T4 首次选不到不立即放弃', not o.reset_called)
o._ladder_mm_goto_tick(100.0, 100.0, 5600, 'c')
ck('T4 连续1.5s选不到放弃', o.reset_called)

# T5 锁定即钉端点+duration
o = make(mon_x=None)
o._ladder_mm_goto_tick(80.0, 100.0, 6000, 'c')
ck('T5 钉住录制梯端点', o._climb_ladder_x == 100.0 and o._climb_ladder_y_top == 40.0
   and o._climb_ladder_y_bottom == 105.0 and o._climb_ladder_duration == 5.0,
   (o._climb_ladder_x, o._climb_ladder_duration))

print()
if fails:
    print('==== %d FAILED: %s' % (len(fails), fails)); raise SystemExit(1)
print('==== ALL GOTO STATE-MACHINE TESTS PASSED ====')
