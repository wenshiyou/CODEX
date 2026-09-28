# -*- coding: utf-8 -*-
# 哨兵五行全量单测(阈值改动后回归:发呆3秒)
import importlib.util, warnings, inspect
warnings.filterwarnings("ignore")
spec = importlib.util.spec_from_file_location("mru", "maple_route_ui.py")
mru = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mru)
R = mru.MinimapRouteRecorder
DBG = []
mru._debug_log = lambda m: DBG.append(m)
assert mru.STALL_IDLE_MS == 3000, mru.STALL_IDLE_MS
assert mru.STALL_CLIMB_MS == 2000 and mru.STALL_WALK_MS == 2000 and mru.STALL_TP_MS == 1000
assert mru.STALL_LADDER_RECHECK_MS == 500 and not hasattr(mru, 'STALL_LADDER_JUMP_EVADE_MS')

class FakeSelf:
    _stall_slide_or_fire = R._stall_slide_or_fire
    _stall_enter = R._stall_enter
    _stall_finish = R._stall_finish
    _stall_fail = R._stall_fail
    _wd_stall_tick = R._wd_stall_tick
    _stall_line_ladder = R._stall_line_ladder
    _stall_line_walk = R._stall_line_walk
    _stall_line_tp = R._stall_line_tp
    _stall_line_lock = R._stall_line_lock
    _stall_line_idle = R._stall_line_idle
    _stall_diag_text = R._stall_diag_text
    _dot_shadow_update = R._dot_shadow_update
    def __init__(self):
        self._stall_lines = {k: {'track': None, 'state': None, 'fails': []}
                             for k in ('ladder', 'walk', 'tp', 'lock', 'idle')}
        self._stall_active = None; self._stall_hold_main = False; self._stall_alert_msg = None
        self._ladder_jump_last_t = 0; self._climb_state = 'none'
        self._player_map_pos = (50.0, 60.0); self._random_running = True
        self._combat_tp_pending = None; self._b_lock_enabled = True
        self._climb_fail_pause_until = 0; self._random_move_keys = set()
        self._monsters = []; self._b_lock = None; self._b_lock_time = 0
        self._combat_first_strike_time = 0; self._combat_target_attacked = False
        self._combat_held_keys = set()
        self._dot_hist = []; self._dot_shadow_pos = None; self._dot_dir_vec = (0.0, 0.0)
        self.keys = []; self.logs = []; self.resets = 0; self.intents_cleared = 0
        self.bv = False
    def _back_head_visible(self): return self.bv, 0.7
    def _release_combat_key(self, vk): self.keys.append(('rel_c', vk))
    def _key_down(self, vk): self.keys.append(('dn', vk))
    def _key_up(self, vk): self.keys.append(('up', vk))
    def _press_game_key(self, k, duration=120): self.keys.append(('tap', k, duration))
    def _rlog(self, m, *a, **k): self.logs.append(m)
    def _get_fight_config(self): return {'jump_key': 'alt'}
    def _key_to_vk(self, k): return 0x38 if k == 'alt' else None
    def _set_b_lock_enabled(self, on, why=''):
        self._b_lock_enabled = on
        if not on: self._b_lock = None; self._b_lock_time = 0
    def _reset_climb(self): self.resets += 1
    def _wd_clear_intent(self, axis=None): self.intents_cleared += 1
    def _release_move_conflicts(self): self.keys.append(('rel_conflicts',))

NOW = 1000000
VK = dict(up=0x26, down=0x28, left=0x25, right=0x27)
it = {'dir': 1, 'start_t': NOW - 3000}

# 1 影子光点指南针回归
fs = FakeSelf()
for i in range(60):
    R._dot_shadow_update(fs, (50 + i*0.5, 60), NOW + i*10)
assert fs._dot_shadow_pos is not None and fs._dot_dir_vec[0] > 20
for i in range(60, 120):
    R._dot_shadow_update(fs, (50, 60), NOW + i*10)
assert abs(fs._dot_dir_vec[0]) < 2
print("1 dot-shadow regress OK")

# 2 卡梯观察
fs = FakeSelf()
fs._climb_state = 'climbing'; fs.bv = True
DBG.clear()
for i in range(30):
    R._wd_stall_dispatch(fs, NOW + i*100, {}, (50.0, 60.0), False)
assert any('[ladder]' in d and '观察' in d for d in DBG)
assert fs.keys == [] and len(fs._stall_lines['ladder']['fails']) == 1
print("2 ladder observe OK")

# 3 卡梯恢复
mru.STALL_SENTINEL_OBSERVE = False
fs = FakeSelf()
fs._climb_state = 'climbing'; fs.bv = True
for i in range(30):
    R._wd_stall_dispatch(fs, NOW + i*100, {}, (50.0, 60.0), False)
assert fs.keys.index(('rel_conflicts',)) < fs.keys.index(('dn', VK['right']))
assert ('dn', 0x38) in fs.keys and ('up', 0x38) in fs.keys
assert fs._b_lock_enabled is True and fs._stall_hold_main is False
print("3 ladder recover OK")

# 4 横跳后500ms重检再跳
fs = FakeSelf()
fs._climb_state = 'climbing'; fs.bv = True
n0 = fs.keys.count(('dn', VK['right']))
for i in range(25):
    R._wd_stall_dispatch(fs, NOW + 5000 + i*100, {}, (50.0, 60.0), False)
