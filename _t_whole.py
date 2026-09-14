# -*- coding: utf-8 -*-
# 离线验证整框匹配几何：已知位置贴"假人模板"，检查脚坐标还原/位移门限/空图拦截（验证完即弃，不入库）
import types
import numpy as np
import cv2
import maple_route_ui as M

Cls = M.MinimapRouteRecorder

def make_tpl(w=60, h=100):
    t = np.zeros((h, w, 3), np.uint8)
    t[5:40, 10:50] = (60, 60, 200)      # 上半 红块(BGR)
    t[40:95, 18:42] = (200, 120, 40)    # 下半 蓝青块
    cv2.circle(t, (30, 25), 12, (255, 255, 255), -1)  # 白色圆,带形状梯度
    return t

def to_tpls(im, ax, ay, sc=Cls.WHOLE_MATCH_SCALE):
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    col = cv2.merge([hsv[:, :, 0], hsv[:, :, 1]])
    h0, w0 = im.shape[:2]
    gh = cv2.resize(g, (max(1, int(w0*sc)), max(1, int(h0*sc))))
    ch = cv2.resize(col, (max(1, int(w0*sc)), max(1, int(h0*sc))))
    return [(gh, ch, ax, ay, h0, w0)]

def fake_self(tpls):
    s = types.SimpleNamespace()
    for n in dir(Cls):
        if n.startswith("WHOLE_"):
            setattr(s, n, getattr(Cls, n))
    s._vote_tpls = tpls; s._vote_sig = "x"; s._vote_diag_t = 0.0
    s._load_char_vote_set = lambda: tpls
    return s

# 1) 已知位置贴人：模板左上(100,120)、基点(30,98) → 脚真值(130,218)
t0 = make_tpl(); AX, AY = 30, 98
frame = np.zeros((400, 400, 3), np.uint8)
LEFT, TOP = 100, 120
frame[TOP:TOP+t0.shape[0], LEFT:LEFT+t0.shape[1]] = t0
true_foot = (LEFT+AX, TOP+AY)
tpls = to_tpls(t0, AX, AY)
s = fake_self(tpls)

r_track = Cls._vote_match_character(s, frame, true_foot, coarse=False)
print("[track 中心=真脚] 返回:", r_track, " 真脚:", true_foot)
assert r_track is not None, "track应找到"
assert abs(r_track[0]-true_foot[0]) <= 2 and abs(r_track[1]-true_foot[1]) <= 2, "脚坐标还原偏差过大"
assert r_track[2] >= Cls.WHOLE_THR, "综合分应过阈值"

# 2) track 中心离真脚 80px(>MAX_MOVE45) 应被位移门限拦掉返回None
r_far = Cls._vote_match_character(s, frame, (true_foot[0]+80, true_foot[1]), coarse=False)
print("[track 中心偏离80] 返回:", r_far, "(应None)")
assert r_far is None, "track位移门限应拦截"

# 3) 同样偏离但 coarse=True 应能找回且不卡门限
r_coarse = Cls._vote_match_character(s, frame, (true_foot[0]+80, true_foot[1]), coarse=True)
print("[coarse 中心偏离80] 返回:", r_coarse)
assert r_coarse is not None and abs(r_coarse[0]-true_foot[0]) <= 2, "coarse应跨窗找回"

# 4) 空黑图(没有人) 综合分应低于阈值返回None
blank = np.zeros((400, 400, 3), np.uint8)
r_blank = Cls._vote_match_character(fake_self(tpls), blank, (200, 200), coarse=True)
print("[空图] 返回:", r_blank, "(应None)")
assert r_blank is None, "空图不应误配"

print("ALL_WHOLE_MATCH_TESTS_PASS")
