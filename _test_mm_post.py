# -*- coding: utf-8 -*-
"""离线单测(闸门1): _ladder_post_jump_process 起跳后流程——
跑跳delay1=100ms内保持朝梯键(带速)不按↑;到点release松左右+按↑;check连续2帧后脑=抓住(via跑跳);
直跳delay1=50ms;满窗无后脑分流realign(跑跳/直跳why正确)。"""
import maple_route_ui as M
C = M.MinimapRouteRecorder
VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN = M.VK_LEFT, M.VK_RIGHT, M.VK_UP, M.VK_DOWN
M._debug_log = lambda *a, **k: None

def make(run):
    o = object.__new__(C)
    o._random_move_keys = set()
    o._climb_start_y = 100.0
    o._ladder_run_jumped = bool(run)
    o._ladder_vert_jumped = not bool(run)
    o._ladder_post_jump_step = 'delay1'
    o._ladder_post_jump_t = 1000
    o._ladder_back_seen_frames = 0
    o._ladder_back_peak = 0.0
    o.released = 0; o.grabbed = []; o.realign_why = None; o.jumps = []
    o._key_down = lambda vk: o._random_move_keys.add(vk)
    o._key_up = lambda vk: o._random_move_keys.discard(vk)
    o._press_game_key = lambda key, duration=120: o.jumps.append((key, duration))
    def _rel():
        o.released += 1
        o._random_move_keys.discard(VK_LEFT); o._random_move_keys.discard(VK_RIGHT)
    o._release_move_conflicts = _rel
    o.back_seq = []
    def _back():
        v = o.back_seq.pop(0) if o.back_seq else (False, 0.0)
        return v
    o._back_head_visible = _back
    def _grab(via, py, t, score):
        o.grabbed.append((via, score))
    o._grab_to_climbing = _grab
    def _realign(py, t, why):
        o.realign_why = why
    o._ladder_mm_realign = _realign
    return o

fails = []
def ck(n, c, e=''):
    print(('PASS ' if c else 'FAIL ') + n + ('  ' + str(e) if e else ''))
    if not c: fails.append(n)

# R 跑跳:100ms内保持右键带速、不按↑;100ms到点松键按↑;连续2帧后脑抓住 via=跑跳
o = make(run=True)
o._random_move_keys.add(VK_RIGHT)          # start_jump('run')保留的朝梯键
o._ladder_post_jump_process(100.0, 1050)   # +50 <100
ck('R1 跑跳50ms仍带速(右键在)且未按↑未release',
   VK_RIGHT in o._random_move_keys and VK_UP not in o._random_move_keys and o.released == 0)
o._ladder_post_jump_process(100.0, 1100)   # +100 到点
ck('R2 100ms松左右+按↑进check',
   o.released == 1 and VK_RIGHT not in o._random_move_keys and VK_UP in o._random_move_keys
   and o._ladder_post_jump_step == 'check', (o.released, sorted(o._random_move_keys)))
o.back_seq = [(True, 0.71), (True, 0.80)]
o._ladder_post_jump_process(100.0, 1150)
o._ladder_post_jump_process(100.0, 1200)
ck('R3 连续2帧后脑=抓住 via跑跳 且记录峰值0.80',
   len(o.grabbed) == 1 and o.grabbed[0][0] == '跑跳' and abs(o.grabbed[0][1] - 0.80) < 1e-6
   and abs(o._ladder_back_peak - 0.80) < 1e-6, (o.grabbed, o._ladder_back_peak))

# V 直跳:50ms到点;满窗1000ms无后脑 -> realign 直跳
o = make(run=False)
o._ladder_post_jump_process(100.0, 1040)   # +40 <50
ck('V1 直跳40ms未按↑', VK_UP not in o._random_move_keys and o.released == 0)
o._ladder_post_jump_process(100.0, 1050)   # +50 到点
ck('V2 50ms松键按↑进check', o.released == 1 and VK_UP in o._random_move_keys and o._ladder_post_jump_step == 'check')
o.back_seq = [(False, 0.30)] * 30
# check起点已重置为1050,推到满窗
t = 1050
while o.realign_why is None and t < 2200:
    t += 100
    o._ladder_post_jump_process(100.0, t)
ck('V3 直跳满窗无后脑分流realign(直跳)', o.realign_why == '直跳满窗没后脑', o.realign_why)

# U 跑跳满窗无后脑 -> realign 跑跳(不占直跳轮次由realign自身测)
o = make(run=True)
o._ladder_post_jump_process(100.0, 1100)   # 跑跳100到点进check
o.back_seq = [(False, 0.20)] * 30
t = 1100
while o.realign_why is None and t < 2300:
    t += 100
    o._ladder_post_jump_process(100.0, t)
ck('U 跑跳满窗无后脑分流realign(跑跳)', o.realign_why == '跑跳满窗没后脑', o.realign_why)

# W 回归(真机id=6 14s死循环根因):跑跳失败realign后run_jumped残留True,再直跳start_jump('vert')必须清回False,
#   post才走50ms、why=直跳满窗(realign才会计直跳轮次、3轮放弃生效);修复前误判跑跳→100ms/why跑跳/轮次永不累计
o = make(run=True)   # 等同 realign 之后 run_jumped=True
o._ladder_mm_start_jump('vert', 1.0, 100.0, 9000, 'c', vx=0.0)
ck('W1 直跳互斥清run_jumped/置vert/左右松',
   o._ladder_run_jumped is False and o._ladder_vert_jumped is True
   and VK_LEFT not in o._random_move_keys and VK_RIGHT not in o._random_move_keys,
   (o._ladder_run_jumped, o._ladder_vert_jumped))
o._ladder_post_jump_process(100.0, 9040)
ck('W2 直跳40ms未按↑未release', VK_UP not in o._random_move_keys and o.released == 0)
o._ladder_post_jump_process(100.0, 9050)
ck('W3 直跳50ms(非跑跳100)松键按↑进check', o.released == 1 and VK_UP in o._random_move_keys
   and o._ladder_post_jump_step == 'check', (o.released, o._ladder_post_jump_step))
o.back_seq = [(False, 0.40)] * 30
t = 9050
while o.realign_why is None and t < 10200:
    t += 100
    o._ladder_post_jump_process(100.0, t)
ck('W4 满窗分流=直跳满窗没后脑(轮次才累计/3轮放弃生效)', o.realign_why == '直跳满窗没后脑', o.realign_why)

print()
if fails:
    print('==== %d FAILED: %s' % (len(fails), fails)); raise SystemExit(1)
print('==== ALL POST-JUMP TESTS PASSED ====')
