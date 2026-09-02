"""
调试v4：分析用户提供的小地图图中黄色光点的精确颜色
"""
import cv2
import numpy as np
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 读取用户提供的地图内容图
img = cv2.imread("user_mm2.png")
if img is None:
    print("无法读取 user_mm2.png")
    exit(1)

print(f"用户地图图: {img.shape[1]}x{img.shape[0]}")

hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

# 找所有黄色像素
print("\n--- 黄色像素分析 ---")
for hl in range(15, 35, 2):
    for hh in range(25, 45, 2):
        mask = cv2.inRange(hsv, np.array([hl, 100, 150]), np.array([hh, 255, 255]))
        yellow_pixels = cv2.countNonZero(mask)
        if yellow_pixels > 0:
            # 找轮廓
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            small = [c for c in cnts if 1 <= cv2.contourArea(c) <= 15]
            if small:
                largest = max(small, key=cv2.contourArea)
                M = cv2.moments(largest)
                if M["m00"] > 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    area = cv2.contourArea(largest)
                    print(f"  H[{hl},{hh}]: 黄色像素{yellow_pixels}个, 小光点{len(small)}个, 最大=({cx},{cy}) area={area:.1f}")

# 用严格范围找
print("\n--- 严格范围 ---")
best = None
for hl in range(20, 32):
    for hh in range(28, 42):
        for sl in [150, 180, 200, 220]:
            for vl in [180, 200, 220, 240]:
                mask = cv2.inRange(hsv, np.array([hl, sl, vl]), np.array([hh, 255, 255]))
                cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                small = [c for c in cnts if 1 <= cv2.contourArea(c) <= 10]
                if len(small) == 1:
                    c = small[0]
                    M = cv2.moments(c)
                    if M["m00"] > 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                        area = cv2.contourArea(c)
                        if best is None or area > best[2]:
                            best = (cx, cy, area, hl, hh, sl, vl)
                            print(f"  唯一光点: H[{hl},{hh}] S>={sl} V>={vl} pos=({cx},{cy}) area={area:.1f}")

if best:
    cx, cy, area, hl, hh, sl, vl = best
    print(f"\n最优: H[{hl},{hh}] S>={sl} V>={vl} pos=({cx},{cy}) area={area:.1f}")
    mask = cv2.inRange(hsv, np.array([hl, sl, vl]), np.array([hh, 255, 255]))
    result = img.copy()
    cv2.circle(result, (cx, cy), 3, (0, 255, 255), -1)
    cv2.circle(result, (cx, cy), 8, (0, 0, 255), 2)
    result_big = cv2.resize(result, (result.shape[1] * 4, result.shape[0] * 4),
                            interpolation=cv2.INTER_NEAREST)
    cv2.imwrite("debug_user_result.png", result_big)
    print("结果: debug_user_result.png")
else:
    print("未找到唯一光点")
