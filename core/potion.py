"""
药品自动系统模块
通过 OpenCV 图像识别血条/蓝条百分比，低于阈值时自动吃药。
支持:
  - 红药（HP）自动使用
  - 蓝药（MP）自动使用
  - 可配置血条/蓝条的屏幕区域和颜色
"""
import time
import cv2
import numpy as np


class PotionManager:
    """药品管理器"""

    def __init__(self, controller, hp_threshold=30, mp_threshold=20,
                 hp_key="q", mp_key="w",
                 hp_bar_region=None, mp_bar_region=None,
                 hp_color=None, mp_color=None):
        """
        Args:
            controller: InputController 实例
            hp_threshold: HP 低于此百分比时吃药
            mp_threshold: MP 低于此百分比时吃药
            hp_key: 红药按键
            mp_key: 蓝药按键
            hp_bar_region: [x, y, w, h] 血条在屏幕上的区域
            mp_bar_region: [x, y, w, h] 蓝条在屏幕上的区域
            hp_color: [R, G, B] 血条颜色（用于颜色识别）
            mp_color: [R, G, B] 蓝条颜色
        """
        self.controller = controller
        self.hp_threshold = hp_threshold
        self.mp_threshold = mp_threshold
        self.hp_key = hp_key
        self.mp_key = mp_key
        self.hp_bar_region = hp_bar_region or [10, 10, 200, 20]
        self.mp_bar_region = mp_bar_region or [10, 35, 200, 20]
        self.hp_color = np.array(hp_color or [255, 0, 0])
        self.mp_color = np.array(mp_color or [0, 0, 255])

        # 吃药冷却（防止连续吃）
        self._hp_last_use = 0
        self._mp_last_use = 0
        self._potion_cooldown = 1.0  # 吃药最小间隔1秒

        # 统计
        self.hp_potion_count = 0
        self.mp_potion_count = 0

    def read_bar_percentage(self, frame, region, target_color, tolerance=40):
        """
        从截图中读取血条/蓝条百分比

        Args:
            frame: 全屏截图（BGR）
            region: [x, y, w, h] 条的区域
            target_color: [B, G, R] 目标颜色（注意OpenCV是BGR）
            tolerance: 颜色容差

        Returns:
            float: 百分比 0-100
        """
        x, y, w, h = region
        # 确保区域在帧内
        h_frame, w_frame = frame.shape[:2]
        x = max(0, min(x, w_frame - 1))
        y = max(0, min(y, h_frame - 1))
        w = min(w, w_frame - x)
        h = min(h, h_frame - y)

        if w <= 0 or h <= 0:
            return 100.0

        roi = frame[y:y+h, x:x+w]

        # 转换目标颜色为BGR（配置中写的是RGB，这里转一下）
        target_bgr = np.array([target_color[2], target_color[1], target_color[0]])

        # 颜色范围
        lower = np.clip(target_bgr - tolerance, 0, 255)
        upper = np.clip(target_bgr + tolerance, 0, 255)

        # 创建掩码
        mask = cv2.inRange(roi, lower, upper)

        # 计算填充比例
        filled_pixels = cv2.countNonZero(mask)
        total_pixels = roi.shape[0] * roi.shape[1]

        if total_pixels == 0:
            return 100.0

        percentage = (filled_pixels / total_pixels) * 100
        return min(100.0, max(0.0, percentage))

    def check_and_use_potions(self, frame):
        """
        检查血量蓝量，低于阈值时自动吃药

        Args:
            frame: 当前屏幕截图

        Returns:
            dict: {"hp_used": bool, "mp_used": bool, "hp_percent": float, "mp_percent": float}
        """
        result = {"hp_used": False, "mp_used": False, "hp_percent": 100, "mp_percent": 100}

        # 读取HP
        hp_percent = self.read_bar_percentage(frame, self.hp_bar_region, self.hp_color)
        result["hp_percent"] = hp_percent

        # 读取MP
        mp_percent = self.read_bar_percentage(frame, self.mp_bar_region, self.mp_color)
        result["mp_percent"] = mp_percent

        now = time.time()

        # HP 低于阈值
        if hp_percent < self.hp_threshold:
            if now - self._hp_last_use > self._potion_cooldown:
                self.controller.press_key(self.hp_key, duration=0.05)
                self._hp_last_use = now
                self.hp_potion_count += 1
                result["hp_used"] = True
                print(f"[药品] HP={hp_percent:.0f}%，使用红药")

        # MP 低于阈值
        if mp_percent < self.mp_threshold:
            if now - self._mp_last_use > self._potion_cooldown:
                self.controller.press_key(self.mp_key, duration=0.05)
                self._mp_last_use = now
                self.mp_potion_count += 1
                result["mp_used"] = True
                print(f"[药品] MP={mp_percent:.0f}%，使用蓝药")

        return result

    def calibrate_bar_region(self, frame, bar_type="hp"):
        """
        校准血条/蓝条区域（交互式，在UI中调用）
        简单实现: 返回当前区域，实际UI中可让用户框选
        """
        if bar_type == "hp":
            return self.hp_bar_region
        else:
            return self.mp_bar_region

    def to_dict(self):
        return {
            "hp_threshold": self.hp_threshold,
            "mp_threshold": self.mp_threshold,
            "hp_key": self.hp_key,
            "mp_key": self.mp_key,
            "hp_bar_region": self.hp_bar_region,
            "mp_bar_region": self.mp_bar_region,
            "hp_color": self.hp_color.tolist(),
            "mp_color": self.mp_color.tolist()
        }
