"""
人物模板匹配定位模块
通过手动截取人物角色的特征图（像素块）作为模板，
使用 OpenCV 模板匹配 (cv2.matchTemplate) 在全屏截图中定位人物坐标。

支持:
  - 左右朝向各一张或多张模板图
  - 多模板同时匹配，取置信度最高的结果
  - 可设置匹配置信度阈值
  - 模板图保存在 data/templates/ 目录

模板文件命名规则:
  player_left_0.png, player_left_1.png, ...  (左朝向)
  player_right_0.png, player_right_1.png, ... (右朝向)
"""
import os
import cv2
import numpy as np
from pathlib import Path


class PlayerTemplate:
    """单个人物模板"""
    def __init__(self, file_path, direction):
        """
        Args:
            file_path: 模板图片路径
            direction: "left" 或 "right"
        """
        self.file_path = file_path
        self.direction = direction  # "left" / "right"
        self.image = None
        self.width = 0
        self.height = 0
        self._load()

    def _load(self):
        if os.path.exists(self.file_path):
            self.image = cv2.imread(self.file_path, cv2.IMREAD_COLOR)
            if self.image is not None:
                self.height, self.width = self.image.shape[:2]

    def is_valid(self):
        return self.image is not None

    def match(self, frame, threshold=0.7):
        """
        在帧中匹配该模板

        Args:
            frame: BGR 全屏截图
            threshold: 匹配置信度阈值 (0-1)

        Returns:
            dict | None: {
                "position": (x, y),       # 模板左上角坐标
                "center": (cx, cy),       # 中心点坐标
                "confidence": float,      # 匹配度
                "direction": str,         # "left" / "right"
                "width": int,
                "height": int
            }
        """
        if not self.is_valid():
            return None

        # 模板比帧大，无法匹配
        if self.height > frame.shape[0] or self.width > frame.shape[1]:
            return None

        # 执行模板匹配
        result = cv2.matchTemplate(frame, self.image, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val < threshold:
            return None

        x, y = max_loc
        cx = x + self.width / 2
        cy = y + self.height / 2

        return {
            "position": (x, y),
            "center": (cx, cy),
            "confidence": float(max_val),
            "direction": self.direction,
            "width": self.width,
            "height": self.height
        }


class PlayerTracker:
    """
    人物追踪器
    管理多个人物模板，在每帧中匹配定位人物。
    """

    TEMPLATES_DIR = "data/templates"

    def __init__(self, templates_dir=None, match_threshold=0.7):
        """
        Args:
            templates_dir: 模板图存放目录
            match_threshold: 匹配置信度阈值 (0-1)
        """
        self.templates_dir = templates_dir or self.TEMPLATES_DIR
        self.match_threshold = match_threshold
        self.templates = []       # [PlayerTemplate, ...]
        self.last_position = None  # 上一次定位结果
        self.last_direction = None
        self._load_templates()

        # 确保目录存在
        os.makedirs(self.templates_dir, exist_ok=True)

    def _load_templates(self):
        """从目录加载所有模板图"""
        self.templates = []
        if not os.path.exists(self.templates_dir):
            return

        for filename in os.listdir(self.templates_dir):
            if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                continue
            if filename.startswith("player_left_"):
                direction = "left"
            elif filename.startswith("player_right_"):
                direction = "right"
            else:
                continue

            file_path = os.path.join(self.templates_dir, filename)
            template = PlayerTemplate(file_path, direction)
            if template.is_valid():
                self.templates.append(template)

        print(f"[人物追踪] 加载了 {len(self.templates)} 个人物模板 "
              f"(左:{self.left_count}, 右:{self.right_count})")

    def reload(self):
        """重新加载模板（添加/删除模板后调用）"""
        self._load_templates()

    @property
    def left_count(self):
        return sum(1 for t in self.templates if t.direction == "left")

    @property
    def right_count(self):
        return sum(1 for t in self.templates if t.direction == "right")

    @property
    def has_templates(self):
        return len(self.templates) > 0

    def track(self, frame):
        """
        在帧中定位人物

        Args:
            frame: BGR 全屏截图

        Returns:
            dict | None: 最佳匹配结果 {
                "center": (cx, cy),
                "confidence": float,
                "direction": "left"/"right",
                "bbox": [x1, y1, x2, y2]
            }
        """
        if not self.has_templates:
            return None

        best_match = None
        best_confidence = 0

        # 遍历所有模板，找最佳匹配
        for template in self.templates:
            result = template.match(frame, self.match_threshold)
            if result and result["confidence"] > best_confidence:
                best_match = result
                best_confidence = result["confidence"]

        if best_match is None:
            return None

        self.last_position = best_match["center"]
        self.last_direction = best_match["direction"]

        x, y = best_match["position"]
        return {
            "center": best_match["center"],
            "confidence": best_match["confidence"],
            "direction": best_match["direction"],
            "bbox": [x, y, x + best_match["width"], y + best_match["height"]]
        }

    def save_template(self, image, direction, index=None):
        """
        保存一张人物模板图

        Args:
            image: BGR 图像（裁剪好的人物特征块）
            direction: "left" 或 "right"
            index: 模板序号，None 则自动递增

        Returns:
            str: 保存的文件路径
        """
        os.makedirs(self.templates_dir, exist_ok=True)

        if index is None:
            # 自动找下一个序号
            existing = [f for f in os.listdir(self.templates_dir)
                        if f.startswith(f"player_{direction}_")]
            index = len(existing)

        filename = f"player_{direction}_{index}.png"
        file_path = os.path.join(self.templates_dir, filename)
        cv2.imwrite(file_path, image)

        # 重新加载
        self.reload()
        print(f"[人物追踪] 保存模板: {file_path}")
        return file_path

    def delete_template(self, direction, index):
        """删除指定模板"""
        filename = f"player_{direction}_{index}.png"
        file_path = os.path.join(self.templates_dir, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            self.reload()
            print(f"[人物追踪] 删除模板: {file_path}")
            return True
        return False

    def clear_templates(self, direction=None):
        """
        清除模板
        direction=None 清除全部，"left"/"right" 清除指定朝向
        """
        if not os.path.exists(self.templates_dir):
            return
        for filename in os.listdir(self.templates_dir):
            if direction:
                if not filename.startswith(f"player_{direction}_"):
                    continue
            elif not filename.startswith("player_"):
                continue
            os.remove(os.path.join(self.templates_dir, filename))
        self.reload()

    def list_templates(self):
        """列出所有模板信息"""
        result = []
        for i, t in enumerate(self.templates):
            result.append({
                "index": i,
                "direction": t.direction,
                "width": t.width,
                "height": t.height,
                "file": os.path.basename(t.file_path)
            })
        return result
