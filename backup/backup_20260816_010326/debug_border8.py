"""
调试v12：外层大框 + 扫描内层顶部边框，精确定位地图内容区域
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

# 1. 找外层大框（灰白色）
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

ox, oy, ow, oh = outer if outer else (8, 0, 195, 210)
print(f"外层大框: ({ox},{oy}) {ow}x{oh}")

# 2. 在外层大框内，从y=50开始往下扫描，找内层顶部边框
# 顶部边框是一条水平的亮线（灰白色）
inner = gray[oy:oy + oh, ox:ox + ow]
row_mean = inner.mean(axis=1)

# 找y>50范围内，亮度从暗变亮再变暗的位置（边框）
# 边框行的亮度应该较高（>100），且连续多列
top_border_y = None
for y in range(65, int(oh * 0.6)):
    # 检查这一行是否有连续的亮像素（边框）
    row = inner[y, :]
    bright_count = np.sum(row > 110)
    if bright_count > ow * 0.7:  # 超过70%的列是亮的
        top_border_y = y
        print(f"顶部边框行: y={y} 亮度={row_mean[y]:.1f} 亮像素={bright_count}/{ow}")
        break

if top_border_y is None:
    # 兜底：用亮度突变
    row_diff = np.abs(np.diff(row_mean[50:int(oh * 0.7)]))
    top_border_y = int(np.argmax(row_diff)) + 50
    print(f"兜底顶部边框: y={top_border_y}")

# 3. 左右边框：外层大框左右内缩
# 扫描左右边缘，找亮边框
left_border_x = 3
for x in range(2, ow // 4):
    col = inner[:, x]
    if np.sum(col > 100) > oh * 0.3:
        left_border_x = x
        break

right_border_x = ow - 4
for x in range(ow - 3, ow * 3 // 4, -1):
    col = inner[:, x]
    if np.sum(col > 100) > oh * 0.3:
        right_border_x = x
        break

print(f"左边框: x={left_border_x} 右边框: x={right_border_x}")

# 4. 底部边框：外层大框底部内缩
bottom_border_y = oh - 3
for y in range(oh - 4, int(oh * 0.7), -1):
    row = inner[y, :]
    if np.sum(row > 100) > ow * 0.5:
        bottom_border_y = y
        break

print(f"底部边框: y={bottom_border_y}")

# 5. 地图内容区域 = 边框内部
pad = 2
map_x = ox + left_border_x + pad
map_y = roi_top + oy + top_border_y + pad
map_w = right_border_x - left_border_x - pad * 2
map_h = bottom_border_y - top_border_y - pad * 2

print(f"\n地图内容区域: ({map_x},{map_y}) {map_w}x{map_h}")

# 截取并识别光点
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
cv2.rectangle(roi_result, (ox + left_border_x, oy + top_border_y),
              (ox + right_border_x, oy + bottom_border_y), (0, 0, 255), 2)

result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                        interpolation=cv2.INTER_NEAREST)
cv2.imwrite("debug_v12_result.png", result_big)
cv2.imwrite("debug_v12_roi.png", roi_result)
print("\n结果: debug_v12_result.png, debug_v12_roi.png")
