"""调试脚本：截取游戏窗口，检测HP/MP血条，画框保存，用于肉眼验证"""
import ctypes
import os
import sys
import numpy as np
import cv2
import mss

user32 = ctypes.windll.user32

# 找游戏窗口
WINDOW_KEYWORDS = ["冒险岛", "风灵"]
_enum_result = []

@ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
def _enum_cb(hwnd, lparam):
    try:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if 0 < length < 500:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                for kw in WINDOW_KEYWORDS:
                    if kw in title:
                        _enum_result.append((hwnd, title))
                        break
    except Exception:
        pass
    return True

user32.EnumWindows(_enum_cb, 0)
if not _enum_result:
    print("未找到游戏窗口")
    sys.exit(1)

hwnd, title = _enum_result[0]
print("找到窗口:", title, "hwnd=", hwnd)

# 获取窗口矩形
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
rect = RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
print("窗口矩形:", rect.left, rect.top, rect.right, rect.bottom)

# 截图
with mss.mss() as sct:
    monitor = {"top": rect.top, "left": rect.left,
               "width": rect.right - rect.left, "height": rect.bottom - rect.top}
    frame = np.array(sct.grab(monitor))[:, :, :3]  # BGRA->BGR

print("截图尺寸:", frame.shape)

# 保存原始截图
cv2.imwrite("debug_capture.png", frame)
print("已保存 debug_capture.png")

# 血条检测（和主程序一样的逻辑）
h, w = frame.shape[:2]
y_start = max(0, h - 25)
roi = frame[y_start:, :]
hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
hp_mask = ((hsv[:,:,0] <= 8) | (hsv[:,:,0] >= 175)) & (hsv[:,:,1] > 80) & (hsv[:,:,2] > 80)
mp_mask = (hsv[:,:,0] >= 100) & (hsv[:,:,0] <= 130) & (hsv[:,:,1] > 80) & (hsv[:,:,2] > 80)

print("HP mask 像素数:", hp_mask.sum(), "MP mask 像素数:", mp_mask.sum())

def find_bar(mask, y_off, fw):
    if mask.sum() < 15:
        return None
    counts = mask.sum(axis=1)
    row = int(np.argmax(counts))
    cols = np.where(mask[row])[0]
    if len(cols) < 15:
        return None
    gaps = np.diff(cols)
    split_points = np.where(gaps > 3)[0]
    if len(split_points) == 0:
        x1, x2 = int(cols[0]), int(cols[-1])
    else:
        best_len = 0
        best_seg = (cols[0], cols[-1])
        start = 0
        for sp in split_points:
            seg_len = cols[sp] - cols[start] + 1
            if seg_len > best_len:
                best_len = seg_len
                best_seg = (int(cols[start]), int(cols[sp]))
            start = sp + 1
        seg_len = cols[-1] - cols[start] + 1
        if seg_len > best_len:
            best_seg = (int(cols[start]), int(cols[-1]))
        x1, x2 = best_seg
    bw = x2 - x1 + 1
    if 20 <= bw <= 500:
        return (x1, y_off + row, bw)
    return None

hp_bar = find_bar(hp_mask, y_start, w)
mp_bar = find_bar(mp_mask, y_start, w)
print("检测到 HP bar:", hp_bar)
print("检测到 MP bar:", mp_bar)

# 画框
disp = frame.copy()
if hp_bar:
    x, y, bw = hp_bar
    cv2.rectangle(disp, (x, y-2), (x+bw, y+2), (0, 0, 255), 2)
    cv2.putText(disp, "HP", (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
if mp_bar:
    x, y, bw = mp_bar
    cv2.rectangle(disp, (x, y-2), (x+bw, y+2), (255, 0, 0), 2)
    cv2.putText(disp, "MP", (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)

# 画搜索区域
cv2.rectangle(disp, (0, y_start), (w, h), (0, 255, 0), 1)
cv2.putText(disp, "search area", (5, y_start+15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

cv2.imwrite("debug_capture_boxed.png", disp)
print("已保存 debug_capture_boxed.png (红框=HP, 蓝框=MP, 绿框=搜索区域)")
