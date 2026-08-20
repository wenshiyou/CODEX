"""
人物模板匹配实时测试脚本
用法: python test_player_track.py
功能: 实时全屏截图，用模板匹配定位人物，在窗口中显示匹配结果
按键: q/ESC 退出
"""
import cv2
import numpy as np
import os
import sys

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.capture import ScreenCapture
from core.player_tracker import PlayerTracker


def main():
    print("=" * 50)
    print("  人物模板匹配实时测试")
    print("=" * 50)

    # 初始化追踪器
    tracker = PlayerTracker(templates_dir="data/templates", match_threshold=0.85)
    print(f"已加载模板: 左={tracker.left_count}, 右={tracker.right_count}")

    if not tracker.has_templates:
        print("错误: 没有找到模板图，请先在 data/templates/ 放入模板")
        return

    # 全屏截图
    capture = ScreenCapture(region=None)  # None=全屏
    print("截图模式: 全屏")
    print("按 q 或 ESC 退出")
    print()

    cv2.namedWindow("Player Tracking - 按q/ESC退出", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Player Tracking - 按q/ESC退出", 1280, 720)

    frame_count = 0
    last_fps_time = __import__('time').time()
    fps = 0

    while True:
        # 截图
        frame = capture.capture()
        if frame is None:
            print("截图失败")
            break

        frame_count += 1

        # 模板匹配
        result = tracker.track(frame)

        # 绘制结果
        display = frame.copy()

        if result:
            x1, y1, x2, y2 = result["bbox"]
            cx, cy = result["center"]
            conf = result["confidence"]
            direction = result["direction"]

            # 画匹配框
            cv2.rectangle(display, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
            # 画中心点
            cv2.circle(display, (int(cx), int(cy)), 5, (0, 0, 255), -1)

            # 信息文字
            info_text = f"POS:({cx:.0f},{cy:.0f}) DIR:{direction} CONF:{conf:.3f}"
            cv2.putText(display, info_text, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        else:
            cv2.putText(display, "NOT FOUND - 未匹配到人物", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # FPS
        now = __import__('time').time()
        if now - last_fps_time >= 1.0:
            fps = frame_count
            frame_count = 0
            last_fps_time = now
        cv2.putText(display, f"FPS:{fps}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        # 模板信息
        cv2.putText(display, f"Templates:L={tracker.left_count} R={tracker.right_count} thresh={tracker.match_threshold}",
                    (10, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        # 缩放显示
        h, w = display.shape[:2]
        scale = min(1280 / w, 720 / h)
        if scale < 1.0:
            display = cv2.resize(display, None, fx=scale, fy=scale)

        cv2.imshow("Player Tracking - 按q/ESC退出", display)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break

    cv2.destroyAllWindows()
    print("测试结束")


if __name__ == "__main__":
    main()
