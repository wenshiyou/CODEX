# -*- coding: utf-8 -*-
"""抓当前游戏窗口一帧,看伤害数字实际颜色/位置。"""
import json, io, os, ctypes, ctypes.wintypes
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"
import mss
from PIL import Image
user32 = ctypes.windll.user32
hwnd = None
EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
def _cb(h, l):
    global hwnd
    b = ctypes.create_unicode_buffer(256); user32.GetWindowTextW(h, b, 256)
    if "PLAY AND HAPPY" in b.value:
        hwnd = h; return False
    return True
user32.EnumWindows(EnumProc(_cb), 0)
r = ctypes.wintypes.RECT()
user32.GetClientRect(hwnd, ctypes.byref(r))
w, h = r.right - r.left, r.bottom - r.top
mon = {"top": r.top, "left": r.left, "width": w, "height": h}
with mss.mss() as sct:
    im = sct.grab(mon)
    img = Image.frombytes("RGB", im.size, im.rgb)
out = os.path.join(P, "_dmg_sample.png")
img.save(out)
print("SAVED", out, img.size)
