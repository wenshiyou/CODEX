# -*- coding: utf-8 -*-
# 临时诊断3：光点局部高清放大 + 纯黄中心 vs 黄+橙红整体中心
import win32gui, mss, numpy as np, cv2

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

# 连续抓5帧取最清晰一帧;先用纯黄找到光点
best = None
for _ in range(5):
    fr = grab()
    my = cv2.inRange(fr, np.array([0, 220, 220]), np.array([205, 255, 255]))
    n, lab, st, ce = cv2.connectedComponentsWithStats(my, 8)
    if n > 1:
        bi = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        if st[bi, cv2.CC_STAT_AREA] >= 10:
            best = (fr, bi, st, ce); break
if best is None:
    print("没找到黄光点"); raise SystemExit
fr, bi, st, ce = best
cx, cy = int(round(ce[bi][0])), int(round(ce[bi][1]))
print("纯黄连通域中心=(%d,%d) 外接框 x%d y%d w%d h%d" % (
    cx, cy, st[bi, 0], st[bi, 1], st[bi, 2], st[bi, 3]))

# 1) 局部原图放大8倍(看清光点真实形状/颜色/有没有小三角)
r0, r1 = max(0, cy - 10), min(MH, cy + 11)
c0, c1 = max(0, cx - 10), min(MW, cx + 11)
zoom = cv2.resize(fr[r0:r1, c0:c1], ((c1 - c0) * 10, (r1 - r0) * 10), interpolation=cv2.INTER_NEAREST)
cv2.imwrite('_dot_zoom.png', zoom)

# 2) 暖亮=黄+橙红(R高 G中高 B明显低),看整体形状与中心
B, G, R = fr[:, :, 0], fr[:, :, 1], fr[:, :, 2]
warm = ((R >= 215) & (G >= 180) & (B <= 185) & (R.astype(int) - B >= 50)).astype(np.uint8) * 255
n2, l2, s2, c2 = cv2.connectedComponentsWithStats(warm, 8)
# 只看离纯黄中心最近(<=8)的连通域
print("== 暖亮连通域(距黄中心<=8) ==")
for k in range(1, n2):
    wx, wy, ww, wh, wa = s2[k]
    wcx, wcy = c2[k]
    if abs(wcx - cx) <= 8 and abs(wcy - cy) <= 8:
        print("域 面积%d 框x%d y%d w%d h%d 中心(%.1f,%.1f) 盒中心(%.1f,%.1f)" % (
            wa, wx, wy, ww, wh, wcx, wcy, wx + ww / 2, wy + wh / 2))
z = 8
warm_big = cv2.resize(fr, (MW * z, MH * z), interpolation=cv2.INTER_NEAREST)
wm = cv2.resize(warm, (MW * z, MH * z), interpolation=cv2.INTER_NEAREST)
warm_big[wm > 0] = (0, 0, 255)  # 暖亮像素叠红
cv2.drawMarker(warm_big, (cx * z, cy * z), (255, 0, 0), cv2.MARKER_CROSS, 24, 2)  # 蓝叉=纯黄中心
cv2.imwrite('_dot_warm.png', warm_big)
print("saved _dot_zoom.png _dot_warm.png")
