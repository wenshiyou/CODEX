# -*- coding: utf-8 -*-
# 临时诊断2：光点邻域真实颜色 + 多组黄色阈值24帧中心稳定性对比
import win32gui, mss, numpy as np, cv2, time

MAPX, MAPY, MW, MH = 14, 123, 202, 151
_hw = []
win32gui.EnumWindows(lambda h, _: _hw.append(h) if 'MapleStory' in win32gui.GetWindowText(h) else None, None)
h = _hw[0]
l, t, r, b = win32gui.GetWindowRect(h)
mon = {'left': l, 'top': t, 'width': r - l, 'height': b - t}
sct = mss.mss()

def grab():
    img = np.array(sct.grab(mon))[:, :, :3]
    return img[MAPY:MAPY + MH, MAPX:MAPX + MW].copy()

blk = grab()
# 用上一轮定位到的光点附近，全块找现阈值最亮点作为邻域中心
m0 = cv2.inRange(blk, np.array([131, 250, 250]), np.array([141, 255, 255]))
ys0, xs0 = np.where(m0 > 0)
cx, cy = int(xs0.mean()), int(ys0.mean()) if len(xs0) else (63, 86)
print("现阈值核心点=(%d,%d)" % (cx, cy))
print("== 邻域±8内 G>=190且R>=190 的像素 (dx,dy,[B,G,R]) ==")
win = blk[cy - 8:cy + 9, cx - 8:cx + 9]
yy, xx = np.where((win[:, :, 1] >= 190) & (win[:, :, 2] >= 190))
for y_, x_ in zip(yy, xx):
    print(x_ - 8, y_ - 8, win[y_, x_].tolist())

tests = {
    'T0_now_250': (np.array([131, 250, 250]), np.array([141, 255, 255])),
    'T1_g220_b205': (np.array([0, 220, 220]), np.array([205, 255, 255])),
    'T2_g232_b210': (np.array([0, 232, 232]), np.array([210, 255, 255])),
    'T3_g240_b215': (np.array([0, 240, 240]), np.array([215, 255, 255])),
}
hist = {k: [] for k in tests}; areas = {k: [] for k in tests}; ncomp = {k: [] for k in tests}
for i in range(24):
    fr = grab()
    for k, (lo, hi) in tests.items():
        m = cv2.inRange(fr, lo, hi)
        n, lab, st, ce = cv2.connectedComponentsWithStats(m, 8)
        ncomp[k].append(n - 1)
        if n > 1:
            bi = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
            areas[k].append(int(st[bi, cv2.CC_STAT_AREA])); hist[k].append(ce[bi])
        else:
            areas[k].append(0); hist[k].append(None)
    time.sleep(0.1)
for k in tests:
    cs = np.array([c for c in hist[k] if c is not None])
    aa = [a for a in areas[k] if a]
    if len(cs):
        print("%s 连通域数众数=%s 面积min/med/max=%s/%s/%s 中心均=(%.1f,%.1f) 抖动std=(%.2f,%.2f) X[%.0f,%.0f]Y[%.0f,%.0f]" % (
            k, max(set(ncomp[k]), key=ncomp[k].count), min(aa), int(np.median(aa)), max(aa),
            cs[:, 0].mean(), cs[:, 1].mean(), cs[:, 0].std(), cs[:, 1].std(),
            cs[:, 0].min(), cs[:, 0].max(), cs[:, 1].min(), cs[:, 1].max()))
# 存T1标注图
fr = grab(); m = cv2.inRange(fr, *tests['T1_g220_b205'])
n, lab, st, ce = cv2.connectedComponentsWithStats(m, 8)
z = 5; big = cv2.resize(fr, (MW * z, MH * z), interpolation=cv2.INTER_NEAREST)
biggest = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA])) if n > 1 else -1
for kk in range(1, n):
    x, y, w, hh, a = st[kk]; col = (0, 0, 255) if kk == biggest else (255, 0, 0)
    cv2.rectangle(big, (x * z, y * z), ((x + w) * z, (y + hh) * z), col, 1)
    cv2.circle(big, (int(ce[kk][0] * z), int(ce[kk][1] * z)), 3, col, -1)
cv2.imwrite('_dot_t1.png', big)
print("saved _dot_t1.png 连通域数=", n - 1)
