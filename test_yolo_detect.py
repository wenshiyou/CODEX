"""
YOLO 怪物检测测试脚本
用法:
  1. 将训练好的 best.pt 放到 data/models/ 目录
  2. 运行: python test_yolo_detect.py
  3. 脚本会截取游戏画面，运行YOLO检测，显示结果

如果没有模型，脚本会提示并退出。
"""
import ctypes
import struct
import mss
import numpy as np
import cv2
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.detector import YoloDetector
from config.config_loader import Config

WINDOW_TITLE = "冒险岛怀旧服"
MODEL_PATH = "data/models/best.pt"


def find_game_window():
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        print(f"未找到游戏窗口: {WINDOW_TITLE}")
        return None
    return hwnd


def capture_window(hwnd):
    user32 = ctypes.windll.user32
    rect = ctypes.create_string_buffer(16)
    user32.GetWindowRect(hwnd, rect)
    left, top, right, bottom = struct.unpack("llll", rect.raw)
    w, h = right - left, bottom - top
    sct = mss.mss()
    frame = np.array(sct.grab({"left": left, "top": top, "width": w, "height": h}))[:, :, :3]
    return frame


def draw_detections(frame, detections):
    """在画面上绘制检测结果"""
    result = frame.copy()
    colors = {
        "player": (0, 255, 255),
        "monster": (0, 0, 255),
        "ladder": (255, 100, 0),
        "npc": (255, 255, 0),
        "portal": (0, 255, 0),
    }
    for det in detections:
        cls = det["class"]
        conf = det["confidence"]
        x1, y1, x2, y2 = [int(v) for v in det["bbox"]]
        color = colors.get(cls, (255, 255, 255))
        cv2.rectangle(result, (x1, y1), (x2, y2), color, 2)
        label = f"{cls} {conf:.2f}"
        cv2.putText(result, label, (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        cx, cy = det["center"]
        cv2.circle(result, (int(cx), int(cy)), 3, color, -1)
    return result


def main():
    print("=" * 60)
    print("YOLO 怪物检测测试")
    print("=" * 60)

    # 检查模型文件
    if not os.path.exists(MODEL_PATH):
        print(f"\n模型文件不存在: {MODEL_PATH}")
        print("请将训练好的 best.pt 放到 data/models/ 目录")
        print("\n如需采集训练数据，运行: python collect_training_data.py")
        return

    # 查找游戏窗口
    hwnd = find_game_window()
    if not hwnd:
        return

    print(f"游戏窗口: {hwnd}")

    # 加载配置
    cfg = Config()
    yolo_cfg = cfg.get("yolo", {})

    # 初始化检测器
    detector = YoloDetector(
        model_path=MODEL_PATH,
        confidence=yolo_cfg.get("confidence", 0.5),
        iou_threshold=yolo_cfg.get("iou_threshold", 0.45),
        device=yolo_cfg.get("device", "cpu"),
        class_names=yolo_cfg.get("class_names", {})
    )

    print("加载YOLO模型...")
    try:
        detector.load_model()
    except Exception as e:
        print(f"模型加载失败: {e}")
        return

    print("模型加载成功！")
    print("\n按 Q 退出，按 S 保存当前检测结果")

    win = "YOLO Detection | Q=quit S=save"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 800, 600)

    frame_count = 0
    while True:
        t0 = time.time()
        frame = capture_window(hwnd)

        # 运行检测
        detections = detector.detect(frame)
        result = draw_detections(frame, detections)

        # 统计
        monsters = [d for d in detections if d["class"] == "monster"]
        players = [d for d in detections if d["class"] == "player"]
        fps = 1.0 / (time.time() - t0) if time.time() > t0 else 0

        # HUD
        cv2.putText(result, f"FPS: {fps:.1f}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(result, f"Monsters: {len(monsters)}", (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.putText(result, f"Players: {len(players)}", (10, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        cv2.imshow(win, result)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key == ord('s'):
            path = f"yolo_detect_{frame_count}.png"
            cv2.imwrite(path, result)
            print(f"保存: {path} ({len(detections)} 个检测)")

        frame_count += 1

    cv2.destroyAllWindows()
    print("测试结束")


if __name__ == "__main__":
    main()
