"""
路线录制与可视化测试脚本
功能:
  - 实时全屏截图 + 模板匹配定位人物
  - 按 P 键: 开始/停止平台录制（人物走动记录平台范围）
  - 按 L 键: 开始/停止梯子录制（人物爬梯子记录位置）
  - 按 C 键: 清除当前录制的点
  - 按 M 键: 切换显示模式（全屏路线图 / 小地图）
  - 按 S 键: 保存平台和梯子数据
  - 按 Q/ESC: 退出

显示:
  - 绿色水平线 = 已录制的平台
  - 蓝色竖线 = 已录制的梯子
  - 红色点 = 当前录制中的轨迹点
  - 黄色圈 = 人物当前位置
"""
import cv2
import numpy as np
import mss
import time
import json
import os
import ctypes
from collections import defaultdict

# Win32 API 常量
SW_MINIMIZE = 6
SW_RESTORE = 9
SW_SHOW = 5

# ============ 配置 ============
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "data", "templates", "player_right_0.png")
MATCH_THRESHOLD = 0.85
PLATFORMS_FILE = os.path.join(os.path.dirname(__file__), "data", "platforms.json")
LADDERS_FILE = os.path.join(os.path.dirname(__file__), "data", "ladders.json")

# 小地图区域（根据你的截图，左上角）
MINIMAP_REGION = [0, 0, 170, 160]

# 颜色 (BGR)
COLOR_PLATFORM = (0, 255, 0)
COLOR_LADDER = (255, 100, 0)
COLOR_RECORDING = (0, 0, 255)
COLOR_PLAYER = (0, 255, 255)
COLOR_TEXT = (255, 255, 255)


