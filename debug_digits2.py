"""从已保存的截图验证数字识别"""
import cv2
import numpy as np

frame = cv2.imread("debug_capture.png")
if frame is None:
    print("找不到 debug_capture.png")
    exit(1)

h, w = frame.shape[:2]
print("frame:", frame.shape)

# 裁底部35像素（状态栏）
status = frame[h-35:h, :]
cv2.imwrite("debug_status.png", status)

# 白字阈值
gray = cv2.cvtColor(status, cv2.COLOR_BGR2GRAY)
_, white = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
cv2.imwrite("debug_status_white.png", white)

# 生成数字模板（和游戏字体接近）
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
    if 4 < cw < 30 and 8 < ch < 25:
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
    char_resized = cv2.resize(char_img, (16, 26))
    best_d = -1
    best_score = -1
    for d, tpl in digit_templates.items():
        res = cv2.matchTemplate(char_resized, tpl, cv2.TM_CCOEFF_NORMED)
        score = res[0][0]
        if score > best_score:
            best_score = score
            best_d = d
    result.append((x, best_d, best_score))

print("识别结果:")
for x, d, s in result:
    print(f"  x={x}: {d} (score={s:.2f})")

# 画框
disp = status.copy()
for x, y, cw, ch in boxes:
    cv2.rectangle(disp, (x, y), (x+cw, y+ch), (0, 255, 0), 1)
cv2.imwrite("debug_status_boxed.png", disp)

# 放大显示
disp_big = cv2.resize(disp, (w*2, 70), interpolation=cv2.INTER_NEAREST)
cv2.imwrite("debug_status_big.png", disp_big)
print("已保存")
