# -*- coding: utf-8 -*-
# 临时诊断：连续抓小地图块，对比"全部ffff88像素质心(现算法)"与"最大连通域中心"，定位中心漂移
import win32gui, mss, numpy as np, cv2, time

MAPX, MAPY, MW, MH = 14, 123, 202, 151
LO = np.array([131, 250, 250]); HI = np.array([141, 255, 255])

hwnds = []
def _cb(h, _):
    if 'MapleStory' in win32gui.GetWindowText(h):
        hwnds.append(h)
win32gui.EnumWindows(_cb, None)
print("hwnds=", [(h, win32gui.GetWindowText(h)) for h in hwnds])
h = hwnds[0]
l, t, r, b = win32gui.GetWindowRect(h)
mon = {'left': l, 'top': t, 'width': r - l, 'height': b - t}
sct = mss.mss()

def grab():
    img = np.array(sct.grab(mon))[:, :, :3]
    return img[MAPY:MAPY + MH, MAPX:MAPX + MW].copy()

frames = []
for i in range(24):
    blk = grab()
    mask = cv2.inRange(blk, LO, HI)
    n, labels, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    comps = []
    for k in range(1, n):
        x, y, w, hh, aa = stats[k]
        comps.append((int(aa), int(x), int(y), int(w), int(hh), (float(cent[k][0]), float(cent[k][1]))))
    comps.sort(reverse=True)
    ys, xs = np.where(mask > 0)
    allm = (round(float(xs.mean()), 1), round(float(ys.mean()), 1)) if len(xs) else None
    big = comps[0] if comps else None
    bbc = None
    if big:
        bbc = (round(big[1] + big[3] / 2, 1), round(big[2] + big[4] / 2, 1))  # 最大连通域包围盒中心
    print("f%02d 像素=%d 域数=%d 最大域[面积%d x%d y%d w%d h%d 域质心(%.1f,%.1f) 盒中心%s] 全质心%s" % (
        i, len(xs), n - 1, big[0] if big else -1, big[1] if big else -1, big[2] if big else -1,
        big[3] if big else -1, big[4] if big else -1,
        big[5][0] if big else -1, big[5][1] if big else -1, str(bbc), str(allm)))
    frames.append((blk, comps, allm))
    time.sleep(0.12)

def annot(blk, comps, allm, idx):
    z = 4
    big = cv2.resize(blk, (MW * z, MH * z), interpolation=cv2.INTER_NEAREST)
    if allm:
        cv2.drawMarker(big, (int(allm[0] * z), int(allm[1] * z)), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)  # 红=现算法全质心
    for ci, c in enumerate(comps[:4]):
        col = [(255, 0, 0), (0, 255, 0), (255, 0, 255), (0, 200, 255)][ci]
        aa, x, y, w, hh, ce = c
        cv2.rectangle(big, (x * z, y * z), ((x + w) * z, (y + hh) * z), col, 1)
        cv2.circle(big, (int(ce[0] * z), int(ce[1] * z)), 3, col, -1)                    # 实心=连通域质心
        cv2.drawMarker(big, (int((x + w / 2) * z), int((y + hh / 2) * z)), col, cv2.MARKER_DIAMOND, 14, 1)  # 菱形=包围盒中心
    cv2.imwrite('_dot_%d.png' % idx, big)

for idx in (0, 12, 23):
    annot(*frames[idx], idx)
print("saved _dot_0.png _dot_12.png _dot_23.png")
