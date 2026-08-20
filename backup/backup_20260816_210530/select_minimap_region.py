"""
小地图区域手动选择工具（独立运行）
运行后弹出游戏窗口截图，拖拽框选小地图区域，按 Enter 确认。
选择结果保存到 data/minimap_region.json，test_minimap_route.py 会自动读取。
"""
import ctypes
import struct
import mss
import numpy as np
import cv2
import os
import json

os.chdir(os.path.dirname(os.path.abspath(__file__)))

WINDOW_TITLE = "冒险岛怀旧服"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
REGION_FILE = os.path.join(DATA_DIR, "minimap_region.json")
os.makedirs(DATA_DIR, exist_ok=True)

user32 = ctypes.windll.user32


def main():
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        print("未找到游戏窗口:", WINDOW_TITLE)
        print("请先启动游戏")
        return

    # 获取窗口矩形
    rect = ctypes.create_string_buffer(16)
    user32.GetWindowRect(hwnd, rect)
    left, top, right, bottom = struct.unpack("llll", rect.raw)
    w, h = right - left, bottom - top
    print("游戏窗口: (%d,%d) %dx%d" % (left, top, w, h))

    # 截取整个窗口
    sct = mss.mss()
    frame = np.array(sct.grab({"left": left, "top": top, "width": w, "height": h}))[:, :, :3]
    print("截图尺寸:", frame.shape[1], "x", frame.shape[0])

    # 弹出选择窗口
    sel_win = "拖拽框选小地图 | Enter=确认 C=取消"
    cv2.namedWindow(sel_win, cv2.WINDOW_NORMAL)
    # 缩放到合适大小显示
    display_w = min(frame.shape[1], 1000)
    display_h = int(frame.shape[0] * display_w / frame.shape[1])
    cv2.resizeWindow(sel_win, display_w, display_h)

    print("\n请在窗口中拖拽框选小地图区域（包括标题栏）")
    print("按 Enter 确认，按 C 取消")

    roi = cv2.selectROI(sel_win, frame, fromCenter=False, showCrosshair=True)
    cv2.destroyAllWindows()

    x, y, rw, rh = roi
    if rw < 20 or rh < 20:
        print("取消或选择区域太小")
        return

    print("\n选中区域: 窗口内坐标 (%d,%d) %dx%d" % (x, y, rw, rh))

    # 保存
    pad = 2
    region = {
        "minimap": {
            "left": int(x), "top": int(y),
            "width": int(rw), "height": int(rh)
        },
        "map": {
            "left": int(x) + pad, "top": int(y) + pad,
            "width": int(rw) - pad * 2, "height": int(rh) - pad * 2
        }
    }
    with open(REGION_FILE, "w", encoding="utf-8") as f:
        json.dump(region, f, indent=2)

    print("已保存到:", REGION_FILE)
    print("map area: %dx%d" % (region["map"]["width"], region["map"]["height"]))

    # 验证截取
    map_r = region["map"]
    verify = frame[map_r["top"]:map_r["top"] + map_r["height"],
                   map_r["left"]:map_r["left"] + map_r["width"]]
    cv2.imwrite("debug_map_area.png", verify)
    print("验证截图已保存: debug_map_area.png")
    print("\n完成！现在可以运行 test_minimap_route.py")


if __name__ == "__main__":
    main()
