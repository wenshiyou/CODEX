"""
调试v7：精确检测地图内容区域（嵌套边框 + 行亮度）
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
gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

# 方法：用Canny找边缘，然后找内部矩形
edges = cv2.Canny(gray, 30, 100)
kernel = np.ones((3, 3), np.uint8)
edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

# 找所有轮廓（含嵌套）
contours, hierarchy = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

print("所有矩形轮廓:")
rects = []
for i, c in enumerate(contours):
    x, y, cw, ch = cv2.boundingRect(c)
    area = cv2.contourArea(c)
    if cw > 40 and ch > 30:
        parent = hierarchy[0][i][3]
        rects.append((x, y, cw, ch, area, parent, i))
        print(f"  [{i}] ({x},{y}) {cw}x{ch} area={area:.0f} parent={parent}")

# 找地图内容区域：有父轮廓（嵌套在外框内），且宽高比合理
map_rect = None
for x, y, cw, ch, area, parent, idx in rects:
    if parent != -1 and cw > 100 and ch > 80 and area > 8000:
        map_rect = (x, y, cw, ch)
        print(f"\n选中嵌套地图框: ({x},{y}) {cw}x{ch}")
        break

# 如果没找到嵌套框，用行亮度法
if map_rect is None:
    print("\n未找到嵌套框，使用行亮度法")
    # 找小地图外框
    outer = max(rects, key=lambda r: r[4])
    ox, oy, ow, oh, _, _, _ = outer
    # 在外框内找亮度突变行（标题栏底部）
    inner = gray[oy:oy + oh, ox:ox + ow]
    row_mean = inner.mean(axis=1)
    row_diff = np.abs(np.diff(row_mean))
    # 在前60%行找最大突变
    split = int(oh * 0.6)
    map_top_offset = int(np.argmax(row_diff[:split])) + 1
    map_rect = (ox + 3, oy + map_top_offset, ow - 6, oh - map_top_offset - 3)
    print(f"外框: ({ox},{oy}) {ow}x{oh}")
    print(f"地图顶部分界线: y={map_top_offset}")
    print(f"地图区域: ({map_rect[0]},{map_rect[1]}) {map_rect[2]}x{map_rect[3]}")

map_x, map_y, map_w, map_h = map_rect

# 截取地图内容区域
map_area = roi[map_y:map_y + map_h, map_x:map_x + map_w].copy()
cv2.imwrite("debug_map_v7.png", map_area)
print(f"\n地图内容: {map_area.shape[1]}x{map_area.shape[0]}")

# 识别黄色光点
hsv_map = cv2.cvtColor(map_area, cv2.COLOR_BGR2HSV)
mask = cv2.inRange(hsv_map, np.array([27, 150, 220]), np.array([30, 255, 255]))
mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 30]

result = map_area.copy()
print(f"黄色光点: {len(valid)}个")
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
cv2.imwrite("debug_map_v7_result.png", result_big)
cv2.imwrite("debug_roi_v7.png", roi_result)
print("结果保存: debug_map_v7_result.png, debug_roi_v7.png")
