"""
实时调试：显示光点位置和轨迹，排查为什么没有线出来
"""
import ctypes
import struct
import mss
import numpy as np
import cv2
import time

user32 = ctypes.windll.user32
hwnd = user32.FindWindowW(None, "冒险岛怀旧服")
rect = ctypes.create_string_buffer(16)
user32.GetWindowRect(hwnd, rect)
left, top, right, bottom = struct.unpack("llll", rect.raw)
w, h = right - left, bottom - top

sct = mss.mss()

# 使用之前验证的地图区域参数
map_x, map_y, map_w, map_h = 11, 97, 184, 119

points = []
recording = False
last_pos = None

print("按P开始/停止录制，Q退出")
print(f"地图区域: ({map_x},{map_y}) {map_w}x{map_h}")

while True:
    frame = np.array(sct.grab({"left": left + map_x, "top": top + map_y,
                                "width": map_w, "height": map_h}))[:, :, :3]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([25, 120, 180]), np.array([35, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 30]

    pos = None
    if valid:
        largest = max(valid, key=cv2.contourArea)
        M = cv2.moments(largest)
        if M["m00"] > 0:
            pos = (int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"]))

    if recording and pos:
        points.append(pos)
        if last_pos and (pos[0] != last_pos[0] or pos[1] != last_pos[1]):
            print(f"  光点移动: {last_pos} -> {pos}")
        last_pos = pos

    display = frame.copy()
    if pos:
        cv2.circle(display, pos, 3, (0, 255, 255), -1)
        cv2.circle(display, pos, 6, (0, 0, 255), 2)

    if len(points) > 1:
        pts = np.array(points, np.int32).reshape((-1, 1, 2))
        cv2.polylines(display, [pts], False, (0, 0, 255), 1)

    # 放大2倍
    display = cv2.resize(display, (map_w * 2, map_h * 2), interpolation=cv2.INTER_NEAREST)

    cv2.putText(display, f"光点: {pos}", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    cv2.putText(display, f"轨迹点: {len(points)} 录制: {'是' if recording else '否'}", (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0) if recording else (0, 0, 255), 1)
    cv2.putText(display, "P=录制 Q=退出", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

    cv2.imshow("Debug", display)
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('p'):
        recording = not recording
        if recording:
            points = []
            print("开始录制...")
        else:
            print(f"停止录制，共 {len(points)} 个点")
            if len(points) >= 3:
                ys = [p[1] for p in points]
                print(f"  Y范围: {min(ys)}-{max(ys)} 差={max(ys)-min(ys)}")
                xs = [p[0] for p in points]
                print(f"  X范围: {min(xs)}-{max(xs)} 差={max(xs)-min(xs)}")

cv2.destroyAllWindows()
