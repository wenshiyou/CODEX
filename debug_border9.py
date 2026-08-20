"""
调试v13：扫描线法自动检测地图内容区域边框（适应不同大小）
思路：外层大框内，从上下左右扫描连续亮线（灰白色边框）
"""
import ctypes, struct, mss, numpy as np, cv2, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

user32 = ctypes.windll.user32
hwnd = user32.FindWindowW(None, "冒险岛怀旧服")
rect = ctypes.create_string_buffer(16)
user32.GetWindowRect(hwnd, rect)
left, top, right, bottom = struct.unpack("llll", rect.raw)
w, h = right - left, bottom - top

sct = mss.mss()
frame = np.array(sct.grab({"left": left, "top": top, "width": w, "height": h}))[:, :, :3]

roi_top = 15
roi = frame[roi_top:roi_top + 230, 0:220].copy()
gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
print(f"ROI: {roi.shape[1]}x{roi.shape[0]}")

# 1. 找外层大框（灰白色检测）
hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
border_mask = cv2.inRange(hsv, np.array([0, 0, 100]), np.array([180, 50, 255]))
border_mask = cv2.morphologyEx(border_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
contours, _ = cv2.findContours(border_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

outer = None
max_a = 0
for c in contours:
    x, y, cw, ch = cv2.boundingRect(c)
    a = cv2.contourArea(c)
    if cw > 80 and ch > 100 and a > max_a:
        max_a = a
        outer = (x, y, cw, ch)

ox, oy, ow, oh = outer if outer else (5, 0, 200, 220)
print(f"外层大框: ({ox},{oy}) {ow}x{oh}")

# 2. 在外层大框内用扫描线法找内层地图边框
inner = gray[oy:oy + oh, ox:ox + ow]

def find_horizontal_border(img, start_y, end_y, direction=1, threshold=110, ratio=0.65):
    """从start_y向end_y扫描，找第一条亮像素占比>ratio的水平线"""
    h_img = img.shape[0]
    for y in range(start_y, end_y, direction):
        if y < 0 or y >= h_img:
            break
        row = img[y, :]
        bright = np.sum(row > threshold)
        if bright > ow * ratio:
            return y
    return None

def find_vertical_border(img, start_x, end_x, direction=1, y_range=None, threshold=110, ratio=0.4):
    """从start_x向end_x扫描，找第一条亮像素占比>ratio的垂直线"""
    w_img = img.shape[1]
    y1, y2 = y_range if y_range else (0, img.shape[0])
    for x in range(start_x, end_x, direction):
        if x < 0 or x >= w_img:
            break
        col = img[y1:y2, x]
        bright = np.sum(col > threshold)
        if bright > (y2 - y1) * ratio:
            return x
    return None

# 顶部边框：从外层高度的35%开始往下找，要求高亮度连续线
top_y = find_horizontal_border(inner, int(oh * 0.35), int(oh * 0.6), 1, 130, 0.75)
# 底部边框：从底部往上找
bottom_y = find_horizontal_border(inner, oh - 3, int(oh * 0.5), -1, 130, 0.75)

print(f"顶部边框: y={top_y}")
print(f"底部边框: y={bottom_y}")

if top_y and bottom_y and bottom_y > top_y:
    # 左右边框：在顶部和底部之间的范围内找
    left_x = find_vertical_border(inner, 3, ow // 2, 1, (top_y, bottom_y), 130, 0.45)
    right_x = find_vertical_border(inner, ow - 4, ow // 2, -1, (top_y, bottom_y), 130, 0.45)
else:
    left_x = find_vertical_border(inner, 2, ow // 2, 1)
    right_x = find_vertical_border(inner, ow - 3, ow // 2, -1)

print(f"左边框: x={left_x}")
print(f"右边框: x={right_x}")

# 兜底值
if top_y is None: top_y = int(oh * 0.38)
if bottom_y is None: bottom_y = oh - 3
if left_x is None: left_x = 3
if right_x is None: right_x = ow - 3

# 3. 地图内容区域 = 边框内部（内缩2像素）
pad = 2
map_x = ox + left_x + pad
map_y = roi_top + oy + top_y + pad
map_w = right_x - left_x - pad * 2
map_h = bottom_y - top_y - pad * 2

print(f"\n地图内容区域(窗口内): ({map_x},{map_y}) {map_w}x{map_h}")

# 4. 截取并识别黄色光点
map_area = frame[map_y:map_y + map_h, map_x:map_x + map_w].copy()
hsv_map = cv2.cvtColor(map_area, cv2.COLOR_BGR2HSV)
mask = cv2.inRange(hsv_map, np.array([25, 120, 180]), np.array([35, 255, 255]))
mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 30]

result = map_area.copy()
print(f"\n黄色光点: {len(valid)}个")
for c in valid:
    M = cv2.moments(c)
    if M["m00"] > 0:
        cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
        cv2.circle(result, (cx, cy), 2, (0, 255, 255), -1)
        cv2.circle(result, (cx, cy), 5, (0, 0, 255), 2)
        print(f"  光点: ({cx},{cy}) area={cv2.contourArea(c):.1f}")

# 画边框
roi_result = roi.copy()
cv2.rectangle(roi_result, (ox + left_x, oy + top_y),
              (ox + right_x, oy + bottom_y), (0, 0, 255), 2)

result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                        interpolation=cv2.INTER_NEAREST)
cv2.imwrite("debug_v13_result.png", result_big)
cv2.imwrite("debug_v13_roi.png", roi_result)
print("\n结果: debug_v13_result.png, debug_v13_roi.png")
