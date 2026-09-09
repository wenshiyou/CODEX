# -*- coding: utf-8 -*-
"""验证 WDA_EXCLUDEFROMCAPTURE：窗口人眼可见但mss拍不到"""
import ctypes, time
import numpy as np, mss
import tkinter as tk

u = ctypes.WinDLL('user32', use_last_error=True)
root = tk.Tk(); root.withdraw()
win = tk.Toplevel(root)
win.geometry("300x200+200+200")
win.configure(bg="red")
win.attributes("-topmost", True)
win.update(); root.update()
time.sleep(0.4)
hwnd = u.FindWindowW(None, None)  # 占位，下面按坐标取
# 用tkinter窗口id
hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()

def red_count():
    with mss.mss() as sct:
        img = np.array(sct.grab({"left":200,"top":200,"width":300,"height":200}))[:,:,:3]
    m = (img[:,:,2]>180)&(img[:,:,0]<80)&(img[:,:,1]<80)
    return int(m.sum())

print("1) 正常 mss红色像素:", red_count(), "(大=能拍到)")
r = u.SetWindowDisplayAffinity(hwnd, 0x11)
win.update(); time.sleep(0.2)
print("   SetWindowDisplayAffinity返回:", r)
print("2) 设隐身 mss红色像素:", red_count(), "(≈0=拍不到)")
u.SetWindowDisplayAffinity(hwnd, 0)
time.sleep(0.15)
print("3) 解除 mss红色像素:", red_count(), "(恢复)")
win.destroy(); root.destroy()
