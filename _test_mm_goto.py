# -*- coding: utf-8 -*-
"""离线单测(闸门1): 小地图上梯 goto 状态机——2拍锁梯一次锁定/带速跑跳跨rj下降沿/停稳直跳/
微调点动/realign同梯不占轮/直跳3轮放弃/选不到超时/钉录制端点。object.__new__ 绕UI初始化,mock按键。"""
import maple_route_ui as M
C = M.MinimapRouteRecorder
VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN = M.VK_LEFT, M.VK_RIGHT, M.VK_UP, M.VK_DOWN
M._debug_log = lambda *a, **k: None

LAD1 = [{'id': 1, 'x': 100.0, 'y_top': 40.0, 'y_bottom': 105.0, 'duration_sec': 5.0}]

def make(ladders=None, mon_x=None, spx=200.0, cfg=None):
    o = object.__new__(C)
    o.ladders = LAD1 if ladders is None else ladders
    o._player_screen_pos = (spx, 300.0)
    o._ladder_target_mon_x = mon_x
    o._ladder_jump_cfg = cfg or {'rj_l': 7, 'rj_r': 7, 'vl_l': 1, 'vl_r': 1}
    o._random_move_keys = set()
    o._climb_state = 'to_ladder'; o._climb_direction = 1
    o._ladder_run_jumped = False; o._ladder_vert_jumped = False
    o._ladder_jump_phase = 'mm_goto'; o._ladder_post_jump_step = None; o._ladder_post_jump_t = 0
    o._ladder_realign_round = 0
    o._ladder_mm_fine_phase = ''; o._ladder_mm_fine_t = 0; o._ladder_mm_fine_round = 0
    o._ladder_mm_no_pick_t = 0
    o._ladder_mm_lock_id = None; o._ladder_mm_cand_id = None; o._ladder_mm_cand_streak = 0
    o._ladder_mm_pick_t = 0; o._ladder_mm_prev_px = None; o._ladder_mm_prev_ad = None
    o._ladder_mm_approach_streak = 0; o._ladder_mm_still_frames = 0; o._ladder_back_peak = 0.0
    o._climb_ladder_x = 0; o._climb_ladder_y_top = 0; o._climb_ladder_y_bottom = 0
    o._climb_ladder_duration = None; o._climb_start_y = 0; o._climb_fail_pause_until = 0
    o.reset_called = False; o.jumps = []
    o._key_down = lambda vk: o._random_move_keys.add(vk)
    o._key_up = lambda vk: o._random_move_keys.discard(vk)
    o._press_game_key = lambda key, duration=120: o.jumps.append((key, duration))
    o._rlog = lambda *a, **k: None
    o._decide_climb_fail_action = lambda: None
    def _hold(d):
        vk = VK_RIGHT if d > 0 else VK_LEFT; ovk = VK_LEFT if vk == VK_RIGHT else VK_RIGHT
        o._random_move_keys.discard(ovk); o._random_move_keys.add(vk)
    o._hold_toward_ladder = _hold
    def _reset():
        o.reset_called = True; o._climb_state = 'none'; o._ladder_jump_phase = None
        o._ladder_mm_lock_id = None
    o._reset_climb = _reset
    return o

fails = []
def ck(name, cond, extra=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(extra) if extra else ''))
    if not cond: fails.append(name)

def g(o, px, t, py=100.0):
    return o._ladder_mm_goto_tick(px, py, t, 'c')

# A 锁梯2拍才锁,锁后walk按住+钉端点
o = make(mon_x=260.0)
g(o, 80.0, 1000); ck('A1 第1拍候选未锁不走向', o._ladder_mm_lock_id is None and len(o.jumps) == 0)
g(o, 84.0, 1047)
ck('A2 第2拍锁定+walk按住右+钉端点/duration',
   o._ladder_mm_lock_id == 1 and VK_RIGHT in o._random_move_keys and len(o.jumps) == 0
   and o._climb_ladder_x == 100.0 and o._climb_ladder_y_top == 40.0
   and o._climb_ladder_y_bottom == 105.0 and o._climb_ladder_duration == 5.0,
   (o._ladder_mm_lock_id, o._climb_ladder_x, o._climb_ladder_duration))

