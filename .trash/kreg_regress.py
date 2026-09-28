# -*- coding: utf-8 -*-
# 绿框大小k标定单测(真实_kreg_collect/_blue_box_size+假self)
import importlib.util, warnings
warnings.filterwarnings("ignore")
spec = importlib.util.spec_from_file_location("mru", "maple_route_ui.py")
mru = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mru)
R = mru.MinimapRouteRecorder
DBG = []
mru._debug_log = lambda m: DBG.append(m)

class FakeSelf:
    _kreg_collect = R._kreg_collect
    _blue_box_size = R._blue_box_size
    def __init__(self):
        self._kreg = {'pts': [], 'k': None, 'fit_t': 0, 'log_t': 0}
        self._camera_state = 'deadzone'
        self._player_map_pos = (100.0, 60.0)
        self._target_window_size = (1280, 800)
        self._blue_box = {'width': 84, 'height': 52}   # 手标值(偏大的那个)

NOW = 1000000
TRUE_K = 15.2   # 真实比例:屏幕px/光点px

def feed(fs, dot_xs, scr_xs, t0=NOW):
    for i, (dx, sx) in enumerate(zip(dot_xs, scr_xs)):
        fs._player_map_pos = (dx, 60.0)
        R._kreg_collect(fs, sx, t0 + i*60)   # 60ms间隔>40ms门槛

# case1 死区长基线:屏=15.2×光点+b → k收敛≈15.2,bw_auto=1280/15.2≈84→按真值算应≈84?
# 用真实场景:手标84偏大,真值假设70 → 屏=70×... 不对,k=1280/70=18.3
fs = FakeSelf()
TRUE_K2 = 18.3   # bw_true=1280/18.3≈70
dots = [100 + i*0.8 for i in range(40)]          # 光点走32px
scr = [400 + (d-100)*TRUE_K2 for d in dots]      # 屏走586px
feed(fs, dots, scr)
k = fs._kreg['k']
assert k is not None and abs(k - TRUE_K2) < 0.6, k
bw, bh, auto = R._blue_box_size(fs)
assert auto and abs(bw - round(1280/k)) <= 1 and bw < 84, (bw, k)   # 自动值比手标小(修正"标大了")
print("case1 死区回归收敛: k=%.2f bw_auto=%d(手标84) OK" % (k, bw))

# case2 跟随区样本不收(k不被污染)
fs = FakeSelf()
fs._camera_state = 'following'
feed(fs, [100+i for i in range(30)], [640]*30)   # 跟随:屏不动光点动(假k≈0场景)
assert fs._kreg['k'] is None and fs._kreg['pts'] == []
print("case2 跟随区不收样 OK")

# case3 跨度不足不拟合(站死区不动)
fs = FakeSelf()
feed(fs, [100.0]*30, [640.0]*30)
assert fs._kreg['k'] is None
print("case3 零基线不拟合 OK")

# case4 非线性(R²低)整窗丢:屏与光点无关系(乱数)。逐次喂,每次拟合若R²低即清窗,
# 故喂完后k应保持None(乱数几乎不可能连续8点凑出R²≥0.90的直线)
fs = FakeSelf()
import random
random.seed(7)
dots = [100 + random.uniform(0, 30) for _ in range(30)]
scr = [400 + random.uniform(0, 600) for _ in range(30)]
feed(fs, dots, scr)
assert fs._kreg['k'] is None, ("乱数竟拟出直线", fs._kreg['k'])
print("case4 低R2整窗丢弃 OK")

# case5 换图跳变清窗重采
fs = FakeSelf()
feed(fs, dots[:20], scr[:20])
n_before = len(fs._kreg['pts'])
fs._player_map_pos = (500.0, 60.0)   # 光点跳400px(换图)
R._kreg_collect(fs, 400.0, NOW + 20*60 + 500)
assert len(fs._kreg['pts']) == 1     # 跳变→清窗→只剩新点
print("case5 换图跳变清窗 OK")

# case6 未标定时回退手标
fs = FakeSelf()
bw, bh, auto = R._blue_box_size(fs)
assert not auto and bw == 84 and bh == 52
print("case6 未标定回退手标 OK")

# case7 物理不合理k(0.5)→回退手标(不硬钳出离谱框)
fs = FakeSelf()
fs._kreg['k'] = 0.5
bw, bh, auto = R._blue_box_size(fs)
assert not auto and bw == 84 and bh == 52, (bw, bh, auto)
fs._kreg['k'] = 100.0   # 上方也越界
bw, bh, auto = R._blue_box_size(fs)
assert not auto and bw == 84, (bw, auto)
print("case7 物理越界k回退手标 OK")

# case8 死区+噪声±3px:长基线仍收敛(精度验证)
fs = FakeSelf()
random.seed(1)
dots = [100 + i*0.8 for i in range(40)]
scr = [400 + (d-100)*TRUE_K2 + random.uniform(-3, 3) for d in dots]
feed(fs, dots, scr)
assert abs(fs._kreg['k'] - TRUE_K2) < 1.0, fs._kreg['k']
print("case8 ±3px噪声下k误差<1.0: k=%.2f OK" % fs._kreg['k'])

print("=== ALL 8 PASS ===")
