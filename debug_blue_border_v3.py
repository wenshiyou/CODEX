"""
调试v3：蓝色边框检测法（标题可包含版）
策略：投影法检测整个小地图控件的蓝色外边框
- 行投影找顶部/底部边框
- 列投影找左/右边框
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

# 蓝色边框检测：中等饱和度青蓝色
blue_mask = cv2.inRange(hsv, np.array([85, 50, 80]), np.array([120, 220, 240]))
blue_mask = cv2.morphologyEx(blue_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
cv2.imwrite("debug_blue_border_mask3.png", blue_mask)

# 行投影：每行蓝色像素数
row_counts = np.sum(blue_mask > 0, axis=1)
col_counts = np.sum(blue_mask > 0, axis=0)

# 打印前60行的蓝色像素数，看分布
print("\n行投影(前60行):")
for y in range(min(60, roi_h)):
    bar = "#" * int(row_counts[y] / 3)
    print(f"  y={y:3d}: {row_counts[y]:4d} {bar}")

# 找顶部边框：从上往下，第一条蓝色像素数 > roi_w*0.3 的行
top_y = None
for y in range(roi_h):
    if row_counts[y] > roi_w * 0.30:
        top_y = y
        break

# 找底部边框：从下往上，在 top_y+50 以下找第一条蓝色像素数 > roi_w*0.30 的行
bottom_y = None
for y in range(roi_h - 1, max(top_y + 50 if top_y else 50, 0), -1):
    if row_counts[y] > roi_w * 0.30:
        bottom_y = y
        break

print(f"\n顶部边框: y={top_y}")
print(f"底部边框: y={bottom_y}")

if top_y is not None and bottom_y is not None and bottom_y > top_y:
    # 在顶部和底部之间找左右边框
    mid_start = top_y + 5
    mid_end = bottom_y - 5
    if mid_end > mid_start:
        # 左边框：从左往右
        left_x = None
        for x in range(roi_w):
            if col_counts[x] > (mid_end - mid_start) * 0.30:
                left_x = x
                break
        # 右边框：从右往左
        right_x = None
        for x in range(roi_w - 1, -1, -1):
            if col_counts[x] > (mid_end - mid_start) * 0.30:
                right_x = x
                break
    else:
        left_x = right_x = None
else:
    left_x = right_x = None

print(f"左边框: x={left_x}")
print(f"右边框: x={right_x}")

# 兜底
if top_y is None: top_y = 0
if bottom_y is None: bottom_y = roi_h - 1
if left_x is None: left_x = 0
if right_x is None: right_x = roi_w - 1

print(f"\n蓝色边框(ROI内): ({left_x},{top_y}) {right_x-left_x}x{bottom_y-top_y}")

# 地图区域 = 边框内部（内缩2px去边框线）
pad = 2
map_x = left_x + pad
map_y = roi_top + top_y + pad
map_w = right_x - left_x - pad * 2
map_h = bottom_y - top_y - pad * 2

print(f"地图区域(窗口内): ({map_x},{map_y}) {map_w}x{map_h}")

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
cv2.rectangle(roi_result, (left_x, top_y), (right_x, bottom_y), (0, 0, 255), 1)
cv2.rectangle(roi_result, (map_x, map_y - roi_top),
              (map_x + map_w, map_y - roi_top + map_h), (0, 255, 0), 1)

result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                        interpolation=cv2.INTER_NEAREST)
cv2.imwrite("debug_blue_border_v3_result.png", result_big)
cv2.imwrite("debug_blue_border_v3_roi.png", roi_result)
print("\n结果: debug_blue_border_v3_result.png, debug_blue_border_v3_roi.png")