# B 带速跑跳:跨rj下降沿+连续朝梯,起跳瞬间朝梯键仍按住(不松)
g(o, 89.0, 1094)
g(o, 94.0, 1141)
ck('B 跨线带速跑跳1次且右键保持按住(带速)、未误置直跳',
   o._ladder_jump_phase == 'post_jump' and o._ladder_run_jumped and not o._ladder_vert_jumped
   and len(o.jumps) == 1 and VK_RIGHT in o._random_move_keys and VK_LEFT not in o._random_move_keys,
   (o._ladder_jump_phase, len(o.jumps), sorted(o._random_move_keys)))

# C 高速一帧从rj外冲到ad0 仍判跑跳(不漏、不零速直跳)
o = make(mon_x=260.0)
g(o, 80.0, 2000); g(o, 84.0, 2047); g(o, 89.0, 2094)
g(o, 100.0, 2141)
ck('C 一帧跨rj冲到正下=带速跑跳(非直跳)',
   o._ladder_run_jumped and not o._ladder_vert_jumped and len(o.jumps) == 1,
   (o._ladder_run_jumped, o._ladder_vert_jumped, len(o.jumps)))

# D 停稳直跳:ad<=vl 连续2拍静止才跳,起跳前左右已松
o = make()
g(o, 99.5, 3000)
g(o, 99.5, 3047); ck('D1 锁当帧停稳1拍不原地跳', len(o.jumps) == 0)
g(o, 99.5, 3094)
ck('D2 停稳2拍才直跳且左右全松',
   o._ladder_vert_jumped and not o._ladder_run_jumped and len(o.jumps) == 1
   and VK_LEFT not in o._random_move_keys and VK_RIGHT not in o._random_move_keys,
   (len(o.jumps), sorted(o._random_move_keys)))

# E 高速滑到正下当帧不跳(还在动),松键等停,停稳后才跳
o = make()
g(o, 95.0, 4000); g(o, 95.0, 4047)
g(o, 99.8, 4094)
ck('E1 滑入直跳距离当帧不跳且松键', len(o.jumps) == 0 and VK_RIGHT not in o._random_move_keys)
g(o, 99.8, 4141); g(o, 99.8, 4188)
ck('E2 停稳2拍后直跳', len(o.jumps) == 1 and o._ladder_vert_jumped, len(o.jumps))

# F 微调2拍对不齐(始终ad2.5)放弃回主线
o = make()
g(o, 97.5, 5000); g(o, 97.5, 5047)   # 锁+fine move t5047
g(o, 97.5, 5107)                      # move满->gap
g(o, 97.5, 5157)                      # gap满 ad2.5>1 round2 move
g(o, 97.5, 5217)                      # move满->gap
g(o, 97.5, 5267)                      # gap满 仍2.5 放弃
ck('F 微调2拍对不齐放弃、全程没跳', o.reset_called and len(o.jumps) == 0, (o.reset_called, len(o.jumps)))

# G 微调末拍走到正下->停稳->直跳(不放弃)
o = make()
g(o, 97.5, 6000); g(o, 97.5, 6047)
g(o, 97.5, 6107); g(o, 97.5, 6157)    # round1 gap->round2 move
g(o, 99.4, 6217)                      # round2走到ad0.6(band转vert,滑动当帧等停)
g(o, 99.4, 6264); g(o, 99.4, 6311)    # 停稳2拍->vert
ck('G 微调到位停稳后直跳、未放弃', len(o.jumps) == 1 and o._ladder_vert_jumped and not o.reset_called,
   (len(o.jumps), o.reset_called))

