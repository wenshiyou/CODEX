# -*- coding: utf-8 -*-
"""只读诊断:用PrintWindow直接抓主蒙板自身绘制内容(绕过EXCLUDEFROMCAPTURE),
看打怪范围框/锚点框在蒙板1280x800里的真实位置,判断是否越界。不改主程序。"""
import win32gui, win32ui, numpy as np, cv2
from ctypes import windll

G, O = [], []
def cb(h, _):
    t = win32gui.GetWindowText(h); c = win32gui.GetClassName(h)
    if 'MapleStory' in t: G.append(h)
    if 'MapleBotOverlay' in c: O.append(h)
win32gui.EnumWindows(cb, None)
print('游戏', G, '蒙板', O)

def shot(h, path):
    l, t, r, b = win32gui.GetWindowRect(h); w, hgt = r-l, b-t
    wdc = win32gui.GetWindowDC(h)
    mdc = win32ui.CreateDCFromHandle(wdc)
    dc = mdc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mdc, w, hgt)
    dc.SelectObject(bmp)
    ok = windll.user32.PrintWindow(h, dc.GetSafeHdc(), 2)  # PW_RENDERFULLCONTENT
    bi = bmp.GetInfo()
    bits = np.frombuffer(bmp.GetBitmapBits(True), np.uint8).reshape(bi['bmHeight'], bi['bmWidth'], 4)
    cv2.imwrite(path, bits)
    win32gui.DeleteObject(bmp.GetHandle()); dc.DeleteDC(); mdc.DeleteDC(); win32gui.ReleaseDC(h, wdc)
    print(path, 'PrintWindow返回=', ok, '尺寸', w, hgt)

if O: shot(O[0], '_diag_overlay_only.png')
if G: shot(G[0], '_diag_game_pw.png')
