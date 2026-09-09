"""
小地图标记窗口模块
功能:
  1. 截取游戏小地图区域作为底图
  2. 在小地图上绘制:
     - 绿色线段/区域: 已记录的平台
     - 蓝色竖线: 梯子位置
     - 红色圆点: 当前检测到的怪物
     - 黄色圆点: 人物当前位置
  3. 支持全屏坐标到小地图坐标的映射
  4. 独立 OpenCV 窗口显示
"""
import cv2
import numpy as np
import threading
import time

from utils.capture import ScreenCapture


class MinimapWindow:
    """小地图标记窗口"""

    # 颜色定义 (BGR)
    COLOR_PLATFORM = (0, 255, 0)      # 绿色 - 平台
    COLOR_LADDER = (255, 100, 0)      # 蓝色 - 梯子
    COLOR_MONSTER = (0, 0, 255)       # 红色 - 怪物
    COLOR_PLAYER = (0, 255, 255)      # 黄色 - 人物
    COLOR_TEXT = (255, 255, 255)      # 白色 - 文字

    def __init__(self, minimap_region=None, scale=1.0):
        """
        Args:
            minimap_region: [x, y, w, h] 小地图在屏幕上的区域
            scale: 显示缩放比例
        """
        self.minimap_region = minimap_region or [1700, 50, 200, 200]
        self.scale = scale
        self.capture = ScreenCapture(region=self.minimap_region)

        self._window_name = "Minimap - 地图标记"
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()

        # 实时数据（由外部更新）
        self._player_pos = None
        self._monster_positions = []
        self._platforms = []
        self._ladders = []

        # 坐标映射（全屏坐标 → 小地图坐标）
        # 简单线性映射，可通过 calibrate 校准
        self._map_offset_x = 0
        self._map_offset_y = 0
        self._map_scale_x = 1.0
        self._map_scale_y = 1.0

        # 底图缓存
        self._base_map = None

    def set_data(self, player_pos=None, monsters=None, platforms=None, ladders=None):
        """
        更新小地图上的实时数据（线程安全）

        Args:
            player_pos: (x, y) 全屏坐标
            monsters: [(x, y), ...] 怪物全屏坐标列表
            platforms: [Platform, ...] 平台列表
            ladders: [Ladder, ...] 梯子列表
        """
        if player_pos is not None:
            self._player_pos = player_pos
        if monsters is not None:
            self._monster_positions = monsters
        if platforms is not None:
            self._platforms = platforms
        if ladders is not None:
            self._ladders = ladders

    def calibrate(self, full_screen_points, minimap_points):
        """
        校准坐标映射
        通过对应点计算变换矩阵（透视变换）

        Args:
            full_screen_points: [(x,y), ...] 全屏坐标点（至少4个）
            minimap_points: [(x,y), ...] 对应小地图坐标点（至少4个）
        """
        if len(full_screen_points) >= 4 and len(minimap_points) >= 4:
            src = np.float32(full_screen_points[:4])
            dst = np.float32(minimap_points[:4])
            self._transform_matrix = cv2.getPerspectiveTransform(src, dst)
            self._has_transform = True
        else:
            # 简单线性映射
            self._has_transform = False

    def _world_to_minimap(self, x, y):
        """
        将全屏坐标转换为小地图坐标

        简化版: 假设小地图是全屏的等比例缩略图
        实际使用时应通过 calibrate 校准
        """
        if hasattr(self, '_has_transform') and self._has_transform:
            point = np.float32([[[x, y]]])
            transformed = cv2.perspectiveTransform(point, self._transform_matrix)
            return int(transformed[0][0][0]), int(transformed[0][0][1])
        else:
            # 简单映射: 小地图区域内的相对位置
            mx = int((x - self._map_offset_x) * self._map_scale_x)
            my = int((y - self._map_offset_y) * self._map_scale_y)
            return mx, my

    def _draw_platforms(self, img):
        """绘制平台"""
        for p in self._platforms:
            # 平台在小地图上画一条水平线
            x1, _ = self._world_to_minimap(p.x_min, p.y_base)
            x2, _ = self._world_to_minimap(p.x_max, p.y_base)
            _, y = self._world_to_minimap(0, p.y_base)

            # 确保在图像范围内
            h, w = img.shape[:2]
            x1 = max(0, min(x1, w - 1))
            x2 = max(0, min(x2, w - 1))
            y = max(0, min(y, h - 1))

            cv2.line(img, (x1, y), (x2, y), self.COLOR_PLATFORM, 2)
            cv2.putText(img, f"P{p.id}", (x1, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, self.COLOR_PLATFORM, 1)

    def _draw_ladders(self, img):
        """绘制梯子"""
        for ladder in self._ladders:
            x, y1 = self._world_to_minimap(ladder.x, ladder.y_top)
            _, y2 = self._world_to_minimap(ladder.x, ladder.y_bottom)

            h, w = img.shape[:2]
            x = max(0, min(x, w - 1))
            y1 = max(0, min(y1, h - 1))
            y2 = max(0, min(y2, h - 1))

            cv2.line(img, (x, y1), (x, y2), self.COLOR_LADDER, 2)
            cv2.putText(img, f"L{ladder.id}", (x + 3, (y1 + y2) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, self.COLOR_LADDER, 1)

    def _draw_monsters(self, img):
        """绘制怪物"""
        for pos in self._monster_positions:
            x, y = self._world_to_minimap(pos[0], pos[1])
            h, w = img.shape[:2]
            if 0 <= x < w and 0 <= y < h:
                cv2.circle(img, (x, y), 3, self.COLOR_MONSTER, -1)

    def _draw_player(self, img):
        """绘制人物"""
        if self._player_pos:
            x, y = self._world_to_minimap(self._player_pos[0], self._player_pos[1])
            h, w = img.shape[:2]
            if 0 <= x < w and 0 <= y < h:
                cv2.circle(img, (x, y), 5, self.COLOR_PLAYER, -1)
                cv2.circle(img, (x, y), 7, self.COLOR_PLAYER, 1)

    def _draw_legend(self, img):
        """绘制图例"""
        h, w = img.shape[:2]
        y_offset = 10

        items = [
            ("平台", self.COLOR_PLATFORM),
            ("梯子", self.COLOR_LADDER),
            ("怪物", self.COLOR_MONSTER),
            ("人物", self.COLOR_PLAYER),
        ]

        for name, color in items:
            cv2.circle(img, (12, y_offset + 4), 4, color, -1)
            cv2.putText(img, name, (20, y_offset + 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, self.COLOR_TEXT, 1)
            y_offset += 16

    def _render_frame(self):
        """渲染一帧小地图图像"""
        # 截取小地图底图
        try:
            base = self.capture.capture()
            if base is not None:
                self._base_map = base.copy()
        except Exception:
            pass

        if self._base_map is None:
            # 创建空白底图
            w, h = self.minimap_region[2], self.minimap_region[3]
            self._base_map = np.zeros((h, w, 3), dtype=np.uint8)

        img = self._base_map.copy()

        # 绘制各元素
        self._draw_platforms(img)
        self._draw_ladders(img)
        self._draw_monsters(img)
        self._draw_player(img)
        self._draw_legend(img)

        # 缩放
        if self.scale != 1.0:
            img = cv2.resize(img, None, fx=self.scale, fy=self.scale)

        return img

    def show(self):
        """显示小地图窗口（阻塞，在子线程运行）"""
        cv2.namedWindow(self._window_name, cv2.WINDOW_NORMAL)
        self._running = True
        self._stop_event.clear()

        while not self._stop_event.is_set():
            img = self._render_frame()
            cv2.imshow(self._window_name, img)

            # 等待按键，按 q 或 ESC 关闭
            key = cv2.waitKey(100) & 0xFF
            if key in (ord('q'), 27):
                break

        self._running = False
        cv2.destroyWindow(self._window_name)

    def start(self):
        """在后台线程启动小地图窗口"""
        if self._running:
            return
        self._thread = threading.Thread(target=self.show, daemon=True)
        self._thread.start()

    def stop(self):
        """关闭小地图窗口"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1)
        cv2.destroyWindow(self._window_name)

    def get_snapshot(self):
        """获取当前渲染的小地图图像（供UI嵌入使用）"""
        return self._render_frame()
