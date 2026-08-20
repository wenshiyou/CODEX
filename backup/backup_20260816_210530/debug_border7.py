"""
调试v11：用Canny边缘检测找内层地图灰白色边框
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
gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

# Canny边缘检测
edges = cv2.Canny(gray, 30, 100)
# 膨胀让边框连续
edges = cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1)
cv2.imwrite("debug_v11_edges.png", edges)

# 找轮廓
contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

print("所有矩形轮廓（Canny）:")
candidates = []
for c in contours:
    x, y, cw, ch = cv2.boundingRect(c)
    area = cv2.contourArea(c)
    peri = cv2.arcLength(c, True)
    approx = cv2.approxPolyDP(c, 0.02 * peri, True)
    corners = len(approx)
    # 筛选：y>45, 宽>90, 高>70, 4-12个角
    if y > 45 and cw > 80 and ch > 60 and 4 <= corners <= 15 and area > 3000:
        candidates.append((x, y, cw, ch, area, corners))
        print(f"  ({x},{y}) {cw}x{ch} area={area:.0f} corners={corners}")

if candidates:
    # 选最接近正方形/横版的，且面积适中
    candidates.sort(key=lambda x: (x[4], x[2] / x[3]), reverse=True)
    ix, iy, iw, ih, _, _ = candidates[0]
    print(f"\n选中: ({ix},{iy}) {iw}x{ih}")
else:
    print("\nCanny未找到，用灰白色法")
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    border_mask = cv2.inRange(hsv, np.array([0, 0, 100]), np.array([180, 50, 255]))
    border_mask = cv2.morphologyEx(border_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts2, _ = cv2.findContours(border_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts2:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        if y > 45 and cw > 80 and ch > 60 and area > 3000:
            candidates.append((x, y, cw, ch, area, 0))
            print(f"  灰白: ({x},{y}) {cw}x{ch} area={area:.0f}")
    if candidates:
        candidates.sort(key=lambda x: x[4], reverse=True)
        ix, iy, iw, ih, _, _ = candidates[0]
        print(f"选中灰白: ({ix},{iy}) {iw}x{ih}")
    else:
        ix, iy, iw, ih = 11, 78, 185, 122
        print(f"使用默认: ({ix},{iy}) {iw}x{ih}")

# 地图内容区域
pad = 3
map_x = ix + pad
map_y = roi_top + iy + pad
map_w = iw - pad * 2
map_h = ih - pad * 2
print(f"\n地图区域: ({map_x},{map_y}) {map_w}x{map_h}")

map_area = frame[map_y:map_y + map_h, map_x:map_x + map_w].copy()

# 黄色光点
hsv_map = cv2.cvtColor(map_area, cv2.COLOR_BGR2HSV)
mask = cv2.inRange(hsv_map, np.array([25, 120, 180]), np.array([35, 255, 255]))
mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 30]

result = map_area.copy()
print(f"黄色光点: {len(valid)}个")
for c in valid:
    M = cv2.moments(c)
    if M["m00"] > 0:
        cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
        cv2.circle(result, (cx, cy), 2, (0, 255, 255), -1)
        cv2.circle(result, (cx, cy), 5, (0, 0, 255), 2)
        print(f"  光点: ({cx},{cy}) area={cv2.contourArea(c):.1f}")

roi_result = roi.copy()
cv2.rectangle(roi_result, (ix, iy), (ix + iw, iy + ih), (0, 0, 255), 2)

result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                        interpolation=cv2.INTER_NEAREST)
cv2.imwrite("debug_v11_result.png", result_big)
cv2.imwrite("debug_v11_roi.png", roi_result)
print("结果: debug_v11_result.png, debug_v11_roi.png")
