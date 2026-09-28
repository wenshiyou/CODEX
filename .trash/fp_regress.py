# -*- coding: utf-8 -*-
# 融合预测器单测(未绑定方法+假self,测完即删)
import importlib.util, warnings
warnings.filterwarnings("ignore")
spec = importlib.util.spec_from_file_location("mru", "maple_route_ui.py")
mru = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mru)
R = mru.MinimapRouteRecorder
mru._debug_log = lambda m: None
KP = {}
mru.key_pressed = lambda vk: KP.get(vk, False)
assert mru.KAL_CENTER_BAN is False
assert mru.FP_RAD_BASE == 100 and mru.FP_RAD_TIGHT == 60 and mru.FP_RAD_WIDE == 150

VK = dict(up=0x26, down=0x28, left=0x25, right=0x27)

class FakeSelf:
    _fused_predict_pos = R._fused_predict_pos
    _kal_scene_now = R._kal_scene_now
    def __init__(self):
        self._fp = None
        self._role_track = {'last': (600, 500), 'last_t': 1000000.0}
        self._player_map_pos = (100.0, 50.0)
        self._kal_k = {'walk': None, 'jump': None, 'tp': None}
        self._kal_n = {'walk': 0, 'jump': 0, 'tp': 0}
        self._combat_tp_post_until = 0; self._combat_last_tp_dir = 0
        self._pred_learn_vx = 400.0; self._pred_learn_vy = 120.0; self._pred_learn_tp = 250
        self._climb_state = 'none'
        self._combat_tp_pending = None

NOW = 1000000

# case1 锚点新鲜:预测位=锚点位(贴人不超前),状态含校准,半径收窄
fs = FakeSelf()
fs._role_track = {'last': (600, 500), 'last_t': NOW}
p = R._fused_predict_pos(fs, NOW)
assert p is not None and p[0] == 600 and p[1] == 500 and p[3].startswith('校准')
assert p[2] == mru.FP_RAD_TIGHT
print("case1 fresh-anchor: 贴人+收窄 OK", p)

# case2 锚点新鲜+持续移动:每帧重校准,框仍贴最新锚点(旧黄框超前bug的回归用例)
fs = FakeSelf()
fs._kal_k['walk'] = 20.0
KP.clear(); KP[VK['right']] = True
for i in range(10):
    fs._role_track = {'last': (600 + i*40, 500), 'last_t': NOW + i*100}
    fs._player_map_pos = (100.0 + i*2, 50.0)
    p = R._fused_predict_pos(fs, NOW + i*100)
assert p[0] == 600 + 9*40, p   # 框=当前锚点位,不超前
print("case2 moving-fresh: 框贴人不超前 OK", p[0])

# case3 锚点丢失+k有效:光点位移×k外推(事实通道)
fs = FakeSelf()
fs._kal_k['walk'] = 20.0
fs._role_track = {'last': (600, 500), 'last_t': NOW}      # NOW校准一次
R._fused_predict_pos(fs, NOW)
KP.clear(); KP[VK['right']] = True
fs._role_track = {'last': (600, 500), 'last_t': NOW}      # 丢失:锚点停在NOW
fs._player_map_pos = (103.0, 50.0)                        # 光点右移3px
p = R._fused_predict_pos(fs, NOW + 500)
assert p[0] == 600 + 3*20 and '光点' in p[3], p
print("case3 lost+k-valid: 光点外推 OK", p)

# case4 锚点丢失+k无效:回退意图通道(按键×学习速度)
fs = FakeSelf()
fs._role_track = {'last': (600, 500), 'last_t': NOW}
R._fused_predict_pos(fs, NOW)
KP.clear(); KP[VK['right']] = True
fs._player_map_pos = None                                  # 光点也丢(极端:双通道只剩意图)
p = R._fused_predict_pos(fs, NOW + 500)
assert p[0] == 600 + 400*0.5 and '意图右' in p[3], p
print("case4 lost+k-none: 意图回退 OK", p)

# case5 瞬移后摇+意图通道:注入学习瞬移距离
fs = FakeSelf()
fs._role_track = {'last': (600, 500), 'last_t': NOW}
R._fused_predict_pos(fs, NOW)
fs._combat_tp_post_until = NOW + 5000; fs._combat_last_tp_dir = 1
p = R._fused_predict_pos(fs, NOW + 500)
assert p[0] == 600 + 250 and '瞬移注入' in p[3], p
print("case5 tp-inject OK", p)

# case6 瞬移+k有效:光点跳变被事实通道捕获,不重复注入
fs = FakeSelf()
fs._kal_k['tp'] = 20.0
fs._role_track = {'last': (600, 500), 'last_t': NOW}
R._fused_predict_pos(fs, NOW)
fs._combat_tp_post_until = NOW + 5000; fs._combat_last_tp_dir = 1
fs._player_map_pos = (112.5, 50.0)                        # 光点跳12.5px×20=250屏幕px
p = R._fused_predict_pos(fs, NOW + 300)
assert p[0] == 600 + 250 and '光点' in p[3], p            # 只算一次(事实通道)
print("case6 tp+fact: 光点捕获不双计 OK", p)

# case7 爬梯Y外推:climbing+按↑,Y上移
fs = FakeSelf()
fs._climb_state = 'climbing'
fs._role_track = {'last': (600, 500), 'last_t': NOW}
R._fused_predict_pos(fs, NOW)
KP.clear(); KP[VK['up']] = True
fs._player_map_pos = (100.0, 47.0)                        # 光点Y上移3(k没学→Y不动,vy外推)
p = R._fused_predict_pos(fs, NOW + 500)
assert p[1] == 500 - 120*0.5 and '上梯' in p[3], p
print("case7 climb-Y intent OK", p)

# case8 半径三档:刚校准60/丢失1s=100/丢失>2s=150
fs = FakeSelf()
fs._kal_k['walk'] = 20.0
fs._role_track = {'last': (600, 500), 'last_t': NOW}
p0 = R._fused_predict_pos(fs, NOW)
p1 = R._fused_predict_pos(fs, NOW + 1000)                 # 丢失1s
p2 = R._fused_predict_pos(fs, NOW + 3000)                 # 丢失3s
assert p0[2] == 60 and p1[2] == 100 and p2[2] == 150, (p0[2], p1[2], p2[2])
print("case8 radius三档 OK")

# case9 无锚点返回None+清态
fs = FakeSelf()
fs._role_track = None
assert R._fused_predict_pos(fs, NOW) is None and fs._fp is None
fs._role_track = {'last': None}
assert R._fused_predict_pos(fs, NOW) is None
print("case9 no-anchor OK")

print("=== ALL 9 PASS ===")
