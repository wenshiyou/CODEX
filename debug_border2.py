"""
调试v6：用灰白色边框自动检测地图内容区域，验证黄色光点
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

# 截取左上角区域（包含完整小地图）
roi = frame[15:230, 0:210].copy()
print(f"ROI: {roi.shape[1]}x{roi.shape[0]}")

# 用灰白色边框检测
hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
border_mask = cv2.inRange(hsv, np.array([0, 0, 100]), np.array([180, 50, 255]))
kernel = np.ones((3, 3), np.uint8)
border_mask = cv2.morphologyEx(border_mask, cv2.MORPH_CLOSE, kernel)

contours, _ = cv2.findContours(border_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

# 找地图内容区域的边框（面积适中的矩形）
candidates = []
for c in contours:
    x, y, cw, ch = cv2.boundingRect(c)
    area = cv2.contourArea(c)
    if cw > 80 and ch > 60 and area > 5000:
        candidates.append((x, y, cw, ch, area))
        print(f"候选边框: ({x},{y}) {cw}x{ch} area={area:.0f}")

# 选最可能的地图区域（不是最大的外框，而是内部的地图框）
candidates.sort(key=lambda x: x[4])  # 按面积排序
if len(candidates) >= 2:
    # 第二个通常是内部地图框
    map_x, map_y, map_w, map_h, _ = candidates[-2]
elif candidates:
    map_x, map_y, map_w, map_h, _ = candidates[0]
else:
    print("未找到边框，使用默认值")
    map_x, map_y, map_w, map_h = 11, 63, 185, 122

print(f"\n选中地图区域(ROI内): ({map_x},{map_y}) {map_w}x{map_h}")

# 转换到游戏窗口坐标系
win_map_x = map_x
win_map_y = 15 + map_y
print(f"地图区域(窗口内): ({win_map_x},{win_map_y}) {map_w}x{map_h}")

# 截取地图内容区域
map_area = roi[map_y:map_y + map_h, map_x:map_x + map_w].copy()
cv2.imwrite("debug_map_auto.png", map_area)
print(f"地图内容: {map_area.shape[1]}x{map_area.shape[0]}")

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

# 在ROI上画出地图区域边框
roi_result = roi.copy()
cv2.rectangle(roi_result, (map_x, map_y), (map_x + map_w, map_y + map_h), (0, 0, 255), 2)

# 放大显示
result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                        interpolation=cv2.INTER_NEAREST)
cv2.imwrite("debug_map_auto_result.png", result_big)
cv2.imwrite("debug_roi_with_border.png", roi_result)
print("\n结果保存: debug_map_auto_result.png, debug_roi_with_border.png")
