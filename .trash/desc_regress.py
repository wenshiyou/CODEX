# -*- coding: utf-8 -*-
# 影子法下行状态机单测(未绑定方法+假self)
import importlib.util, warnings
warnings.filterwarnings("ignore")
spec = importlib.util.spec_from_file_location("mru", "maple_route_ui.py")
mru = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mru)
R = mru.MinimapRouteRecorder
DBG = []
mru._debug_log = lambda m: DBG.append(m)

NOW = 1000000
VK = dict(up=0x26, down=0x28, left=0x25, right=0x27)

class FakeSelf:
    _dot_moving_state = R._dot_moving_state
    _desc_ladder_side_blocked = R._desc_ladder_side_blocked
    _descend_step = R._descend_step
    _desc_mm_ladder_tick = R._desc_mm_ladder_tick
    _enter_desc_mm_ladder = R._enter_desc_mm_ladder
    _pick_desc_side = R._pick_desc_side
    def __init__(self):
        self._desc_phase = None; self._desc_base_y = 0; self._desc_phase_t = 0
        self._desc_ref_px = None; self._desc_stall_t = 0; self._desc_jumped = False
        self._desc_leap_dir = 1; self._desc_jump_t = 0; self._desc_drop_try = 1
        self._desc_grab_realign = 0; self._desc_side_leap_n = 0; self._desc_mm_no_pick_t = 0
        self._player_map_pos = (50.0, 60.0); self._dot_shadow_pos = (50.0, 60.0)
        self._random_move_keys = set(); self._climb_state = 'descend'
        self._combat_locked_target = None; self._combat_last_target_pos = None
        self._climb_ladder_x = 0.0; self._climb_ladder_y_top = 0.0; self._climb_ladder_y_bottom = 0.0
        self._climb_fail_pause_until = 0; self._b_lock = None
        self.keys = []; self.logs = []; self.resets = 0; self.relocks = 0; self.fails = 0
        self.ladders = []
        self._shadow_mv = 'still'
    # 桩
    def _dot_moving_state(self): return self._shadow_mv
    def _get_fight_config(self): return {'jump_key': 'c'}
    def _key_down(self, vk): self.keys.append(('dn', vk))
    def _key_up(self, vk): self.keys.append(('up', vk))
    def _press_game_key(self, k, duration=120): self.keys.append(('tap', k, duration))
    def _release_move_conflicts(self): self.keys.append(('rel_conf',))
    def _rlog(self, m, *a, **k): self.logs.append(m)
    def _pick_ladder_minimap(self, ladders, px, py, d, x): return None
    def _desc_horiz_walk(self, tx, px, now, stall, dbg): pass
    def _back_head_visible(self): return (self._shadow_mv == 'still' and self._desc_phase == 'dot_grab' and False), 0.5
    def _reset_climb(self): self.resets += 1
    def _reset_lock_after_arrival(self, why): self.relocks += 1
    def _decide_climb_fail_action(self): self.fails += 1

# case1 影子状态机:down/still/left/unknown
fs = FakeSelf()
fs._dot_shadow_pos = (50.0, 60.0); fs._player_map_pos = (50.0, 62.5)
assert R._dot_moving_state(fs) == 'down'
fs._player_map_pos = (52.5, 60.0)
assert R._dot_moving_state(fs) == 'right'
fs._player_map_pos = (50.0, 60.0)
assert R._dot_moving_state(fs) == 'still'
fs._dot_shadow_pos = None
assert R._dot_moving_state(fs) == 'unknown'
print("case1 moving-state OK")

# case2 避梯选侧:右有梯选左
fs = FakeSelf()
fs.ladders = [{'x': 60.0, 'y_top': 40.0, 'y_bottom': 80.0}]   # 右侧10px有梯,梯身覆盖py=60
assert R._desc_ladder_side_blocked(fs, 50.0, 60.0, 1) is True
assert R._desc_ladder_side_blocked(fs, 50.0, 60.0, -1) is False
d = R._pick_desc_side(fs, 50.0, 60.0)
assert d == -1, d
print("case2 avoid-ladder side OK")

# case3 全流程·成功路径:pre_wait→direct_drop(压↓100+跳+松↓)→影子down→dot_fall→still→落地重锁
fs = FakeSelf()
fs._desc_phase = 'pre_wait'; fs._desc_phase_t = NOW
R._descend_step(fs, 50.0, 60.0, NOW + 200)            # 站稳→direct_drop(phase_t=NOW+200)
assert fs._desc_phase == 'direct_drop'
R._descend_step(fs, 50.0, 60.0, NOW + 250)            # 压↓中(只过了50ms<100)
assert ('dn', VK['down']) in fs.keys and fs._desc_jump_t == 0
R._descend_step(fs, 50.0, 60.0, NOW + 350)            # 压↓满100ms→跳→松↓
assert ('tap', 'c', 120) in fs.keys and ('up', VK['down']) in fs.keys
assert fs._desc_jump_t == NOW + 350
fs._shadow_mv = 'down'
R._descend_step(fs, 50.0, 62.0, NOW + 750)            # 跳后300ms:影子down→dot_fall
assert fs._desc_phase == 'dot_fall'
fs._shadow_mv = 'still'
R._descend_step(fs, 50.0, 62.0, NOW + 1500)           # still=落地
assert fs.resets == 1 and fs.relocks == 1 and fs._desc_drop_try == 1
print("case3 success path OK")

