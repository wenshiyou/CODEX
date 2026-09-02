"""
调试：蓝色边框检测法
用饱和蓝色边框代替灰白扫描线法，精确定位地图内容区域
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

# 搜索区域：窗口左上部分
roi_top = 15
roi_bottom = min(h, int(h * 0.40))
roi_right = min(w, int(w * 0.28))
roi = frame[roi_top:roi_bottom, 0:roi_right].copy()
print(f"ROI: {roi.shape[1]}x{roi.shape[0]}")

hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

# 蓝色边框：中等饱和度的蓝色/青色（区别于淡蓝色背景 S<90）
# 边框颜色偏青蓝，H 约 90-115，S 约 60-200，V 约 100-230
blue_border_mask = cv2.inRange(hsv, np.array([85, 50, 80]), np.array([120, 220, 240]))
cv2.imwrite("debug_blue_border_mask.png", blue_border_mask)

# 形态学闭运算连接边框线段
kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
blue_border_mask = cv2.morphologyEx(blue_border_mask, cv2.MORPH_CLOSE, kernel)
blue_border_mask = cv2.morphologyEx(blue_border_mask, cv2.MORPH_OPEN, kernel)

# 找轮廓
contours, _ = cv2.findContours(blue_border_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

# 找最像矩形边框的轮廓：面积大、宽高比合理、位置靠下（跳过标题栏按钮）
best_rect = None
best_score = 0
for c in contours:
    x, y, cw, ch = cv2.boundingRect(c)
    area = cv2.contourArea(c)
    if cw < 60 or ch < 60:
        continue
    ratio = cw / ch
    if not (0.5 < ratio < 2.5):
        continue
    # 评分：面积大 + 填充率低（边框是空心的，轮廓面积/外接矩形面积小）
    fill_ratio = area / (cw * ch) if cw * ch > 0 else 1
    # 边框的 fill_ratio 应该较小（< 0.3），实心区域较大
    score = area * (1.0 - fill_ratio) if fill_ratio < 0.5 else area * 0.1
    if score > best_score:
        best_score = score
        best_rect = (x, y, cw, ch)

if best_rect is None:
    # 兜底：用所有蓝色像素的外接矩形
    ys, xs = np.where(blue_border_mask > 0)
    if len(xs) > 100:
        best_rect = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min()), int(ys.max() - ys.min()))
    else:
        best_rect = (5, 30, 180, 150)

bx, by, bw, bh = best_rect
print(f"蓝色边框外接矩形: ({bx},{by}) {bw}x{bh}")

# 地图内容区域 = 边框内部（边框本身约1-2px，内缩3px去掉边框）
pad = 3
map_x = bx + pad
map_y = roi_top + by + pad
map_w = bw - pad * 2
map_h = bh - pad * 2

print(f"地图内容区域(窗口内): ({map_x},{map_y}) {map_w}x{map_h}")

# 截取地图内容区并检测黄色光点
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

# 画边框和地图区域
roi_result = roi.copy()
cv2.rectangle(roi_result, (bx, by), (bx + bw, by + bh), (0, 0, 255), 1)
cv2.rectangle(roi_result, (map_x, map_y - roi_top),
              (map_x + map_w, map_y - roi_top + map_h), (0, 255, 0), 1)

result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                        interpolation=cv2.INTER_NEAREST)
cv2.imwrite("debug_blue_border_result.png", result_big)
cv2.imwrite("debug_blue_border_roi.png", roi_result)
print("\n结果: debug_blue_border_result.png, debug_blue_border_roi.png")