# H 跑跳失败realign不占直跳轮次+同梯保留不重选
o = make(mon_x=260.0)
g(o, 80.0, 7000); g(o, 84.0, 7047); g(o, 89.0, 7094); g(o, 94.0, 7141)  # 跑跳
o._ladder_mm_realign(100.0, 7200, "跑跳满窗没后脑")
ck('H1 跑跳realign不占轮次/不reset/同梯保留/run_jumped置位',
   o._ladder_jump_phase == 'mm_goto' and o._ladder_realign_round == 0 and not o.reset_called
   and o._ladder_mm_lock_id == 1 and o._ladder_run_jumped
   and o._ladder_mm_prev_ad is None and o._ladder_mm_cand_id == 1)
g(o, 96.0, 7300)
ck('H2 realign后仍用同一把锁梯(不重选)', o._ladder_mm_lock_id == 1 and len(o.jumps) == 1)

# I 直跳满3轮放弃
o = make()
o._ladder_mm_realign(100.0, 8000, "直跳满窗没后脑"); ck('I1 第1轮直跳失败不放弃', not o.reset_called and o._ladder_realign_round == 1)
o._ladder_mm_realign(100.0, 8100, "直跳满窗没后脑"); ck('I2 第2轮不放弃', not o.reset_called and o._ladder_realign_round == 2)
o._ladder_mm_realign(100.0, 8200, "直跳满窗没后脑"); ck('I3 第3轮放弃回主线', o.reset_called and o._ladder_realign_round == 3)

# J 选不到合格梯 NOPICK 超时放弃
o = make(ladders=[])
g(o, 100.0, 9000); ck('J1 首次选不到不立即放弃', not o.reset_called)
g(o, 100.0, 10600); ck('J2 连续1.5s选不到放弃', o.reset_called)

# K 锁后 side_sign 翻向不重选(锁一次)
two = [{'id': 0, 'x': 100.0, 'y_top': 40.0, 'y_bottom': 105.0, 'duration_sec': 5.0},
       {'id': 1, 'x': 108.0, 'y_top': 40.0, 'y_bottom': 105.0, 'duration_sec': 5.0}]
o = make(ladders=two, mon_x=260.0, spx=200.0)
g(o, 90.0, 11000); g(o, 90.0, 11047)
ck('K1 怪侧右锁最近梯id0', o._ladder_mm_lock_id == 0 and o._climb_ladder_x == 100.0, o._ladder_mm_lock_id)
o._player_screen_pos = (300.0, 300.0)   # side_sign 翻 -1
g(o, 91.0, 11094)
ck('K2 side_sign翻向后锁不重选', o._ladder_mm_lock_id == 0 and o._climb_ladder_x == 100.0)

# L 走路夹0帧(光点量化1px/帧、时走时停)不打断跨7线跑跳(真机id=6拖到ad=2才跳的回归)
o = make(mon_x=260.0)
g(o, 80.0, 12000); g(o, 84.0, 12047)     # 锁
g(o, 89.0, 12094)                        # ad11 dpx+5 streak1
g(o, 89.0, 12141)                        # 同点 dpx0(量化0帧) streak保持1不清零
g(o, 94.0, 12188)                        # ad6 dpx+5 streak2 跨线->跑跳
ck('L 夹0帧仍在7线带速跑跳(不拖到ad≈2)', o._ladder_run_jumped and len(o.jumps) == 1,
   (o._ladder_run_jumped, len(o.jumps)))

# M 静止光点在rj线两侧(ad8↔7)正负抖动,不触发跑跳(倒退帧清零streak)
o = make()
g(o, 92.0, 13000); g(o, 92.0, 13047)     # 锁 ad8
g(o, 93.0, 13094)                        # ad7 dpx+1 streak1 跨线但streak<2
g(o, 92.0, 13141)                        # ad8 dpx-1 倒退 streak0
g(o, 93.0, 13188)                        # ad7 dpx+1 streak1 仍<2
g(o, 92.0, 13235)                        # 抖回 streak0
ck('M 静止光点7/8来回抖不跑跳', len(o.jumps) == 0 and not o._ladder_run_jumped, len(o.jumps))

print()
if fails:
    print('==== %d FAILED: %s' % (len(fails), fails)); raise SystemExit(1)
print('==== ALL GOTO GATE1 TESTS PASSED ====')
