"""
小地图路径录制脚本（正式版）
- 自动锁定"冒险岛怀旧服"游戏窗口
- 自动检测小地图和地图内容区域
- 识别黄色光点（自己角色），记录移动轨迹
- 绘制平台（绿线）和梯子（蓝线）
- 不同地图小地图大小不同，自动适应

快捷键:
  P - 开始/停止平台录制
  L - 开始/停止梯子录制
  C - 清除当前录制轨迹
  S - 保存平台和梯子数据
  R - 重新检测小地图区域
  +/- 调整黄色识别阈值
  Q/ESC - 退出
"""
import ctypes
import struct
import mss
import numpy as np
import cv2
import os
import json
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ============ 配置 ============
DISPLAY_SCALE = 5  # 显示放大倍数
WINDOW_TITLE = "冒险岛怀旧服"

# 黄色光点HSV范围（已调优）
YELLOW_H_LOW = 25
YELLOW_H_HIGH = 35
YELLOW_S_LOW = 120
YELLOW_V_LOW = 180

# 文件
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
PLATFORMS_FILE = os.path.join(DATA_DIR, "minimap_platforms.json")
LADDERS_FILE = os.path.join(DATA_DIR, "minimap_ladders.json")
REGION_FILE = os.path.join(DATA_DIR, "minimap_region.json")

# 颜色 (BGR)
COLOR_PLATFORM = (0, 255, 0)
COLOR_LADDER = (255, 100, 0)
COLOR_RECORDING = (0, 0, 255)
COLOR_PLAYER = (0, 255, 255)
COLOR_TEXT = (255, 255, 255)


