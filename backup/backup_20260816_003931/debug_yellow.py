"""
调试：锁定游戏窗口，截取小地图，识别黄色光点
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

if not hwnd:
    print("未找到游戏窗口！")
    exit(1)

# 2. 获取窗口位置
rect = ctypes.create_string_buffer(16)
user32.GetWindowRect(hwnd, rect)
left, top, right, bottom = struct.unpack("llll", rect.raw)
w = right - left
h = bottom - top
print(f"窗口位置: left={left} top={top} w={w} h={h}")

# 3. 截取游戏窗口
sct = mss.mss()
region = {"left": left, "top": top, "width": w, "height": h}
frame = np.array(sct.grab(region))[:, :, :3]
cv2.imwrite("debug_game_window.png", frame)
print(f"游戏窗口截图: {frame.shape[1]}x{frame.shape[0]}")

# 4. 小地图在窗口左上角，尝试多个偏移量找最佳
# 标题栏约30px，小地图有边框，中间是地图内容
best_minimap = None
best_count = 0
best_pos = None

for mm_top in range(28, 40, 2):
    for mm_left in range(3, 10, 2):
        for mm_w in range(110, 130, 5):
            for mm_h in range(150, 180, 5):
                if mm_top + mm_h > h or mm_left + mm_w > w:
                    continue
                minimap = frame[mm_top:mm_top + mm_h, mm_left:mm_left + mm_w]
                hsv = cv2.cvtColor(minimap, cv2.COLOR_BGR2HSV)
                # 宽范围黄色
                mask = cv2.inRange(hsv, np.array([10, 60, 100]), np.array([45, 255, 255]))
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
                cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                valid = [c for c in cnts if cv2.contourArea(c) >= 1]
                if len(valid) > best_count:
                    best_count = len(valid)
                    best_minimap = minimap.copy()
                    best_pos = (mm_left, mm_top, mm_w, mm_h)

print(f"\n最佳小地图位置: left={best_pos[0]} top={best_pos[1]} w={best_pos[2]} h={best_pos[3]}")
print(f"找到黄色点数量: {best_count}")

if best_minimap is not None:
    cv2.imwrite("debug_minimap.png", best_minimap)
    hsv = cv2.cvtColor(best_minimap, cv2.COLOR_BGR2HSV)

    # 详细测试黄色范围
    print("\n--- 黄色范围测试 ---")
    best_dot = None
    for hl in range(10, 28, 2):
        for hh in range(28, 50, 2):
            mask = cv2.inRange(hsv, np.array([hl, 60, 100]), np.array([hh, 255, 255]))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 50]
            if valid:
                largest = max(valid, key=cv2.contourArea)
                M = cv2.moments(largest)
                if M["m00"] > 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    area = cv2.contourArea(largest)
                    if best_dot is None or area > best_dot[2]:
                        best_dot = (cx, cy, area, hl, hh, len(valid))

    if best_dot:
        cx, cy, area, hl, hh, cnt = best_dot
        print(f"最优黄色范围: H[{hl},{hh}]")
        print(f"光点位置: ({cx},{cy}) area={area:.1f} 同范围点数={cnt}")

        # 画结果
        result = best_minimap.copy()
        cv2.circle(result, (cx, cy), 3, (0, 255, 255), -1)
        cv2.circle(result, (cx, cy), 6, (0, 0, 255), 2)
        # 放大显示
        result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                                interpolation=cv2.INTER_NEAREST)
        cv2.imwrite("debug_result.png", result_big)
        print("结果已保存: debug_result.png (放大4倍)")
    else:
        print("未找到黄色光点！")
