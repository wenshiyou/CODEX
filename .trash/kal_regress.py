# -*- coding: utf-8 -*-
# 光屏比率学习+黄框预测单测(未绑定方法+假self,测完即删)
import importlib.util, warnings
warnings.filterwarnings("ignore")
spec = importlib.util.spec_from_file_location("mru", "maple_route_ui.py")
mru = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mru)
R = mru.MinimapRouteRecorder
DBG = []
mru._debug_log = lambda m: DBG.append(m)

# key_pressed桩:由FakeSelf按键状态驱动
KP = {}
mru.key_pressed = lambda vk: KP.get(vk, False)

class FakeSelf:
    _kal_scene_now = R._kal_scene_now
    _kalman_sample = R._kalman_sample
    _dot_shadow_update = R._dot_shadow_update
    def __init__(self):
        self._kal_k = {'walk': None, 'jump': None, 'tp': None}
        self._kal_n = {'walk': 0, 'jump': 0, 'tp': 0}
        self._kal_smp = None; self._kal_drop_streak = 0; self._kal_pause_until = 0
        self._player_map_pos = None; self._dot_shadow_pos = None; self._dot_dir_vec = (0.0, 0.0)
        self._dot_hist = []
        self._combat_tp_post_until = 0; self._combat_last_jump = 0
        self._climb_state = 'none'
        self._role_track = {'last': (600, 500), 'foot': (600, 500), 'last_t': 1.0}
        self.window_rect = {'width': 1280}

NOW = 1000000
VK_L, VK_R, VK_U, VK_D, VK_J = 0x25, 0x27, 0x26, 0x28, 0x2D

# case1 走路样本学习:k收敛(光点1px=屏20px,真实比率20)
fs = FakeSelf()
KP.clear(); KP[VK_R] = True
fs._player_map_pos = (100.0, 50.0)
R._kalman_sample(fs, 600, NOW)          # 立对(屏X=600边带,不触发中带丢弃)
for i in range(1, 12):
    fs._player_map_pos = (100.0 + i*2.0, 50.0)   # 光点每500ms走2px
    R._kalman_sample(fs, 600 + i*40, NOW + i*500)  # 屏每500ms走40px(边带640~1040之外,600+i*40到1000)
assert fs._kal_k['walk'] is not None and 15 < fs._kal_k['walk'] < 25, fs._kal_k['walk']
assert fs._kal_n['walk'] >= 5
print("case1 walk k converge OK k=%.1f n=%d" % (fs._kal_k['walk'], fs._kal_n['walk']))

# case2 已废弃删除:中带硬丢(KAL_CENTER_BAN)语义已改降权,中带防污染职责移交kreg回归+离群门(case4覆盖)

# case3 方向异号丢弃
fs = FakeSelf()
KP.clear(); KP[VK_R] = True
fs._player_map_pos = (100.0, 50.0)
R._kalman_sample(fs, 200, NOW)
fs._player_map_pos = (102.0, 50.0)      # 光点向右
R._kalman_sample(fs, 150, NOW + 500)    # 屏向左(异号)
assert fs._kal_k['walk'] is None
print("case3 opposite-dir dropped OK")

# case4 离群丢弃+连丢3暂停5秒(每对独立:t0立对→t0+500结算;离群样本位移给足:屏60px/光点1px→k=60离群)
fs = FakeSelf()
fs._kal_k['walk'] = 20.0; fs._kal_n['walk'] = 5
KP.clear(); KP[VK_R] = True
for i in range(3):
    fs._player_map_pos = (100.0, 50.0)
    R._kalman_sample(fs, 200, NOW + i*1000)          # t0立对(屏X=200边带)
    fs._player_map_pos = (101.0, 50.0)                # 光点+1px
    R._kalman_sample(fs, 260, NOW + i*1000 + 500)     # 屏+60px→k=60,离群200%>40%丢弃
assert fs._kal_k['walk'] == 20.0 and fs._kal_pause_until >= NOW + 1500 + 5000, (fs._kal_k, fs._kal_pause_until)
print("case4 outlier x3 -> pause OK (pause_until=%d)" % fs._kal_pause_until)

# case5 三场景互不污染: tp场景单独立对
fs = FakeSelf()
fs._kal_k = {'walk': 20.0, 'jump': None, 'tp': None}
KP.clear(); KP[VK_R] = True
fs._combat_tp_post_until = NOW + 10000  # 瞬移后摇窗
fs._player_map_pos = (100.0, 50.0)
R._kalman_sample(fs, 200, NOW)          # 场景=tp立对
assert fs._kal_smp and fs._kal_smp['scene'] == 'tp'
fs._player_map_pos = (105.0, 50.0)
R._kalman_sample(fs, 320, NOW + 300)    # 瞬移:光点5px屏120px,k=24
assert fs._kal_k['tp'] is not None and 20 < fs._kal_k['tp'] < 28, fs._kal_k
assert fs._kal_k['walk'] == 20.0        # walk没被动
print("case5 scene isolation OK")

# case9 光点丢时采样对作废(防脏跨窗)
fs = FakeSelf()
KP.clear(); KP[VK_R] = True
fs._player_map_pos = (100.0, 50.0)
R._kalman_sample(fs, 200, NOW)
fs._player_map_pos = None
R._kalman_sample(fs, 250, NOW + 200)   # 光点丢:采样对作废
assert fs._kal_smp is None
fs._player_map_pos = (102.0, 50.0)
R._kalman_sample(fs, 210, NOW + 400)   # 重新立对
assert fs._kal_smp is not None and fs._kal_smp['scene'] == 'walk'
print("case9 dot-lost invalidates pair OK")

print("=== ALL 9 PASS ===")
