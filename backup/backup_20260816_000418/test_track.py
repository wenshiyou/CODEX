"""
人物模板匹配实时测试
全屏截图 -> 模板匹配 -> 画框显示人物位置
按 q 或 ESC 退出
"""
import cv2
import numpy as np
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.capture import ScreenCapture


def main():
    # 加载模板
    template_path = "data/templates/player_right_0.png"
    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        print(f"模板加载失败: {template_path}")
        return

    th, tw = template.shape[:2]
    print(f"模板尺寸: {tw}x{th}")
    print("正在全屏截图匹配，按 q 或 ESC 退出...")

    # 截图器（全屏）
    capture = ScreenCapture(region=None)

    cv2.namedWindow("Player Track - q/ESC退出", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Player Track - q/ESC退出", 1280, 720)

    threshold = 0.85  # 匹配阈值
    frame_count = 0
    fps_time = time.time()
    fps = 0

    while True:
        frame = capture.capture()
        if frame is None:
            print("截图失败")
            break

        frame_count += 1

        # 模板匹配
        result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        display = frame.copy()

        if max_val >= threshold:
            x1, y1 = max_loc
            x2, y2 = x1 + tw, y1 + th
            cx, cy = x1 + tw / 2, y1 + th / 2

            # 画匹配框（绿色）
            cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 2)
            # 画人物中心点（红色）
            cv2.circle(display, (int(cx), int(cy)), 8, (0, 0, 255), -1)
            cv2.circle(display, (int(cx), int(cy)), 15, (0, 0, 255), 2)

            info = f"FOUND  pos=({cx:.0f},{cy:.0f})  conf={max_val:.3f}"
            cv2.putText(display, info, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        else:
            info = f"NOT FOUND  best_conf={max_val:.3f}  threshold={threshold}"
            cv2.putText(display, info, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        # FPS
        if time.time() - fps_time >= 1.0:
            fps = frame_count
            frame_count = 0
            fps_time = time.time()
        cv2.putText(display, f"FPS:{fps}", (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(display, f"template:{tw}x{th}  thresh:{threshold}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        # 缩放显示
        h, w = display.shape[:2]
        scale = min(1280 / w, 720 / h)
        if scale < 1.0:
            display = cv2.resize(display, None, fx=scale, fy=scale)

        cv2.imshow("Player Track - q/ESC退出", display)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break

    cv2.destroyAllWindows()
    print("测试结束")


if __name__ == "__main__":
    main()
