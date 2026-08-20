"""
调试v10：找内层地图内容区域的独立灰白色边框（不是外层大框）
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
roi = frame[roi_top:roi_top + 215, 0:210].copy()
print(f"ROI: {roi.shape[1]}x{roi.shape[0]}")

# 灰白色检测
hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
border_mask = cv2.inRange(hsv, np.array([0, 0, 110]), np.array([180, 45, 255]))
kernel = np.ones((2, 2), np.uint8)
border_mask = cv2.morphologyEx(border_mask, cv2.MORPH_CLOSE, kernel)

contours, _ = cv2.findContours(border_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

print("\n所有灰白色轮廓（筛选矩形）:")
inner_rect = None
candidates = []
for c in contours:
    x, y, cw, ch = cv2.boundingRect(c)
    area = cv2.contourArea(c)
    peri = cv2.arcLength(c, True)
    approx = cv2.approxPolyDP(c, 0.03 * peri, True)
    corners = len(approx)
    # 筛选：y>50（在标题栏下方）、宽>100、高>80、近似矩形（4-8个角）
    if y > 45 and cw > 90 and ch > 70 and 4 <= corners <= 10 and area > 5000:
        candidates.append((x, y, cw, ch, area, corners))
        print(f"  候选: ({x},{y}) {cw}x{ch} area={area:.0f} corners={corners}")

if candidates:
    # 选面积最大的（内层地图边框）
    candidates.sort(key=lambda x: x[4], reverse=True)
    ix, iy, iw, ih, _, _ = candidates[0]
    inner_rect = (ix, iy, iw, ih)
    print(f"\n选中内层地图边框: ({ix},{iy}) {iw}x{ih}")
else:
    print("\n未找到内层边框，使用默认值")
    inner_rect = (11, 78, 185, 122)
    ix, iy, iw, ih = inner_rect

# 地图内容区域 = 内层边框内缩3像素
pad = 3
map_x = ix + pad
map_y = roi_top + iy + pad
map_w = iw - pad * 2
map_h = ih - pad * 2

print(f"地图内容区域(窗口内): ({map_x},{map_y}) {map_w}x{map_h}")

# 截取地图内容
map_area = frame[map_y:map_y + map_h, map_x:map_x + map_w].copy()
cv2.imwrite("debug_v10_map.png", map_area)

# 识别黄色光点
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

# 在ROI上画出内层边框
roi_result = roi.copy()
cv2.rectangle(roi_result, (ix, iy), (ix + iw, iy + ih), (0, 0, 255), 2)

result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                        interpolation=cv2.INTER_NEAREST)
cv2.imwrite("debug_v10_result.png", result_big)
cv2.imwrite("debug_v10_roi.png", roi_result)
print("\n结果: debug_v10_result.png, debug_v10_roi.png")
