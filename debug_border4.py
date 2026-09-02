"""
调试v8：灰白色边框 + 位置筛选，精确定位地图内容区域
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

# 截取左上角区域
roi = frame[15:230, 0:210].copy()
print(f"ROI: {roi.shape[1]}x{roi.shape[0]}")

# 灰白色边框检测（低饱和度，中高亮度）
hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
border_mask = cv2.inRange(hsv, np.array([0, 0, 120]), np.array([180, 40, 255]))
kernel = np.ones((2, 2), np.uint8)
border_mask = cv2.morphologyEx(border_mask, cv2.MORPH_CLOSE, kernel)
cv2.imwrite("debug_border_mask.png", border_mask)

contours, _ = cv2.findContours(border_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

print("\n所有灰白色矩形:")
candidates = []
for c in contours:
    x, y, cw, ch = cv2.boundingRect(c)
    area = cv2.contourArea(c)
    peri = cv2.arcLength(c, True)
    approx = cv2.approxPolyDP(c, 0.02 * peri, True)
    if cw > 60 and ch > 50 and area > 3000:
        candidates.append((x, y, cw, ch, area, len(approx)))
        print(f"  ({x},{y}) {cw}x{ch} area={area:.0f} corners={len(approx)}")

# 筛选地图内容区域：y > 60（在标题栏下方），宽高比合理
map_candidates = [c for c in candidates if c[1] > 55 and c[2] > 100 and c[3] > 80]

if map_candidates:
    # 选面积最大的
    map_candidates.sort(key=lambda x: x[4], reverse=True)
    map_x, map_y, map_w, map_h, _, _ = map_candidates[0]
    print(f"\n选中地图区域: ({map_x},{map_y}) {map_w}x{map_h}")
else:
    print("\n未找到，使用默认值")
    map_x, map_y, map_w, map_h = 11, 78, 185, 122

# 截取地图内容区域（向内缩2像素去掉边框）
pad = 2
map_area = roi[map_y + pad:map_y + map_h - pad, map_x + pad:map_x + map_w - pad].copy()
cv2.imwrite("debug_map_v8.png", map_area)
print(f"地图内容(去边框): {map_area.shape[1]}x{map_area.shape[0]}")

# 识别黄色光点
hsv_map = cv2.cvtColor(map_area, cv2.COLOR_BGR2HSV)
mask = cv2.inRange(hsv_map, np.array([27, 150, 220]), np.array([30, 255, 255]))
mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 30]

result = map_area.copy()
print(f"\n黄色光点: {len(valid)}个")
for i, c in enumerate(valid):
    M = cv2.moments(c)
    if M["m00"] > 0:
        cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
        area = cv2.contourArea(c)
        cv2.circle(result, (cx, cy), 2, (0, 255, 255), -1)
        cv2.circle(result, (cx, cy), 5, (0, 0, 255), 2)
        print(f"  光点{i}: ({cx},{cy}) area={area:.1f}")

# 画边框
roi_result = roi.copy()
cv2.rectangle(roi_result, (map_x, map_y), (map_x + map_w, map_y + map_h), (0, 0, 255), 2)

result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                        interpolation=cv2.INTER_NEAREST)
cv2.imwrite("debug_map_v8_result.png", result_big)
cv2.imwrite("debug_roi_v8.png", roi_result)
print("\n结果保存: debug_map_v8_result.png, debug_roi_v8.png")
