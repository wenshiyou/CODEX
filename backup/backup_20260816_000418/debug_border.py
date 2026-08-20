"""
调试v5：自动检测小地图边框，确定地图内容区域
"""
import ctypes, struct, mss, numpy as np, cv2, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

user32 = ctypes.windll.user32
hwnd = user32.FindWindowW(None, "冒险岛怀旧服")
rect = ctypes.create_string_buffer(16)
user32.GetWindowRect(hwnd, rect)
left, top, right, bottom = struct.unpack("llll", rect.raw)
w, h = right - left, bottom - top
print(f"窗口: ({left},{top}) {w}x{h}")

sct = mss.mss()
frame = np.array(sct.grab({"left": left, "top": top, "width": w, "height": h}))[:, :, :3]

# 截取左上角较大区域（包含完整小地图）
roi = frame[20:220, 0:200].copy()
cv2.imwrite("debug_roi.png", roi)
print(f"ROI: {roi.shape[1]}x{roi.shape[0]}")

# 方法1：用Canny边缘检测找矩形边框
gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
edges = cv2.Canny(gray, 50, 150)
cv2.imwrite("debug_edges.png", edges)

# 找水平线和垂直线
horizontal = cv2.morphologyEx(edges, cv2.MORPH_OPEN,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (30, 1)))
vertical = cv2.morphologyEx(edges, cv2.MORPH_OPEN,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (1, 30)))

# 找最长的水平线（地图上下边框）
h_lines = cv2.HoughLinesP(horizontal, 1, np.pi / 180, threshold=30,
                          minLineLength=50, maxLineGap=5)
v_lines = cv2.HoughLinesP(vertical, 1, np.pi / 180, threshold=30,
                          minLineLength=50, maxLineGap=5)

print(f"\n水平线: {len(h_lines) if h_lines is not None else 0}")
print(f"垂直线: {len(v_lines) if v_lines is not None else 0}")

# 方法2：直接分析像素列/行的变化，找边框
# 边框通常是亮色（白色/灰色），地图内容是深色背景
col_brightness = gray.mean(axis=0)
row_brightness = gray.mean(axis=1)

# 找亮度突变的位置（边框）
col_diff = np.abs(np.diff(col_brightness))
row_diff = np.abs(np.diff(row_brightness))

# 打印前100列的亮度，找左右边框
print("\n--- 列亮度（前60列）---")
for i in range(0, 60, 5):
    print(f"  col{i}: {col_brightness[i]:.1f}", end="")
print()

print("\n--- 行亮度（前120行）---")
for i in range(0, 120, 10):
    print(f"  row{i}: {row_brightness[i]:.1f}", end="")
print()

# 方法3：用颜色阈值找灰色边框
hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
# 灰色/白色边框：低饱和度，中高亮度
border_mask = cv2.inRange(hsv, np.array([0, 0, 100]), np.array([180, 50, 255]))
cv2.imwrite("debug_border_mask.png", border_mask)

# 找边框的轮廓
contours, _ = cv2.findContours(border_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
rects = []
for c in contours:
    x, y, cw, ch = cv2.boundingRect(c)
    if cw > 50 and ch > 50:  # 大矩形
        rects.append((x, y, cw, ch))
        print(f"\n大矩形: ({x},{y}) {cw}x{ch}")

# 在ROI上画出检测到的矩形
result = roi.copy()
for (x, y, cw, ch) in rects:
    cv2.rectangle(result, (x, y), (x + cw, y + ch), (0, 0, 255), 2)

# 也画Hough线
if h_lines is not None:
    for line in h_lines[:10]:
        x1, y1, x2, y2 = line[0]
        cv2.line(result, (x1, y1), (x2, y2), (0, 255, 0), 1)
if v_lines is not None:
    for line in v_lines[:10]:
        x1, y1, x2, y2 = line[0]
        cv2.line(result, (x1, y1), (x2, y2), (255, 0, 0), 1)

cv2.imwrite("debug_border_detect.png", result)
print("\n结果保存: debug_border_detect.png")
