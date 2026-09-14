# -*- coding: utf-8 -*-
# 诊断Y上下跳:站定连抓40帧,比较 质心/外接盒中心/膨胀后质心/膨胀后盒中心 的稳定性
import win32gui, mss, numpy as np, cv2, time
MAPX, MAPY, MW, MH = 14, 123, 202, 151
_hw = []
win32gui.EnumWindows(lambda h, _: _hw.append(h) if 'MapleStory' in win32gui.GetWindowText(h) else None, None)
if not _hw:
    print("NO_GAME_WINDOW"); raise SystemExit
h = _hw[0]; l, t, r, b = win32gui.GetWindowRect(h)
mon = {'left': l, 'top': t, 'width': r - l, 'height': b - t}
sct = mss.mss()
KER = np.ones((3, 3), np.uint8)
last = None
A = {'质心': [], '盒中心': [], '膨胀质心': [], '膨胀盒中心': []}
raw_y = []
for i in range(40):
    fr = np.array(sct.grab(mon))[:, :, :3][MAPY:MAPY + MH, MAPX:MAPX + MW]
    m = cv2.inRange(fr, np.array([0, 220, 220]), np.array([205, 255, 255]))
    n, _, st, ce = cv2.connectedComponentsWithStats(m, 8)
    cand = [(int(st[k, cv2.CC_STAT_AREA]), k) for k in range(1, n) if 6 <= st[k, cv2.CC_STAT_AREA] <= 220]
    if not cand:
        time.sleep(0.1); continue
    if last is not None:
        cand.sort(key=lambda c: (ce[c[1]][0]-last[0])**2+(ce[c[1]][1]-last[1])**2)
    else:
        cand.sort(reverse=True)
    k = cand[0][1]; x, y, w, hh = st[k, 0], st[k, 1], st[k, 2], st[k, 3]
    cx, cy = ce[k]
    A['质心'].append((cx, cy)); A['盒中心'].append((x+w/2, y+hh/2))
    md = cv2.dilate(m, KER, iterations=1)
    n2, _, st2, ce2 = cv2.connectedComponentsWithStats(md, 8)
    # 找膨胀后覆盖原团的那个域
    bestk, bestov = 1, -1
    for k2 in range(1, n2):
        ov = ((st2[k2, 0] <= x) and (st2[k2, 1] <= y) and
              st2[k2, 0]+st2[k2, 2] >= x+w and st2[k2, 1]+st2[k2, 3] >= y+hh, st2[k2, cv2.CC_STAT_AREA])
        if ov[1] > bestov: bestk, bestov = k2, ov[1]
    x2, y2, w2, h2 = st2[bestk, 0], st2[bestk, 1], st2[bestk, 2], st2[bestk, 3]
    A['膨胀质心'].append((ce2[bestk][0], ce2[bestk][1])); A['膨胀盒中心'].append((x2+w2/2, y2+h2/2))
    raw_y.append(round(cy, 1))
    last = (cx, cy)
    time.sleep(0.1)
print("有效帧=", len(raw_y), " 质心Y逐帧=", raw_y)
for nm, arr in A.items():
    a = np.array(arr)
    print("%s: X均=%.2f std=%.2f 摆幅=%.1f | Y均=%.2f std=%.2f 摆幅=%.1f Y范围[%.1f,%.1f]" % (
        nm, a[:, 0].mean(), a[:, 0].std(), a[:, 0].max()-a[:, 0].min(),
        a[:, 1].mean(), a[:, 1].std(), a[:, 1].max()-a[:, 1].min(), a[:, 1].min(), a[:, 1].max()))
