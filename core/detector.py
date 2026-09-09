"""
YOLO 目标检测封装模块
用户将训练好的 .pt 模型放到 data/models/ 目录下，配置好路径即可使用。

支持的检测类别（可在 config.json 中自定义 class_names）:
  - player:  玩家人物
  - monster: 怪物
  - ladder:  梯子
  - npc:     NPC
  - portal:  传送点/入口

检测结果统一格式:
  Detection = {
      "class": str,      # 类别名称，如 "monster"
      "class_id": int,   # 类别ID
      "confidence": float,
      "bbox": [x1, y1, x2, y2],  # 检测框
      "center": (cx, cy)         # 中心点
  }
"""
import os
from pathlib import Path

try:
    from ultralytics import YOLO
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False

from utils.geometry import bbox_center


class YoloDetector:
    def __init__(self, model_path, confidence=0.5, iou_threshold=0.45,
                 device="cpu", class_names=None):
        """
        初始化 YOLO 检测器

        Args:
            model_path: 训练好的 .pt 模型路径
            confidence: 置信度阈值
            iou_threshold: NMS 的 IoU 阈值
            device: 推理设备 "cpu" / "cuda:0" / "mps"
            class_names: 类别ID到名称的映射字典，如 {"player": 0, "monster": 1}
        """
        self.model_path = model_path
        self.confidence = confidence
        self.iou_threshold = iou_threshold
        self.device = device
        self.class_names = class_names or {}
        self._id_to_name = {v: k for k, v in self.class_names.items()}
        self.model = None
        self._loaded = False

    def load_model(self):
        """加载 YOLO 模型"""
        if not HAS_YOLO:
            raise RuntimeError(
                "ultralytics 未安装，请运行: pip install ultralytics"
            )
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"YOLO 模型文件不存在: {self.model_path}\n"
                f"请将训练好的 .pt 文件放到该路径，或在 config.json 中修改 model_path"
            )

        self.model = YOLO(self.model_path)
        self._loaded = True
        print(f"[YOLO] 模型加载成功: {self.model_path}")
        print(f"[YOLO] 模型类别: {self.model.names}")

        # 如果用户没配置 class_names，自动从模型读取
        if not self.class_names:
            self.class_names = {v: k for k, v in self.model.names.items()}
            self._id_to_name = self.model.names

        return self

    def detect(self, frame):
        """
        对一帧图像进行目标检测

        Args:
            frame: BGR 格式的 numpy 数组（OpenCV 格式）

        Returns:
            list[dict]: 检测结果列表，每个元素为标准化的 Detection 字典
        """
        if not self._loaded:
            self.load_model()

        results = self.model.predict(
            source=frame,
            conf=self.confidence,
            iou=self.iou_threshold,
            device=self.device,
            verbose=False
        )

        detections = []
        if results and len(results) > 0:
            result = results[0]
            boxes = result.boxes
            if boxes is not None:
                for box in boxes:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    xyxy = box.xyxy[0].cpu().numpy()
                    x1, y1, x2, y2 = [float(v) for v in xyxy]

                    cls_name = self._id_to_name.get(cls_id, f"class_{cls_id}")

                    detections.append({
                        "class": cls_name,
                        "class_id": cls_id,
                        "confidence": conf,
                        "bbox": [x1, y1, x2, y2],
                        "center": bbox_center([x1, y1, x2, y2])
                    })

        return detections

    def detect_by_class(self, frame, class_name):
        """只检测指定类别的目标"""
        all_dets = self.detect(frame)
        return [d for d in all_dets if d["class"] == class_name]

    def get_players(self, frame):
        """获取所有玩家检测结果"""
        return self.detect_by_class(frame, "player")

    def get_monsters(self, frame):
        """获取所有怪物检测结果"""
        return self.detect_by_class(frame, "monster")

    def get_ladders(self, frame):
        """获取所有梯子检测结果"""
        return self.detect_by_class(frame, "ladder")

    def is_loaded(self):
        return self._loaded