assert fs.keys.count(('dn', VK['right'])) == n0 + 1
for i in range(30):
    R._wd_stall_dispatch(fs, NOW + 8000 + i*100, {}, (50.0, 60.0), False)
assert fs.keys.count(('dn', VK['right'])) == n0 + 2
print("4 recheck-500ms rejump OK")

# 5 后脑不可见不触发
fs = FakeSelf()
fs._climb_state = 'climbing'; fs.bv = False
DBG.clear()
for i in range(30):
    R._wd_stall_dispatch(fs, NOW + i*100, {}, (50.0, 60.0), False)
assert not any('[ladder]' in d for d in DBG)
print("5 no-backhead OK")

# 6 发呆3s阈值: 2.2s不触发,3.5s触发
fs = FakeSelf()
fs.bv = False
for i in range(22):
    R._wd_stall_dispatch(fs, NOW + i*100, {}, (50.0, 60.0), False)
assert not any('站台发呆' in l for l in fs.logs), fs.logs
for i in range(35):
    R._wd_stall_dispatch(fs, NOW + 2200 + i*100, {}, (50.0, 60.0), False)
assert any('站台发呆' in l and '光点(50,60)' in l for l in fs.logs), fs.logs
assert len(fs._stall_lines['idle']['fails']) == 1 and fs.keys == []
print("6 idle 3s threshold OK")

# 7 发呆误报排除
fs = FakeSelf(); fs.bv = False
for i in range(40):
    R._wd_stall_dispatch(fs, NOW + i*100, {}, (50.0 + i*0.5, 60.0), False)
assert not any('站台发呆' in l for l in fs.logs)
fs = FakeSelf(); fs.bv = False
fs._combat_target_attacked = True; fs._combat_first_strike_time = NOW + 2000
for i in range(40):
    R._wd_stall_dispatch(fs, NOW + i*100, {}, (50.0, 60.0), False)
assert not any('站台发呆' in l for l in fs.logs)
print("7 idle no-false OK")

# 8 走路行回归
fs = FakeSelf()
for i in range(25):
    R._wd_stall_dispatch(fs, NOW + i*100, {'x': dict(it)}, (50.0, 60.0), False)
assert fs._stall_active == 'walk'
st = fs._stall_lines['walk']['state']
assert st['phase'] == 'watch' and ('tap', 'alt', 120) in fs.keys
R._wd_stall_tick(fs, NOW + 3100)
R._wd_stall_tick(fs, NOW + 3200)
assert ('dn', VK['left']) in fs.keys
fs._player_map_pos = (44.0, 60.0)
R._wd_stall_tick(fs, NOW + 3800)
assert fs._stall_active is None and fs._stall_hold_main is False and fs._b_lock_enabled is True
print("8 walk regress OK")

# 9 瞬移行回归
fs = FakeSelf()
fs._combat_tp_pending = {'t': NOW - 2000, 'axis': 'x', 'dir': 1, 'sx': 0, 'sy': 0}
for i in range(15):
    R._wd_stall_dispatch(fs, NOW + i*100, {}, (50.0, 60.0), False)
assert fs._combat_tp_pending is None and fs._stall_active == 'tp'
R._wd_stall_tick(fs, NOW + 2500)
assert ('dn', VK['right']) in fs.keys
print("9 tp regress OK")

# 10 锁怪行回归
fs = FakeSelf()
fs._monsters = [(100, 100, 150, 150, 0.9)]
for i in range(45):
    R._wd_stall_dispatch(fs, NOW + i*100, {}, (50.0, 60.0), False)
assert any('有怪不锁' in l for l in fs.logs)
fs = FakeSelf()
fs._monsters = [(100, 100, 150, 150, 0.9)]
fs._b_lock = (120, 120); fs._b_lock_time = NOW - 4000
for i in range(45):
    R._wd_stall_dispatch(fs, NOW + i*100, {}, (50.0, 60.0), False)
assert any('锁了不打' in l for l in fs.logs)
print("10 lock regress OK")

# 11 光点丢失清基点
fs = FakeSelf()
fs._stall_lines['walk']['track'] = {'t': NOW, 'bx': 1, 'by': 1, 'dir': 1}
R._wd_stall_dispatch(fs, NOW, {'x': dict(it)}, None, False)
assert all(ln['track'] is None for ln in fs._stall_lines.values())
print("11 dot-lost OK")

# 12 弹窗3次带快照
fs = FakeSelf()
fs.bv = False; fs._monsters = [(100, 100, 150, 150, 0.9)] * 3
for burst in range(3):
    base = NOW + 5000 + burst * 5000
    for i in range(40):
        R._wd_stall_dispatch(fs, base + i*100, {}, (50.0, 60.0), False)
assert fs._stall_alert_msg and '站台反复发呆' in fs._stall_alert_msg
assert '现场:' in fs._stall_alert_msg and '3只怪' in fs._stall_alert_msg
print("12 alert snapshot OK")

# 13 主循环弹窗消费点
src = inspect.getsource(R.run)
assert '_stall_alert_msg' in src and '_show_msg' in src
print("13 popup-in-run OK")

mru.STALL_SENTINEL_OBSERVE = True
print("=== ALL 13 PASS ===")
