"""
小地图路径录制脚本（全局热键版）
- 自动锁定游戏窗口 + 扫描线法检测地图边框
- ROI光点跟踪（快速响应）
- 全局热键：F9平台 F10梯子 F11清除 F12保存（不用切窗口）
- 平台/梯子录制
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

DISPLAY_SCALE = 2
WINDOW_TITLE = "冒险岛怀旧服"
YELLOW_H_LOW = 25
YELLOW_H_HIGH = 35
YELLOW_S_LOW = 120
YELLOW_V_LOW = 180

# 全局热键虚拟键码
VK_F9 = 0x78
VK_F10 = 0x79
VK_F11 = 0x7A
VK_F12 = 0x7B

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
PLATFORMS_FILE = os.path.join(DATA_DIR, "minimap_platforms.json")
LADDERS_FILE = os.path.join(DATA_DIR, "minimap_ladders.json")
REGION_FILE = os.path.join(DATA_DIR, "minimap_region.json")

COLOR_PLATFORM = (0, 255, 0)
COLOR_LADDER = (255, 100, 0)
COLOR_RECORDING = (0, 0, 255)
COLOR_PLAYER = (0, 255, 255)

user32 = ctypes.windll.user32


def key_pressed(vk):
    """检测全局按键是否被按下（边沿触发）"""
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class MinimapRouteRecorder:
    def __init__(self):
        self.sct = mss.mss()
        self.hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if not self.hwnd:
            raise RuntimeError(f"未找到窗口: {WINDOW_TITLE}")
        self._update_window_rect()
        self._detect_minimap()

        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []
        self.platforms = self._load(PLATFORMS_FILE, "platforms")
        self.ladders = self._load(LADDERS_FILE, "ladders")
        self.last_player_pos = None
        self.frame_count = 0

        # 按键状态（用于边沿检测）
        self.f9_was_pressed = False
        self.f10_was_pressed = False
        self.f11_was_pressed = False
        self.f12_was_pressed = False

        print(f"地图区域: {self.map_area_rect['width']}x{self.map_area_rect['height']}")
        print(f"已加载: 平台{len(self.platforms)}个, 梯子{len(self.ladders)}个")
        print("全局热键: F9=平台 F10=梯子 F11=清除 F12=保存")
        print("窗口热键: R=重检 Q=退出\n")

    def _update_window_rect(self):
        rect = ctypes.create_string_buffer(16)
        user32.GetWindowRect(self.hwnd, rect)
        l, t, r, b = struct.unpack("llll", rect.raw)
        self.window_rect = {"left": l, "top": t, "width": r - l, "height": b - t}

    def _detect_minimap(self):
        self._update_window_rect()
        frame = self._capture_window()
        roi_top = 15
        roi = frame[roi_top:roi_top + 230, 0:220].copy()
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        bm = cv2.inRange(hsv, np.array([0, 0, 100]), np.array([180, 50, 255]))
        bm = cv2.morphologyEx(bm, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(bm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        outer = None
        max_a = 0
        for c in contours:
            x, y, cw, ch = cv2.boundingRect(c)
            a = cv2.contourArea(c)
            if cw > 80 and ch > 100 and a > max_a:
                max_a = a
                outer = (x, y, cw, ch)
        ox, oy, ow, oh = outer if outer else (5, 0, 200, 220)
        self.minimap_rect = {"left": ox, "top": roi_top + oy, "width": ow, "height": oh}

        inner = gray[oy:oy + oh, ox:ox + ow]

        def find_h(img, sy, ey, step, th=140, ratio=0.8):
            for y in range(sy, ey, step):
                if 0 <= y < img.shape[0] and np.sum(img[y, :] > th) > ow * ratio:
                    return y
            return None

        def find_v(img, sx, ex, step, yr, th=140, ratio=0.45):
            y1, y2 = yr
            for x in range(sx, ex, step):
                if 0 <= x < img.shape[1] and np.sum(img[y1:y2, x] > th) > (y2 - y1) * ratio:
                    return x
            return None

        top_y = find_h(inner, int(oh * 0.35), int(oh * 0.6), 1)
        bottom_y = find_h(inner, oh - 15, int(oh * 0.5), -1)
        if top_y and bottom_y and bottom_y > top_y:
            left_x = find_v(inner, 3, ow // 2, 1, (top_y, bottom_y))
            right_x = find_v(inner, ow - 4, ow // 2, -1, (top_y, bottom_y))
        else:
            top_y = top_y or int(oh * 0.38)
            bottom_y = bottom_y or oh - 3
            left_x, right_x = 3, ow - 3

        pad = 2
        self.map_area_rect = {
            "left": ox + left_x + pad,
            "top": roi_top + oy + top_y + pad,
            "width": right_x - left_x - pad * 2,
            "height": bottom_y - top_y - pad * 2 - 10
        }
        self._save_region()
        print(f"地图: {self.map_area_rect['width']}x{self.map_area_rect['height']}")

    def _save_region(self):
        with open(REGION_FILE, "w", encoding="utf-8") as f:
            json.dump({"minimap": self.minimap_rect, "map": self.map_area_rect}, f, indent=2)

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
        r = self.window_rect
        return np.array(self.sct.grab(r))[:, :, :3]

    def _capture_map(self):
        r = self.map_area_rect
        reg = {
            "left": self.window_rect["left"] + r["left"],
            "top": self.window_rect["top"] + r["top"],
            "width": r["width"],
            "height": r["height"]
        }
        return np.array(self.sct.grab(reg))[:, :, :3]

    def find_player_dot(self, map_area):
        """ROI跟踪：先在上一帧附近搜索，找不到再全图搜索"""
        hsv = cv2.cvtColor(map_area, cv2.COLOR_BGR2HSV)
        lower = np.array([YELLOW_H_LOW, YELLOW_S_LOW, YELLOW_V_LOW])
        upper = np.array([YELLOW_H_HIGH, 255, 255])
        h, w = map_area.shape[:2]

        if self.last_player_pos:
            cx, cy = self.last_player_pos
            x1 = max(0, cx - 12)
            y1 = max(0, cy - 12)
            x2 = min(w, cx + 13)
            y2 = min(h, cy + 13)
            roi_hsv = hsv[y1:y2, x1:x2]
            mask = cv2.inRange(roi_hsv, lower, upper)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 30]
            if valid:
                largest = max(valid, key=cv2.contourArea)
                M = cv2.moments(largest)
                if M["m00"] > 0:
                    px = int(M["m10"] / M["m00"]) + x1
                    py = int(M["m01"] / M["m00"]) + y1
                    self.last_player_pos = (px, py)
                    return (px, py)

        mask = cv2.inRange(hsv, lower, upper)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 30]
        if valid:
            largest = max(valid, key=cv2.contourArea)
            M = cv2.moments(largest)
            if M["m00"] > 0:
                px = int(M["m10"] / M["m00"])
                py = int(M["m01"] / M["m00"])
                self.last_player_pos = (px, py)
                return (px, py)
        self.last_player_pos = None
        return None

    def extract_platform(self, points):
        if len(points) < 2:
            return []
        ys = sorted(set(int(p[1] // 3) * 3 for p in points))
        clusters = []
        cur = [ys[0]]
        for y in ys[1:]:
            if y - cur[-1] <= 6:
                cur.append(y)
            else:
                clusters.append(cur)
                cur = [y]
        clusters.append(cur)
        platforms = []
        for cl in clusters:
            cp = [p for p in points if int(p[1] // 3) * 3 in cl]
            if len(cp) < 2:
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
        if len(points) < 2:
            return []
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return [{
            "id": len(self.ladders),
            "x": float(sorted(xs)[len(xs) // 2]),
            "y_top": float(min(ys)),
            "y_bottom": float(max(ys))
        }]

    def _check_hotkeys(self):
        """检测全局热键（边沿触发）"""
        # F9: 平台录制
        f9_now = key_pressed(VK_F9)
        if f9_now and not self.f9_was_pressed:
            if self.recording_ladder:
                print("先停梯子(F10)")
            elif self.recording_platform:
                np_ = self.extract_platform(self.platform_points)
                if np_:
                    self.platforms.extend(np_)
                    print(f"提取{len(np_)}个平台, 共{len(self.platform_points)}点")
                else:
                    print(f"未提取到平台, 共{len(self.platform_points)}点")
                self.platform_points = []
                self.recording_platform = False
            else:
                self.recording_platform = True
                self.platform_points = []
                print("平台录制开始...")
        self.f9_was_pressed = f9_now

        # F10: 梯子录制
        f10_now = key_pressed(VK_F10)
        if f10_now and not self.f10_was_pressed:
            if self.recording_platform:
                print("先停平台(F9)")
            elif self.recording_ladder:
                nl = self.extract_ladder(self.ladder_points)
                if nl:
                    self.ladders.extend(nl)
                    print(f"提取{len(nl)}个梯子, 共{len(self.ladder_points)}点")
                else:
                    print(f"未提取到梯子, 共{len(self.ladder_points)}点")
                self.ladder_points = []
                self.recording_ladder = False
            else:
                self.recording_ladder = True
                self.ladder_points = []
                print("梯子录制开始...")
        self.f10_was_pressed = f10_now

        # F11: 清除
        f11_now = key_pressed(VK_F11)
        if f11_now and not self.f11_was_pressed:
            self.platform_points = []
            self.ladder_points = []
            print("已清除")
        self.f11_was_pressed = f11_now

        # F12: 保存
        f12_now = key_pressed(VK_F12)
        if f12_now and not self.f12_was_pressed:
            self._save()
        self.f12_was_pressed = f12_now

    def draw(self, map_area, player_pos):
        display = map_area.copy()
        h, w = display.shape[:2]
        for p in self.platforms:
            x1 = int(max(0, min(p["x_min"], w - 1)))
            x2 = int(max(0, min(p["x_max"], w - 1)))
            y = int(max(0, min(p["y_base"], h - 1)))
            cv2.line(display, (x1, y), (x2, y), COLOR_PLATFORM, 1)
        for l in self.ladders:
            x = int(max(0, min(l["x"], w - 1)))
            y1 = int(max(0, min(l["y_top"], h - 1)))
            y2 = int(max(0, min(l["y_bottom"], h - 1)))
            cv2.line(display, (x, y1), (x, y2), COLOR_LADDER, 1)
        if self.recording_platform and len(self.platform_points) > 1:
            cv2.polylines(display, [np.array(self.platform_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        if self.recording_ladder and len(self.ladder_points) > 1:
            cv2.polylines(display, [np.array(self.ladder_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        if player_pos:
            cv2.circle(display, player_pos, 2, COLOR_PLAYER, -1)
            cv2.circle(display, player_pos, 4, (0, 0, 255), 1)
        display = cv2.resize(display, (int(w * DISPLAY_SCALE), int(h * DISPLAY_SCALE)),
                             interpolation=cv2.INTER_NEAREST)
        y = 18
        status = "平台录制中(F9停)" if self.recording_platform else ("梯子录制中(F10停)" if self.recording_ladder else "待机")
        cv2.putText(display, status, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        y += 16
        pos_str = f"光点:{player_pos}" if player_pos else "光点:未检测到"
        cv2.putText(display, pos_str, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_PLAYER, 1)
        y += 14
        cv2.putText(display, f"平台{len(self.platforms)} 梯子{len(self.ladders)} 轨迹{len(self.platform_points) + len(self.ladder_points)}",
                    (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        y += 14
        cv2.putText(display, "F9平台 F10梯子 F11清除 F12保存", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1)
        return display

    def run(self):
        win = "Minimap Route Recorder | F9平台 F10梯子 F11清除 F12保存 R重检 Q退出"
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        while True:
            try:
                map_area = self._capture_map()
            except Exception:
                time.sleep(0.05)
                continue

            self.frame_count += 1
            if self.frame_count % 2 == 0 or self.last_player_pos is None:
                player_pos = self.find_player_dot(map_area)
            else:
                player_pos = self.last_player_pos

            if self.recording_platform and player_pos:
                self.platform_points.append(player_pos)
            if self.recording_ladder and player_pos:
                self.ladder_points.append(player_pos)

            # 检测全局热键
            self._check_hotkeys()

            cv2.imshow(win, self.draw(map_area, player_pos))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                break
            elif key == ord('r'):
                print("重新检测...")
                self._detect_minimap()
        cv2.destroyAllWindows()
        print(f"最终: 平台{len(self.platforms)}个, 梯子{len(self.ladders)}个")


if __name__ == "__main__":
    MinimapRouteRecorder().run()