"""
人物模板匹配实时测试
全屏截图 -> 匹配"挑"字模板 -> 画框显示坐标和匹配度
按 q 或 ESC 退出
"""
import cv2
import numpy as np
import mss
import time
import os

# 模板路径
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "data", "templates", "player_right_0.png")
threshold = 0.85  # 背景透明，阈值设0.85

def main():
    threshold = 0.85  # 背景透明，阈值设0.85

    # 加载模板
    template = cv2.imread(TEMPLATE_PATH, cv2.IMREAD_COLOR)
    if template is None:
        print(f"错误: 找不到模板 {TEMPLATE_PATH}")
        return
    th, tw = template.shape[:2]
    print(f"模板加载成功: {tw}x{th}")
    print(f"匹配阈值: {threshold}")
    print("全屏截图中... 按 q 或 ESC 退出")
    print("按 + 提高阈值, 按 - 降低阈值")
    print()

    sct = mss.mss()
    monitor = sct.monitors[1]  # 主屏

    cv2.namedWindow("Player Track - 挑字匹配 | q/ESC退出", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Player Track - 挑字匹配 | q/ESC退出", 1280, 720)

    frame_count = 0
    fps_time = time.time()
    fps = 0
    found_count = 0
    total_count = 0

    while True:
        # 全屏截图
        frame = np.array(sct.grab(monitor))
        frame = frame[:, :, :3]  # BGRA -> BGR
        frame_count += 1
        total_count += 1

        # 模板匹配
        result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        display = frame.copy()

        if max_val >= threshold:
            found_count += 1
            x1, y1 = max_loc
            x2, y2 = x1 + tw, y1 + th
            cx, cy = x1 + tw // 2, y1 + th // 2

            # 画匹配框（绿色）
            cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 2)
            # 画中心点（红色）
            cv2.circle(display, (cx, cy), 6, (0, 0, 255), -1)
            cv2.circle(display, (cx, cy), 10, (0, 255, 255), 2)

            # 信息
            info = f"FOUND  pos=({cx},{cy})  conf={max_val:.3f}"
            cv2.putText(display, info, (10, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            color = (0, 255, 0)
        else:
            info = f"NOT FOUND  best_conf={max_val:.3f} (threshold={threshold})"
            cv2.putText(display, info, (10, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            color = (0, 0, 255)

        # FPS
        if time.time() - fps_time >= 1.0:
            fps = frame_count
            frame_count = 0
            fps_time = time.time()

        # 统计
        hit_rate = found_count / total_count * 100 if total_count > 0 else 0
        cv2.putText(display, f"FPS:{fps}  命中率:{hit_rate:.0f}%({found_count}/{total_count})",
                    (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(display, f"template:{tw}x{th}  threshold:{threshold}",
                    (10, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        # 缩放显示
        h, w = display.shape[:2]
        scale = min(1280 / w, 720 / h)
        if scale < 1.0:
            display = cv2.resize(display, None, fx=scale, fy=scale)

        cv2.imshow("Player Track - 挑字匹配 | q/ESC退出", display)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        # 按+/-调阈值
        elif key == ord('+') or key == ord('='):
            threshold = min(0.99, threshold + 0.02)
            print(f"阈值调整为: {threshold:.2f}")
        elif key == ord('-'):
            threshold = max(0.5, threshold - 0.02)
            print(f"阈值调整为: {threshold:.2f}")

    cv2.destroyAllWindows()
    print(f"\n测试结束: 总帧{total_count}, 命中{found_count}, 命中率{hit_rate:.1f}%")

if __name__ == "__main__":
    main()