# case4 实心台:两跳都没down→转梯子(mm_to_lad)
fs = FakeSelf()
fs._desc_phase = 'direct_drop'; fs._desc_phase_t = NOW; fs._desc_jump_t = 0; fs._desc_drop_try = 1
fs._shadow_mv = 'still'
R._descend_step(fs, 50.0, 60.0, NOW + 50)             # 压↓中(50<100)
assert fs._desc_jump_t == 0
R._descend_step(fs, 50.0, 60.0, NOW + 150)            # 第1跳(压↓满100ms)
assert fs._desc_jump_t == NOW + 150 and fs._desc_drop_try == 1
R._descend_step(fs, 50.0, 60.0, NOW + 500)            # 跳后300ms:still→重置计时,第2次待跳
assert fs._desc_drop_try == 2 and fs._desc_jump_t == 0
R._descend_step(fs, 50.0, 60.0, NOW + 650)            # 第2次压↓满100ms→第2跳
assert fs._desc_jump_t == NOW + 650
R._descend_step(fs, 50.0, 60.0, NOW + 1000)           # 第2跳后300ms:still→转mm_to_lad
assert fs._desc_phase == 'mm_to_lad' and any('实心台' in l for l in fs.logs)
print("case4 solid-platform OK")

# case5 光点丢失挂起:unknown不判不重试
fs = FakeSelf()
fs._desc_phase = 'direct_drop'; fs._desc_phase_t = NOW - 500; fs._desc_jump_t = NOW - 300
fs._shadow_mv = 'unknown'
R._descend_step(fs, 50.0, 60.0, NOW)
assert fs._desc_phase == 'direct_drop' and fs._desc_drop_try == 1   # 没动
print("case5 unknown-suspend OK")

# case6 落地观察超时兜底
fs = FakeSelf()
fs._desc_phase = 'dot_fall'; fs._desc_phase_t = NOW
fs._shadow_mv = 'down'
R._descend_step(fs, 50.0, 62.0, NOW + 4000)
assert fs.resets == 1 and any('超时' in l for l in fs.logs)
print("case6 fall-timeout OK")

# case7 dot_grab:压↓200ms后down→横跳(怪在右按右)
fs = FakeSelf()
fs._desc_phase = 'dot_grab'; fs._desc_phase_t = NOW
fs._combat_locked_target = (80.0, 90.0)   # 怪在右
fs._shadow_mv = 'down'
R._descend_step(fs, 50.0, 60.0, NOW + 250)
assert fs._desc_phase == 'dot_leap' and fs._desc_leap_dir == 1
assert ('dn', VK['right']) in fs.keys and ('up', VK['down']) in fs.keys
print("case7 grab-down->leap(monster side) OK")

# case8 dot_grab没down→再对齐2次→放弃
fs = FakeSelf()
fs._desc_phase = 'dot_grab'; fs._desc_phase_t = NOW
fs._shadow_mv = 'still'; fs._desc_grab_realign = 0
R._descend_step(fs, 50.0, 60.0, NOW + 300)
assert fs._desc_phase == 'mm_to_lad' and fs._desc_grab_realign == 1
R._descend_step(fs, 50.0, 60.0, NOW + 600)   # (mm_to_lad走tick桩,不改相位)
fs._desc_phase = 'dot_grab'; fs._desc_phase_t = NOW + 600
R._descend_step(fs, 50.0, 60.0, NOW + 900)
assert fs._desc_grab_realign == 2 and fs._desc_phase == 'mm_to_lad'
fs._desc_phase = 'dot_grab'; fs._desc_phase_t = NOW + 900
R._descend_step(fs, 50.0, 60.0, NOW + 1200)  # 第3次:超上限放弃
assert fs.fails == 1 and fs.resets == 1
print("case8 realign-giveup OK")

# case9 dot_leap:压方向100ms+跳→200ms后无后脑→dot_fall;有后脑→回dot_grab
fs = FakeSelf()
fs._desc_phase = 'dot_leap'; fs._desc_phase_t = NOW; fs._desc_jumped = False
fs._desc_leap_dir = 1; fs._desc_side_leap_n = 1
R._descend_step(fs, 50.0, 60.0, NOW + 150)            # 压方向满100ms→跳
assert ('tap', 'c', 120) in fs.keys and fs._desc_jumped
R._descend_step(fs, 50.0, 60.0, NOW + 400)            # 跳后200ms:无后脑(fake桩返回False)→dot_fall
assert fs._desc_phase == 'dot_fall'
fs2 = FakeSelf()
fs2._desc_phase = 'dot_leap'; fs2._desc_phase_t = NOW; fs2._desc_jumped = True
fs2._desc_leap_dir = 1; fs2._desc_side_leap_n = 1
fs2._back_head_visible = lambda: (True, 0.8)          # 有后脑=挂梯
R._descend_step(fs2, 50.0, 60.0, NOW + 400)
assert fs2._desc_phase == 'dot_grab'                  # 再横跳
print("case9 leap-backhead OK")

# case10 补跳上限:side_leap_n达DESC_LAD_LEAP_MAX仍见后脑→放弃回主线
fs = FakeSelf()
fs._desc_phase = 'dot_leap'; fs._desc_phase_t = NOW; fs._desc_jumped = True
fs._desc_leap_dir = 1; fs._desc_side_leap_n = mru.DESC_LAD_LEAP_MAX
fs._back_head_visible = lambda: (True, 0.9)
R._descend_step(fs, 50.0, 60.0, NOW + 400)
assert fs.resets == 1 and fs.relocks == 1 and any('挂梯' in l for l in fs.logs)
print("case10 leap-max OK")

print("=== ALL 10 PASS ===")
