"""
调试v3：更严格的黄色范围，只找小光点（角色光点）
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

# 小地图完整区域
mm_left, mm_top, mm_w, mm_h = 9, 34, 130, 180
minimap_full = frame[mm_top:mm_top + mm_h, mm_left:mm_left + mm_w].copy()

# 地图内容区域（排除顶部标题）
map_top = 70
map_area = minimap_full[map_top:, :].copy()
print(f"地图区域: {map_area.shape[1]}x{map_area.shape[0]}")

hsv = cv2.cvtColor(map_area, cv2.COLOR_BGR2HSV)

# 更严格的黄色范围测试，只找小光点
print("\n--- 严格黄色范围（小光点 area 1-8）---")
best = None
for hl in range(15, 28):
    for hh in range(25, 40):
        for sl in [150, 180, 200]:
            for vl in [180, 200, 220]:
                mask = cv2.inRange(hsv, np.array([hl, sl, vl]), np.array([hh, 255, 255]))
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
                cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                small = [c for c in cnts if 1 <= cv2.contourArea(c) <= 8]
                if small:
                    largest = max(small, key=cv2.contourArea)
                    M = cv2.moments(largest)
                    if M["m00"] > 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                        area = cv2.contourArea(largest)
                        if best is None or (len(small) == 1 and area > 2):
                            best = (cx, cy, area, hl, hh, sl, vl, len(small))
                            print(f"  H[{hl},{hh}] S>={sl} V>={vl}: {len(small)}个小光点, 最大=({cx},{cy}) area={area:.1f}")

if best:
    cx, cy, area, hl, hh, sl, vl, cnt = best
    print(f"\n最优: H[{hl},{hh}] S>={sl} V>={vl}")
    print(f"光点: ({cx},{cy}) area={area:.1f} 同范围小光点数={cnt}")

    mask = cv2.inRange(hsv, np.array([hl, sl, vl]), np.array([hh, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    result = map_area.copy()
    for i, c in enumerate(cnts):
        a = cv2.contourArea(c)
        if 1 <= a <= 8:
            M = cv2.moments(c)
            if M["m00"] > 0:
                px = int(M["m10"] / M["m00"])
                py = int(M["m01"] / M["m00"])
                cv2.circle(result, (px, py), 2, (0, 255, 255), -1)
                cv2.circle(result, (px, py), 5, (0, 0, 255), 1)
                print(f"  光点{i}: ({px},{py}) area={a:.1f}")

    result_big = cv2.resize(result, (result.shape[1] * 5, result.shape[0] * 5),
                            interpolation=cv2.INTER_NEAREST)
    cv2.imwrite("debug_result3.png", result_big)
    print("结果: debug_result3.png (放大5倍)")
else:
    print("未找到小光点！")
    # 保存HSV各通道看看
    cv2.imwrite("debug_h.png", hsv[:,:,0])
    cv2.imwrite("debug_s.png", hsv[:,:,1])
    cv2.imwrite("debug_v.png", hsv[:,:,2])
    print("已保存H/S/V通道图")
