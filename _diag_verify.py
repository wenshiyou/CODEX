# -*- coding: utf-8 -*-
# 验证:新find_player_dot(整芒星连通域+最近邻) vs 旧ffff88单点, 连抓30帧比稳定性
import win32gui, mss, numpy as np, cv2, time
MAPX, MAPY, MW, MH = 14, 123, 202, 151
_hw = []
win32gui.EnumWindows(lambda h, _: _hw.append(h) if 'MapleStory' in win32gui.GetWindowText(h) else None, None)
h = _hw[0]; l, t, r, b = win32gui.GetWindowRect(h)
mon = {'left': l, 'top': t, 'width': r - l, 'height': b - t}
sct = mss.mss()
def grab():
    img = np.array(sct.grab(mon))[:, :, :3]
    return img[MAPY:MAPY + MH, MAPX:MAPX + MW].copy()

def old_dot(fr):
    m = cv2.inRange(fr, np.array([131, 250, 250]), np.array([141, 255, 255]))
    ys, xs = np.where(m > 0)
    return (round(xs.mean(), 1), round(ys.mean(), 1), len(xs)) if len(xs) else None

last = None
def new_dot(fr):
    global last
    m = cv2.inRange(fr, np.array([0, 220, 220]), np.array([205, 255, 255]))
    n, _, st, ce = cv2.connectedComponentsWithStats(m, 8)
    cand = []
    for k in range(1, n):
        a = int(st[k, cv2.CC_STAT_AREA])
        if 6 <= a <= 220:
            cand.append((a, float(ce[k][0]), float(ce[k][1])))
    if not cand:
        return None, m
    if last is not None:
        cand.sort(key=lambda c: (c[1] - last[0]) ** 2 + (c[2] - last[1]) ** 2)
        ax, ay = cand[0][1], cand[0][2]
        if (ax - last[0]) ** 2 + (ay - last[1]) ** 2 > 28 * 28:
            cand.sort(reverse=True); ax, ay = cand[0][1], cand[0][2]
    else:
        cand.sort(reverse=True); ax, ay = cand[0][1], cand[0][2]
    last = (ax, ay)
    return (round(ax, 1), round(ay, 1), sum(c[0] for c in cand)), m

olds, news = [], []
lastfr, lastmask = None, None
for i in range(30):
    fr = grab()
    o = old_dot(fr); nn, mask = new_dot(fr)
    if o: olds.append(o[:2])
    if nn: news.append(nn[:2]); lastfr, lastmask = fr, mask
    time.sleep(0.1)
def stat(name, arr):
    a = np.array(arr)
    print("%s 帧数=%d 中心均=(%.2f,%.2f) std=(%.2f,%.2f) X[%.1f,%.1f]Y[%.1f,%.1f] 总摆幅=(%.1f,%.1f)" % (
        name, len(a), a[:, 0].mean(), a[:, 1].mean(), a[:, 0].std(), a[:, 1].std(),
        a[:, 0].min(), a[:, 0].max(), a[:, 1].min(), a[:, 1].max(),
        a[:, 0].max() - a[:, 0].min(), a[:, 1].max() - a[:, 1].min()))
stat("旧ffff88", olds)
stat("新芒星团", news)
# 标注最后一帧
if lastfr is not None:
    z = 8
    big = cv2.resize(lastfr, (MW * z, MH * z), interpolation=cv2.INTER_NEAREST)
    n, _, st, ce = cv2.connectedComponentsWithStats(lastmask, 8)
    for k in range(1, n):
        x, y, w, hh, a = st[k]
        if 6 <= a <= 220:
            cv2.rectangle(big, (x * z, y * z), ((x + w) * z, (y + hh) * z), (255, 0, 0), 1)
    if news:
        cx, cy = news[-1]
        cv2.drawMarker(big, (int(cx * z), int(cy * z)), (0, 0, 255), cv2.MARKER_CROSS, 26, 2)
    cv2.imwrite('_dot_new.png', big)
    print("saved _dot_new.png")