class RouteRecorder:
    def __init__(self):
        self.template = cv2.imread(TEMPLATE_PATH, cv2.IMREAD_COLOR)
        if self.template is None:
            raise FileNotFoundError(f"模板不存在: {TEMPLATE_PATH}")
        self.th, self.tw = self.template.shape[:2]

        self.sct = mss.mss()
        self.monitor = self.sct.monitors[1]

        # 录制状态
        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []

        # 已保存的平台和梯子
        self.platforms = self._load(PLATFORMS_FILE, "platforms")
        self.ladders = self._load(LADDERS_FILE, "ladders")

        # 显示模式: "full" 全屏路线图, "minimap" 小地图
        self.display_mode = "full"

        print(f"模板: {self.tw}x{self.th}, 阈值: {MATCH_THRESHOLD}")
        print(f"已加载平台: {len(self.platforms)}, 梯子: {len(self.ladders)}")
        print()
        print("快捷键:")
        print("  P - 开始/停止平台录制")
        print("  L - 开始/停止梯子录制")
        print("  C - 清除当前录制轨迹")
        print("  M - 切换显示模式(全屏/小地图)")
        print("  S - 保存平台和梯子数据")
        print("  Q/ESC - 退出")
        print()

    def _load(self, path, key):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get(key, [])
            except Exception:
                return []
        return []

    def _save(self):
        # 保存平台
        plat_data = {"platforms": self.platforms, "count": len(self.platforms)}
        with open(PLATFORMS_FILE, "w", encoding="utf-8") as f:
            json.dump(plat_data, f, indent=2, ensure_ascii=False)
        # 保存梯子
        lad_data = {"ladders": self.ladders, "count": len(self.ladders)}
        with open(LADDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(lad_data, f, indent=2, ensure_ascii=False)
        print(f"已保存: 平台{len(self.platforms)}个, 梯子{len(self.ladders)}个")

    def capture(self):
        """截图（截图前最小化自身窗口，避免截到自己形成递归）"""
        hwnd = getattr(self, '_hwnd', None)
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
            time.sleep(0.08)
        frame = np.array(self.sct.grab(self.monitor))
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.02)
        return frame[:, :, :3]

    def track_player(self, frame):
        """模板匹配定位人物，返回 (cx, cy, confidence) 或 None"""
        result = cv2.matchTemplate(frame, self.template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val >= MATCH_THRESHOLD:
            cx = max_loc[0] + self.tw // 2
            cy = max_loc[1] + self.th // 2
            return cx, cy, max_val
        return None

    def extract_platform(self, points):
        """从录制点提取平台（按y聚类，取x范围）"""
        if len(points) < 3:
            return None
        ys = sorted(set(int(p[1] // 10) * 10 for p in points))
        clusters = []
        current = [ys[0]]
        for y in ys[1:]:
            if y - current[-1] <= 20:
                current.append(y)
            else:
                clusters.append(current)
                current = [y]
        clusters.append(current)

        platforms = []
        for cluster in clusters:
            cluster_points = [p for p in points if int(p[1] // 10) * 10 in cluster]
            if len(cluster_points) < 3:
                continue
            xs = [p[0] for p in cluster_points]
            y_base = sum(p[1] for p in cluster_points) / len(cluster_points)
            platforms.append({
                "id": len(self.platforms) + len(platforms),
                "x_min": float(min(xs)),
                "x_max": float(max(xs)),
                "y_base": float(y_base)
            })
        return platforms

    def extract_ladder(self, points):
        """从录制点提取梯子"""
        if len(points) < 3:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x_median = sorted(xs)[len(xs) // 2]
        return [{
            "id": len(self.ladders),
            "x": float(x_median),
            "y_top": float(min(ys)),
            "y_bottom": float(max(ys))
        }]

    def draw_route_full(self, frame, player_pos):
        """在全屏图上绘制路线"""
        display = frame.copy()
        h, w = display.shape[:2]

        # 绘制已保存的平台（绿色水平线）
        for p in self.platforms:
            x1 = int(max(0, p["x_min"]))
            x2 = int(min(w - 1, p["x_max"]))
            y = int(p["y_base"])
            if 0 <= y < h:
                cv2.line(display, (x1, y), (x2, y), COLOR_PLATFORM, 3)
                cv2.putText(display, f"P{p['id']}", (x1, y - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_PLATFORM, 1)

        # 绘制已保存的梯子（蓝色竖线）
        for l in self.ladders:
            x = int(l["x"])
            y1 = int(max(0, l["y_top"]))
            y2 = int(min(h - 1, l["y_bottom"]))
            if 0 <= x < w:
                cv2.line(display, (x, y1), (x, y2), COLOR_LADDER, 3)
                cv2.putText(display, f"L{l['id']}", (x + 5, (y1 + y2) // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_LADDER, 1)

        # 绘制当前录制轨迹
        if self.recording_platform:
            for p in self.platform_points:
                cv2.circle(display, (int(p[0]), int(p[1])), 3, COLOR_RECORDING, -1)
        if self.recording_ladder:
            for p in self.ladder_points:
                cv2.circle(display, (int(p[0]), int(p[1])), 3, COLOR_RECORDING, -1)

        # 绘制人物位置
        if player_pos:
            cx, cy, conf = player_pos
            cv2.circle(display, (cx, cy), 8, COLOR_PLAYER, 2)
            cv2.circle(display, (cx, cy), 3, (0, 0, 255), -1)

        return display

    def draw_minimap(self, frame, player_pos):
        """在小地图上绘制路线"""
        # 截取小地图区域
        mx, my, mw, mh = MINIMAP_REGION
        h_frame, w_frame = frame.shape[:2]
        x2 = min(mx + mw, w_frame)
        y2 = min(my + mh, h_frame)
        minimap = frame[my:y2, mx:x2].copy()
        mh, mw = minimap.shape[:2]

        # 计算映射比例: 小地图是全屏地图的缩略图
        # 简化: 用人物当前位置作为参考，假设小地图中心对应人物
        # 这里用简单的比例映射，实际需要校准
        scale_x = mw / w_frame
        scale_y = mh / h_frame

        # 绘制平台
        for p in self.platforms:
            px1 = int(p["x_min"] * scale_x)
            px2 = int(p["x_max"] * scale_x)
            py = int(p["y_base"] * scale_y)
            px1 = max(0, min(px1, mw - 1))
            px2 = max(0, min(px2, mw - 1))
            py = max(0, min(py, mh - 1))
            cv2.line(minimap, (px1, py), (px2, py), COLOR_PLATFORM, 1)

        # 绘制梯子
        for l in self.ladders:
            lx = int(l["x"] * scale_x)
            ly1 = int(l["y_top"] * scale_y)
            ly2 = int(l["y_bottom"] * scale_y)
            lx = max(0, min(lx, mw - 1))
            ly1 = max(0, min(ly1, mh - 1))
            ly2 = max(0, min(ly2, mh - 1))
            cv2.line(minimap, (lx, ly1), (lx, ly2), COLOR_LADDER, 1)

        # 绘制人物
        if player_pos:
            cx, cy, _ = player_pos
            px = int(cx * scale_x)
            py = int(cy * scale_y)
            px = max(0, min(px, mw - 1))
            py = max(0, min(py, mh - 1))
            cv2.circle(minimap, (px, py), 4, COLOR_PLAYER, -1)

        # 放大显示小地图
        minimap = cv2.resize(minimap, (mw * 3, mh * 3), interpolation=cv2.INTER_NEAREST)
        return minimap

    def draw_hud(self, img, player_pos):
        """绘制状态信息"""
        h = img.shape[0]
        y = 25

        # 录制状态
        if self.recording_platform:
            cv2.putText(img, ">> 平台录制中 (按P停止) <<", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        elif self.recording_ladder:
            cv2.putText(img, ">> 梯子录制中 (按L停止) <<", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        else:
            cv2.putText(img, "待机 (P=平台 L=梯子 C=清除 M=切换 S=保存)", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        y += 25

        # 人物位置
        if player_pos:
            cx, cy, conf = player_pos
            cv2.putText(img, f"人物: ({cx},{cy}) conf={conf:.3f}", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_PLAYER, 1)
        else:
            cv2.putText(img, "人物: 未检测到", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        y += 20

        # 统计
        cv2.putText(img, f"平台: {len(self.platforms)}  梯子: {len(self.ladders)}  "
                        f"平台轨迹点: {len(self.platform_points)}  梯子轨迹点: {len(self.ladder_points)}",
                    (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_TEXT, 1)
        y += 20

        # 显示模式
        mode_text = "全屏路线图" if self.display_mode == "full" else "小地图视图"
        cv2.putText(img, f"模式: {mode_text} (按M切换)", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

    def run(self):
        window_name = "Route Recorder - 路线录制 | P平台 L梯子 C清除 M切换 S保存 Q退出"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, 1280, 720)
        # 获取窗口句柄，用于截图前最小化
        time.sleep(0.3)
        self._hwnd = ctypes.windll.user32.FindWindowW(None, window_name)
        print(f"窗口句柄: {self._hwnd}")

        while True:
            frame = self.capture()
            player_pos = self.track_player(frame)

            # 录制中记录点
            if self.recording_platform and player_pos:
                self.platform_points.append((player_pos[0], player_pos[1]))
            if self.recording_ladder and player_pos:
                self.ladder_points.append((player_pos[0], player_pos[1]))

            # 绘制
            if self.display_mode == "full":
                display = self.draw_route_full(frame, player_pos)
            else:
                display = self.draw_minimap(frame, player_pos)

            self.draw_hud(display, player_pos)

            # 缩放
            h, w = display.shape[:2]
            scale = min(1280 / w, 720 / h)
            if scale < 1.0:
                display = cv2.resize(display, None, fx=scale, fy=scale)

            cv2.imshow(window_name, display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                break
            elif key == ord('p'):
                if self.recording_ladder:
                    print("请先停止梯子录制")
                elif self.recording_platform:
                    # 停止平台录制，提取平台
                    new_platforms = self.extract_platform(self.platform_points)
                    if new_platforms:
                        self.platforms.extend(new_platforms)
                        print(f"平台录制结束，提取到 {len(new_platforms)} 个平台")
                    else:
                        print("平台录制结束，未提取到有效平台（点太少）")
                    self.platform_points = []
                    self.recording_platform = False
                else:
                    self.recording_platform = True
                    self.platform_points = []
                    print("平台录制开始，请在目标平台上走动...")
            elif key == ord('l'):
                if self.recording_platform:
                    print("请先停止平台录制")
                elif self.recording_ladder:
                    new_ladders = self.extract_ladder(self.ladder_points)
                    if new_ladders:
                        self.ladders.extend(new_ladders)
                        print(f"梯子录制结束，提取到 {len(new_ladders)} 个梯子")
                    else:
                        print("梯子录制结束，未提取到有效梯子")
                    self.ladder_points = []
                    self.recording_ladder = False
                else:
                    self.recording_ladder = True
                    self.ladder_points = []
                    print("梯子录制开始，请爬一遍目标梯子...")
            elif key == ord('c'):
                self.platform_points = []
                self.ladder_points = []
                print("已清除当前录制轨迹")
            elif key == ord('m'):
                self.display_mode = "minimap" if self.display_mode == "full" else "full"
                print(f"切换到: {'小地图视图' if self.display_mode == 'minimap' else '全屏路线图'}")
            elif key == ord('s'):
                self._save()

        cv2.destroyAllWindows()
        print("\n最终数据:")
        print(f"  平台: {len(self.platforms)} 个")
        for p in self.platforms:
            print(f"    P{p['id']}: x=[{p['x_min']:.0f},{p['x_max']:.0f}] y={p['y_base']:.0f}")
        print(f"  梯子: {len(self.ladders)} 个")
        for l in self.ladders:
            print(f"    L{l['id']}: x={l['x']:.0f} y=[{l['y_top']:.0f},{l['y_bottom']:.0f}]")


if __name__ == "__main__":
    recorder = RouteRecorder()
    recorder.run()
