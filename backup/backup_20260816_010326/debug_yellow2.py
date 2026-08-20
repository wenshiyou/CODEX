"""
调试v2：锁定游戏窗口，自动检测地图内容区域，识别黄色光点
"""
import ctypes
import struct
import mss
import numpy as np
import cv2
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 1. 查找游戏窗口
user32 = ctypes.windll.user32
hwnd = user32.FindWindowW(None, "冒险岛怀旧服")
print(f"窗口句柄: {hwnd}")
rect = ctypes.create_string_buffer(16)
user32.GetWindowRect(hwnd, rect)
left, top, right, bottom = struct.unpack("llll", rect.raw)
w, h = right - left, bottom - top
print(f"窗口: ({left},{top}) {w}x{h}")

# 2. 截取游戏窗口
sct = mss.mss()
frame = np.array(sct.grab({"left": left, "top": top, "width": w, "height": h}))[:, :, :3]

# 3. 小地图完整区域（窗口内左上角）
mm_left, mm_top, mm_w, mm_h = 9, 34, 130, 180
minimap_full = frame[mm_top:mm_top + mm_h, mm_left:mm_left + mm_w].copy()
cv2.imwrite("debug_minimap_full.png", minimap_full)
print(f"完整小地图: {minimap_full.shape[1]}x{minimap_full.shape[0]}")

# 4. 自动检测地图内容区域（排除顶部标题栏）
# 方法：找水平方向上像素变化最大的行作为地图顶部边界
gray = cv2.cvtColor(minimap_full, cv2.COLOR_BGR2GRAY)
row_diff = np.diff(gray.mean(axis=1))
# 找前60行内变化最大的位置（标题栏和地图的分界线）
map_top = int(np.argmax(np.abs(row_diff[:70]))) + 2
print(f"检测到地图内容顶部: y={map_top}")

# 地图内容区域
map_area = minimap_full[map_top:, :].copy()
cv2.imwrite("debug_map_area.png", map_area)
print(f"地图内容区域: {map_area.shape[1]}x{map_area.shape[0]}")

# 5. 在地图内容区域识别黄色光点
hsv = cv2.cvtColor(map_area, cv2.COLOR_BGR2HSV)

print("\n--- 黄色范围测试（地图区域内）---")
best_dot = None
all_dots = []

for hl in range(10, 30, 2):
    for hh in range(28, 50, 2):
        mask = cv2.inRange(hsv, np.array([hl, 80, 120]), np.array([hh, 255, 255]))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 30]
        for c in valid:
            M = cv2.moments(c)
            if M["m00"] > 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                area = cv2.contourArea(c)
                all_dots.append((cx, cy, area, hl, hh))
                if best_dot is None or area > best_dot[2]:
                    best_dot = (cx, cy, area, hl, hh)

print(f"找到候选黄色点: {len(all_dots)} 个")
if best_dot:
    cx, cy, area, hl, hh = best_dot
    print(f"最大黄点: ({cx},{cy}) area={area:.1f} H范围[{hl},{hh}]")

    # 用最优范围画所有黄点
    mask = cv2.inRange(hsv, np.array([hl, 80, 120]), np.array([hh, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    result = map_area.copy()
    for i, c in enumerate(cnts):
        if 1 <= cv2.contourArea(c) <= 30:
            M = cv2.moments(c)
            if M["m00"] > 0:
                px = int(M["m10"] / M["m00"])
                py = int(M["m01"] / M["m00"])
                cv2.circle(result, (px, py), 3, (0, 255, 255), -1)
                cv2.circle(result, (px, py), 6, (0, 0, 255), 2)
                cv2.putText(result, str(i), (px + 8, py),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
                print(f"  黄点{i}: ({px},{py}) area={cv2.contourArea(c):.1f}")

    # 放大4倍
    result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                            interpolation=cv2.INTER_NEAREST)
    cv2.imwrite("debug_result2.png", result_big)
    print("\n结果已保存: debug_result2.png")
else:
    print("未找到黄色光点！")
