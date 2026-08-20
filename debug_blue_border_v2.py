"""
调试v2：蓝色边框检测法（改进版）
策略：先定位外层面板，再在标题栏以下区域找内层蓝色地图边框
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
roi_bottom = min(h, int(h * 0.40))
roi_right = min(w, int(w * 0.28))
roi = frame[roi_top:roi_bottom, 0:roi_right].copy()
roi_h, roi_w = roi.shape[:2]
print(f"ROI: {roi_w}x{roi_h}")

hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

# 第一步：用淡蓝色背景定位外层面板范围（粗定位）
pale_blue = cv2.inRange(hsv, np.array([90, 10, 160]), np.array([130, 90, 255]))
pale_blue = cv2.morphologyEx(pale_blue, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
contours, _ = cv2.findContours(pale_blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
panel_rect = None
max_a = 0
for c in contours:
    x, y, cw, ch = cv2.boundingRect(c)
    a = cv2.contourArea(c)
    if cw > 80 and ch > 80 and a > max_a:
        max_a = a
        panel_rect = (x, y, cw, ch)

if panel_rect is None:
    panel_rect = (0, 0, roi_w, roi_h)

px, py, pw, ph = panel_rect
print(f"外层面板: ({px},{py}) {pw}x{ph}")

# 第二步：在面板内、标题栏以下区域检测蓝色边框
# 标题栏约占面板上部 35%，从 30% 处开始搜索
search_top = py + int(ph * 0.30)
search_region = roi[search_top:py + ph, px:px + pw].copy()
search_hsv = hsv[search_top:py + ph, px:px + pw].copy()
print(f"搜索区域: {search_region.shape[1]}x{search_region.shape[0]} (相对面板 y={search_top-py})")

# 蓝色边框：中等饱和度的青蓝色
blue_mask = cv2.inRange(search_hsv, np.array([85, 50, 80]), np.array([120, 220, 240]))
blue_mask = cv2.morphologyEx(blue_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
cv2.imwrite("debug_blue_border_mask2.png", blue_mask)

# 方法：扫描法找蓝色边框的四条边
# 顶部：从上往下找第一条蓝色像素占比>30%的水平线
def find_horizontal_edge(mask, start, end, direction, ratio=0.30):
    h_m, w_m = mask.shape
    for y in range(start, end, direction):
        if y < 0 or y >= h_m:
            break
        row = mask[y, :]
        if np.sum(row > 0) > w_m * ratio:
            return y
    return None

def find_vertical_edge(mask, start, end, direction, y1, y2, ratio=0.30):
    h_m, w_m = mask.shape
    for x in range(start, end, direction):
        if x < 0 or x >= w_m:
            break
        col = mask[y1:y2, x]
        if np.sum(col > 0) > (y2 - y1) * ratio:
            return x
    return None

top_y = find_horizontal_edge(blue_mask, 0, blue_mask.shape[0] // 2, 1, 0.25)
bottom_y = find_horizontal_edge(blue_mask, blue_mask.shape[0] - 1, blue_mask.shape[0] // 2, -1, 0.25)

print(f"顶部边框(相对搜索区): y={top_y}")
print(f"底部边框(相对搜索区): y={bottom_y}")

if top_y is not None and bottom_y is not None and bottom_y > top_y:
    left_x = find_vertical_edge(blue_mask, 0, blue_mask.shape[1] // 2, 1, top_y, bottom_y, 0.25)
    right_x = find_vertical_edge(blue_mask, blue_mask.shape[1] - 1, blue_mask.shape[1] // 2, -1, top_y, bottom_y, 0.25)
else:
    left_x = find_vertical_edge(blue_mask, 0, blue_mask.shape[1] // 2, 1, 0, blue_mask.shape[0])
    right_x = find_vertical_edge(blue_mask, blue_mask.shape[1] - 1, blue_mask.shape[1] // 2, -1, 0, blue_mask.shape[0])

print(f"左边框(相对搜索区): x={left_x}")
print(f"右边框(相对搜索区): x={right_x}")

# 兜底
if top_y is None: top_y = 5
if bottom_y is None: bottom_y = blue_mask.shape[0] - 5
if left_x is None: left_x = 5
if right_x is None: right_x = blue_mask.shape[1] - 5

# 转换回窗口坐标
# 搜索区在 ROI 中的偏移: (px, search_top)
border_x_in_roi = px + left_x
border_y_in_roi = search_top + top_y
border_w = right_x - left_x
border_h = bottom_y - top_y

print(f"\n蓝色边框(ROI内): ({border_x_in_roi},{border_y_in_roi}) {border_w}x{border_h}")

# 地图内容区域 = 边框内部（内缩3px去边框）
pad = 3
map_x = border_x_in_roi + pad
map_y = roi_top + border_y_in_roi + pad
map_w = border_w - pad * 2
map_h = border_h - pad * 2

print(f"地图内容区域(窗口内): ({map_x},{map_y}) {map_w}x{map_h}")

# 截取并检测黄色光点
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

# 画结果
roi_result = roi.copy()
# 外层面板（黄色）
cv2.rectangle(roi_result, (px, py), (px + pw, py + ph), (0, 255, 255), 1)
# 蓝色边框（红色）
cv2.rectangle(roi_result, (border_x_in_roi, border_y_in_roi),
              (border_x_in_roi + border_w, border_y_in_roi + border_h), (0, 0, 255), 1)
# 地图内容区（绿色）
cv2.rectangle(roi_result, (map_x, map_y - roi_top),
              (map_x + map_w, map_y - roi_top + map_h), (0, 255, 0), 1)

result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                        interpolation=cv2.INTER_NEAREST)
cv2.imwrite("debug_blue_border_v2_result.png", result_big)
cv2.imwrite("debug_blue_border_v2_roi.png", roi_result)
print("\n结果: debug_blue_border_v2_result.png, debug_blue_border_v2_roi.png")
