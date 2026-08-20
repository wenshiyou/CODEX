"""
调试v9：精确检测地图内容区域的左右边界（列亮度分析）
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

# 灰白色外框
hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
border_mask = cv2.inRange(hsv, np.array([0, 0, 100]), np.array([180, 50, 255]))
kernel = np.ones((3, 3), np.uint8)
border_mask = cv2.morphologyEx(border_mask, cv2.MORPH_CLOSE, kernel)
contours, _ = cv2.findContours(border_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

outer = None
max_a = 0
for c in contours:
    x, y, cw, ch = cv2.boundingRect(c)
    a = cv2.contourArea(c)
    if cw > 80 and ch > 100 and a > max_a:
        max_a = a
        outer = (x, y, cw, ch)

ox, oy, ow, oh = outer if outer else (8, 0, 195, 210)
print(f"外框: ({ox},{oy}) {ow}x{oh}")

# 行亮度找顶部分界线
inner = roi[oy:oy + oh, ox:ox + ow]
gray = cv2.cvtColor(inner, cv2.COLOR_BGR2GRAY)
row_mean = gray.mean(axis=1)
row_diff = np.abs(np.diff(row_mean))
ss, se = 50, min(int(oh * 0.7), len(row_diff) - 1)
map_top = int(np.argmax(row_diff[ss:se])) + ss + 1 if se > ss else 75
map_top = max(55, min(map_top, 95))
print(f"顶部分界线: y={map_top}")

# 列亮度找左右边界（在地图内容行范围内分析）
map_region = gray[map_top:, :]
col_mean = map_region.mean(axis=0)
col_diff = np.abs(np.diff(col_mean))

# 左边框：从左往右找第一个亮度突变（从边框到深色地图）
left_bound = 5
for i in range(5, ow // 2):
    if col_mean[i] < 100 and col_mean[i - 1] > 120:
        left_bound = i
        break

# 右边框：从右往左找第一个亮度突变
right_bound = ow - 5
for i in range(ow - 6, ow // 2, -1):
    if col_mean[i] < 100 and col_mean[i + 1] > 120:
        right_bound = i
        break

print(f"列亮度边界: left={left_bound} right={right_bound}")
print(f"地图宽度: {right_bound - left_bound}")

# 打印列亮度看看
print("\n列亮度（每10列）:")
for i in range(0, ow, 10):
    print(f"  col{i}: {col_mean[i]:.1f}", end="")
print()

# 最终地图区域
pad = 2
map_x = ox + left_bound + pad
map_y = roi_top + oy + map_top + pad
map_w = right_bound - left_bound - pad * 2
map_h = oh - map_top - pad * 2

print(f"\n最终地图区域: ({map_x},{map_y}) {map_w}x{map_h}")

# 截取并识别光点
map_area = frame[map_y:map_y + map_h, map_x:map_x + map_w].copy()
hsv_map = cv2.cvtColor(map_area, cv2.COLOR_BGR2HSV)
mask = cv2.inRange(hsv_map, np.array([27, 150, 220]), np.array([30, 255, 255]))
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

# 画边界
roi_result = roi.copy()
cv2.rectangle(roi_result, (ox + left_bound, oy + map_top),
              (ox + right_bound, oy + oh), (0, 0, 255), 1)

result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                        interpolation=cv2.INTER_NEAREST)
cv2.imwrite("debug_v9_result.png", result_big)
cv2.imwrite("debug_v9_roi.png", roi_result)
print("\n结果: debug_v9_result.png, debug_v9_roi.png")
