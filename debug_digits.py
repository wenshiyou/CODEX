"""调试：从游戏底部状态栏识别HP/MP当前数值"""
import ctypes
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
                for kw in WINDOW_KEYWORDS:
                    if kw in buf.value:
                        _enum_result.append(hwnd)
                        break
    except Exception:
        pass
    return True
user32.EnumWindows(_enum_cb, 0)
hwnd = _enum_result[0]

class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
rect = RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))

with mss.mss() as sct:
    monitor = {"top": rect.top, "left": rect.left,
               "width": rect.right - rect.left, "height": rect.bottom - rect.top}
    frame = np.array(sct.grab(monitor))[:, :, :3]

h, w = frame.shape[:2]
print("frame:", frame.shape)

# 裁底部35像素（状态栏）
status = frame[h-35:h, :]
cv2.imwrite("debug_status.png", status)

# 白字阈值
gray = cv2.cvtColor(status, cv2.COLOR_BGR2GRAY)
_, white = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
cv2.imwrite("debug_status_white.png", white)

# 生成数字模板
digit_templates = {}
for d in range(10):
    img = np.zeros((26, 16), dtype=np.uint8)
    cv2.putText(img, str(d), (1, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 2, cv2.LINE_AA)
    digit_templates[d] = img

# 找白色连通域，按x排序
contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
boxes = []
for c in contours:
    x, y, cw, ch = cv2.boundingRect(c)
    if 5 < cw < 30 and 8 < ch < 25:
        boxes.append((x, y, cw, ch))
boxes.sort(key=lambda b: b[0])
print("找到 %d 个字符区域" % len(boxes))

# 逐个识别
result = []
for x, y, cw, ch in boxes:
    pad = 3
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(w, x + cw + pad)
    y2 = min(35, y + ch + pad)
    char_img = white[y1:y2, x1:x2]
    if char_img.size == 0:
        continue
    # 缩放到模板大小
    char_resized = cv2.resize(char_img, (16, 26))
    best_d = -1
    best_score = -1
    for d, tpl in digit_templates.items():
        res = cv2.matchTemplate(char_resized, tpl, cv2.TM_CCOEFF_NORMED)
        score = res[0][0]
        if score > best_score:
            best_score = score
            best_d = d
    if best_score > 0.4:
        result.append((x, best_d, best_score))
    else:
        result.append((x, '?', best_score))

# 输出识别结果
print("识别结果:")
for x, d, s in result:
    print(f"  x={x}: {d} (score={s:.2f})")

# 尝试解析 HP current / MP current
# 数字按x排序，找 "/" 分隔符
digits_str = ''.join(str(d) for _, d, _ in result if d != '?')
print("数字串:", digits_str)

# 画框标注
disp = status.copy()
for x, y, cw, ch in boxes:
    cv2.rectangle(disp, (x, y), (x+cw, y+ch), (0, 255, 0), 1)
cv2.imwrite("debug_status_boxed.png", disp)
print("已保存 debug_status_boxed.png")