class MinimapRouteRecorder:
    def __init__(self):
        self.sct = mss.mss()
        self.user32 = ctypes.windll.user32

        # 游戏窗口和小地图区域
        self.hwnd = None
        self.window_rect = None
        self.minimap_rect = None  # 完整小地图（含标题）
        self.map_area_rect = None  # 地图内容区域（不含标题）

        # 录制状态
        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []

        # 已保存
        self.platforms = self._load(PLATFORMS_FILE, "platforms")
        self.ladders = self._load(LADDERS_FILE, "ladders")

        # 黄色阈值
        self.h_low = YELLOW_H_LOW
        self.h_high = YELLOW_H_HIGH
        self.s_low = YELLOW_S_LOW
        self.v_low = YELLOW_V_LOW

        # 初始化
        self._init_window()
        self._detect_minimap()

        print(f"游戏窗口: {self.window_rect}")
        print(f"小地图: {self.minimap_rect}")
        print(f"地图内容区: {self.map_area_rect}")
        print(f"已加载: 平台{len(self.platforms)}个, 梯子{len(self.ladders)}个")
        print()
        print("快捷键: P=平台 L=梯子 C=清除 S=保存 R=重检 +/-=调阈值 Q=退出")
        print()

    def _init_window(self):
        """查找并锁定游戏窗口"""
        self.hwnd = self.user32.FindWindowW(None, WINDOW_TITLE)
        if not self.hwnd:
            raise RuntimeError(f"未找到游戏窗口: {WINDOW_TITLE}")
        self._update_window_rect()

    def _update_window_rect(self):
        rect = ctypes.create_string_buffer(16)
        self.user32.GetWindowRect(self.hwnd, rect)
        left, top, right, bottom = struct.unpack("llll", rect.raw)
        self.window_rect = {"left": left, "top": top,
                            "width": right - left, "height": bottom - top}

    def _detect_minimap(self):
        """自动检测小地图和地图内容区域（扫描线法，适应不同大小）"""
        self._update_window_rect()
        frame = self._capture_window()

        roi_top = 15
        roi = frame[roi_top:roi_top + 230, 0:220].copy()
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        # 1. 灰白色检测找外层大框
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        border_mask = cv2.inRange(hsv, np.array([0, 0, 100]), np.array([180, 50, 255]))
        border_mask = cv2.morphologyEx(border_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(border_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        outer = None
        max_a = 0
        for c in contours:
            x, y, cw, ch = cv2.boundingRect(c)
            a = cv2.contourArea(c)
            if cw > 80 and ch > 100 and a > max_a:
                max_a = a
                outer = (x, y, cw, ch)

        ox, oy, ow, oh = outer if outer else (5, 0, 200, 220)
        self.minimap_rect = {'left': ox, 'top': roi_top + oy, 'width': ow, 'height': oh}

        # 2. 扫描线法找内层地图边框
        inner = gray[oy:oy + oh, ox:ox + ow]

        def find_hborder(img, sy, ey, step, thresh=130, ratio=0.75):
            for y in range(sy, ey, step):
                if 0 <= y < img.shape[0]:
                    if np.sum(img[y, :] > thresh) > ow * ratio:
                        return y
            return None

        def find_vborder(img, sx, ex, step, y_range, thresh=130, ratio=0.45):
            y1, y2 = y_range
            for x in range(sx, ex, step):
                if 0 <= x < img.shape[1]:
                    if np.sum(img[y1:y2, x] > thresh) > (y2 - y1) * ratio:
                        return x
            return None

        top_y = find_hborder(inner, int(oh * 0.35), int(oh * 0.6), 1)
        bottom_y = find_hborder(inner, oh - 3, int(oh * 0.5), -1)

        if top_y and bottom_y and bottom_y > top_y:
            left_x = find_vborder(inner, 3, ow // 2, 1, (top_y, bottom_y))
            right_x = find_vborder(inner, ow - 4, ow // 2, -1, (top_y, bottom_y))
        else:
            top_y = top_y or int(oh * 0.38)
            bottom_y = bottom_y or oh - 3
            left_x = 3
            right_x = ow - 3

        # 3. 地图内容区域 = 边框内部
        pad = 2
        self.map_area_rect = {
            'left': ox + left_x + pad,
            'top': roi_top + oy + top_y + pad,
            'width': right_x - left_x - pad * 2,
            'height': bottom_y - top_y - pad * 2
        }

        print(f'外层大框: ({ox},{oy}) {ow}x{oh}')
        print(f'地图边框: top={top_y} bottom={bottom_y} left={left_x} right={right_x}')
        print(f'地图内容区: {self.map_area_rect["width"]}x{self.map_area_rect["height"]}')

        self._save_region()


    def _save_region(self):
        config = {
            "window_title": WINDOW_TITLE,
            "minimap_rect": self.minimap_rect,
            "map_area_rect": self.map_area_rect
        }
        with open(REGION_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    def _load(self, path, key):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f).get(key, [])
            except Exception:
                return []
        return []

    def _save(self):
        with open(PLATFORMS_FILE, "w", encoding="utf-8") as f:
            json.dump({"platforms": self.platforms, "count": len(self.platforms)}, f, indent=2)
        with open(LADDERS_FILE, "w", encoding="utf-8") as f:
            json.dump({"ladders": self.ladders, "count": len(self.ladders)}, f, indent=2)
        print(f"已保存: 平台{len(self.platforms)}个, 梯子{len(self.ladders)}个")

    def _capture_window(self):
        """截取整个游戏窗口"""
        r = self.window_rect
        frame = np.array(self.sct.grab(r))
        return frame[:, :, :3]

    def _capture_map_area(self):
        """只截取地图内容区域"""
        r = self.map_area_rect
        region = {
            "left": self.window_rect["left"] + r["left"],
            "top": self.window_rect["top"] + r["top"],
            "width": r["width"],
            "height": r["height"]
        }
        frame = np.array(self.sct.grab(region))
        return frame[:, :, :3]

    def find_player_dot(self, map_area):
        """在地图内容区域找到黄色光点"""
        hsv = cv2.cvtColor(map_area, cv2.COLOR_BGR2HSV)
        lower = np.array([self.h_low, self.s_low, self.v_low])
        upper = np.array([self.h_high, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)

        kernel = np.ones((2, 2), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, mask

        # 找面积在合理范围内的最大轮廓（角色光点约3-15像素）
        valid = [c for c in contours if 1 <= cv2.contourArea(c) <= 30]
        if not valid:
            return None, mask

        largest = max(valid, key=cv2.contourArea)
        M = cv2.moments(largest)
        if M["m00"] == 0:
            return None, mask
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        return (cx, cy), mask

    def extract_platform(self, points):
        """从轨迹点提取平台（水平线聚类）"""
        if len(points) < 3:
            return []
        ys = sorted(set(int(p[1] // 3) * 3 for p in points))
        clusters = []
        current = [ys[0]]
        for y in ys[1:]:
            if y - current[-1] <= 6:
                current.append(y)
            else:
                clusters.append(current)
                current = [y]
        clusters.append(current)

        platforms = []
        for cluster in clusters:
            cp = [p for p in points if int(p[1] // 3) * 3 in cluster]
            if len(cp) < 3:
                continue
            xs = [p[0] for p in cp]
            y_base = sum(p[1] for p in cp) / len(cp)
            platforms.append({
                "id": len(self.platforms) + len(platforms),
                "x_min": float(min(xs)),
                "x_max": float(max(xs)),
                "y_base": float(y_base)
            })
        return platforms

    def extract_ladder(self, points):
        """从轨迹点提取梯子（垂直线）"""
        if len(points) < 3:
            return []
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x_median = sorted(xs)[len(xs) // 2]
        return [{
            "id": len(self.ladders),
            "x": float(x_median),
            "y_top": float(min(ys)),
            "y_bottom": float(max(ys))
        }]

    def draw(self, map_area, player_pos):
        display = map_area.copy()
        h, w = display.shape[:2]

        # 已保存的平台
        for p in self.platforms:
            x1 = int(max(0, min(p["x_min"], w - 1)))
            x2 = int(max(0, min(p["x_max"], w - 1)))
            y = int(max(0, min(p["y_base"], h - 1)))
            cv2.line(display, (x1, y), (x2, y), COLOR_PLATFORM, 1)
            cv2.putText(display, f"P{p['id']}", (x1, max(0, y - 2)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, COLOR_PLATFORM, 1)

        # 已保存的梯子
        for l in self.ladders:
            x = int(max(0, min(l["x"], w - 1)))
            y1 = int(max(0, min(l["y_top"], h - 1)))
            y2 = int(max(0, min(l["y_bottom"], h - 1)))
            cv2.line(display, (x, y1), (x, y2), COLOR_LADDER, 1)
            cv2.putText(display, f"L{l['id']}", (min(w - 10, x + 2), (y1 + y2) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, COLOR_LADDER, 1)

        # 录制轨迹
        if self.recording_platform and len(self.platform_points) > 1:
            pts = np.array(self.platform_points, np.int32).reshape((-1, 1, 2))
            cv2.polylines(display, [pts], False, COLOR_RECORDING, 1)
        if self.recording_ladder and len(self.ladder_points) > 1:
            pts = np.array(self.ladder_points, np.int32).reshape((-1, 1, 2))
            cv2.polylines(display, [pts], False, COLOR_RECORDING, 1)

        # 人物光点
        if player_pos:
            cx, cy = player_pos
            cv2.circle(display, (cx, cy), 2, COLOR_PLAYER, -1)
            cv2.circle(display, (cx, cy), 4, (0, 0, 255), 1)

        # 放大
        display = cv2.resize(display, (w * DISPLAY_SCALE, h * DISPLAY_SCALE),
                             interpolation=cv2.INTER_NEAREST)

        # HUD
        y = 18
        if self.recording_platform:
            cv2.putText(display, ">> 平台录制中 (P停止) <<", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        elif self.recording_ladder:
            cv2.putText(display, ">> 梯子录制中 (L停止) <<", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        else:
            cv2.putText(display, "待机 (P平台 L梯子 C清除 S保存 R重检)", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        y += 18

        if player_pos:
            cv2.putText(display, f"光点: ({player_pos[0]},{player_pos[1]})", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_PLAYER, 1)
        else:
            cv2.putText(display, "光点: 未检测到 (+/-调阈值)", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        y += 16

        cv2.putText(display,
                    f"平台:{len(self.platforms)} 梯子:{len(self.ladders)} "
                    f"轨迹:{len(self.platform_points) + len(self.ladder_points)} "
                    f"H:[{self.h_low},{self.h_high}] S>={self.s_low} V>={self.v_low} "
                    f"地图:{self.map_area_rect['width']}x{self.map_area_rect['height']}",
                    (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_TEXT, 1)

        return display

    def run(self):
        window_name = "Minimap Route Recorder | P平台 L梯子 C清除 S保存 R重检 Q退出"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        while True:
            try:
                map_area = self._capture_map_area()
            except Exception:
                time.sleep(0.1)
                continue

            player_pos, _ = self.find_player_dot(map_area)

            if self.recording_platform and player_pos:
                self.platform_points.append(player_pos)
            if self.recording_ladder and player_pos:
                self.ladder_points.append(player_pos)

            display = self.draw(map_area, player_pos)
            cv2.imshow(window_name, display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                break
            elif key == ord('r'):
                print("重新检测小地图区域...")
                self._detect_minimap()
                print(f"新地图区域: {self.map_area_rect}")
            elif key == ord('p'):
                if self.recording_ladder:
                    print("先停止梯子录制")
                elif self.recording_platform:
                    new_p = self.extract_platform(self.platform_points)
                    if new_p:
                        self.platforms.extend(new_p)
                        print(f"平台录制结束，提取 {len(new_p)} 个平台")
                    else:
                        print("平台录制结束，未提取到有效平台")
                    self.platform_points = []
                    self.recording_platform = False
                else:
                    self.recording_platform = True
                    self.platform_points = []
                    print("平台录制开始，在平台上走动...")
            elif key == ord('l'):
                if self.recording_platform:
                    print("先停止平台录制")
                elif self.recording_ladder:
                    new_l = self.extract_ladder(self.ladder_points)
                    if new_l:
                        self.ladders.extend(new_l)
                        print(f"梯子录制结束，提取 {len(new_l)} 个梯子")
                    else:
                        print("梯子录制结束，未提取到有效梯子")
                    self.ladder_points = []
                    self.recording_ladder = False
                else:
                    self.recording_ladder = True
                    self.ladder_points = []
                    print("梯子录制开始，爬一遍梯子...")
            elif key == ord('c'):
                self.platform_points = []
                self.ladder_points = []
                print("已清除轨迹")
            elif key == ord('s'):
                self._save()
            elif key in (ord('+'), ord('=')):
                self.h_high = min(50, self.h_high + 1)
                print(f"黄色H上限: {self.h_high}")
            elif key == ord('-'):
                self.h_low = max(5, self.h_low - 1)
                print(f"黄色H下限: {self.h_low}")

        cv2.destroyAllWindows()
        print(f"\n最终: 平台{len(self.platforms)}个, 梯子{len(self.ladders)}个")


if __name__ == "__main__":
    recorder = MinimapRouteRecorder()
    recorder.run()
