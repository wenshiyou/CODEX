# -*- coding: utf-8 -*-
"""实测血条检测:抓PLAY AND HAPPY窗口图,跑_detect_monster_hp_bars同款逻辑,画框存图+打印坐标。"""
import cv2, numpy as np, win32gui, win32ui
from ctypes import windll

hwnd = win32gui.FindWindow(None, "PLAY AND HAPPY")
if not hwnd:
    print("找不到PLAY AND HAPPY窗口"); raise SystemExit

# PrintWindow抓图
l, t, r, b = win32gui.GetWindowRect(hwnd)
W, H = r - l, b - t
hwndDC = win32gui.GetWindowDC(hwnd)
mfcDC = win32ui.CreateDCFromHandle(hwndDC)
saveDC = mfcDC.CreateCompatibleDC()
bmp = win32ui.CreateBitmap()
bmp.CreateCompatibleBitmap(mfcDC, W, H)
saveDC.SelectObject(bmp)
windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)
bi = bmp.GetInfo()
bits = bmp.GetBitmapBits(True)
img = np.frombuffer(bits, dtype=np.uint8).reshape(bi['bmHeight'], bi['bmWidth'], 4)
frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
win32gui.DeleteObject(bmp.GetHandle()); saveDC.DeleteDC(); mfcDC.DeleteDC(); win32gui.ReleaseDC(hwnd, hwndDC)
print("截图尺寸:", frame.shape)

# ===== 复制 _detect_monster_hp_bars 逻辑 =====
h, w = frame.shape[:2]
hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
m_g = cv2.inRange(hsv, np.array([35, 90, 80]), np.array([80, 255, 255]))
m_r1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([12, 255, 255]))
m_r2 = cv2.inRange(hsv, np.array([165, 80, 80]), np.array([180, 255, 255]))
mask = cv2.bitwise_or(cv2.bitwise_or(m_r1, m_r2), m_g)
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 2)))
bars = []
contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
for cnt in contours:
    x, y, bw, bh = cv2.boundingRect(cnt)
    if bw > bh * 2 and 15 <= bw <= 90 and 2 <= bh <= 8:
        bars.append((x, y, bw, bh))
if bars:
    filtered = []
    for bb in sorted(bars, key=lambda x: x[2]*x[3], reverse=True):
        if not any(abs(bb[0]-f[0]) < 25 and abs(bb[1]-f[1]) < 12 for f in filtered):
            filtered.append(bb)
    bars = filtered

print("检测到血条数:", len(bars))
for i, (x, y, bw, bh) in enumerate(bars):
    print("  #%d  x=%d y=%d w=%d h=%d" % (i, x, y, bw, bh))

# 画框存图
out = frame.copy()
for (x, y, bw, bh) in bars:
    cv2.rectangle(out, (x, y), (x+bw, y+bh), (0, 0, 255), 2)
cv2.imwrite(r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\_hpbar_test.png", out)
print("已存图: _hpbar_test.png")
