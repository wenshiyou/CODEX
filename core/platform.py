"""
平台记录与管理模块
功能:
  1. 录制模式: 人物在平台上走动时，持续记录人物坐标点
  2. 录制结束后，对坐标点做聚类分析，提取平台的水平范围和基准y值
  3. 保存/加载平台数据到 JSON
  4. 判断怪物是否在已记录的平台上（只打这些位置的怪）
  5. 提供平台信息给路径选择模块
"""
import json
import os
import time
from collections import defaultdict

try:
    from sklearn.cluster import DBSCAN
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

import numpy as np


class Platform:
    """单个平台的数据结构"""
    def __init__(self, platform_id, x_min, x_max, y_base, points=None):
        self.id = platform_id
        self.x_min = x_min
        self.x_max = x_max
        self.y_base = y_base       # 平台基准y坐标
        self.points = points or []  # 原始记录点

    def contains_x(self, x, margin=0):
        """判断x坐标是否在平台水平范围内"""
        return (self.x_min - margin) <= x <= (self.x_max + margin)

    def contains_y(self, y, threshold=30):
        """判断y坐标是否在平台垂直范围内"""
        return abs(y - self.y_base) <= threshold

    def contains_point(self, x, y, threshold=30, margin=0):
        """判断点是否在平台上"""
        return self.contains_x(x, margin) and self.contains_y(y, threshold)

    def to_dict(self):
        return {
            "id": self.id,
            "x_min": self.x_min,
            "x_max": self.x_max,
            "y_base": self.y_base,
            "points": [[p[0], p[1]] for p in self.points]
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            platform_id=d["id"],
            x_min=d["x_min"],
            x_max=d["x_max"],
            y_base=d["y_base"],
            points=[tuple(p) for p in d.get("points", [])]
        )

    def __repr__(self):
        return f"Platform(id={self.id}, x=[{self.x_min:.0f},{self.x_max:.0f}], y={self.y_base:.0f})"


class PlatformManager:
    """平台管理器"""

    def __init__(self, save_path="data/platforms.json"):
        self.save_path = save_path
        self.platforms = []
        self._recording = False
        self._record_points = []
        self._record_start_time = None

        # 确保目录存在
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        # 加载已有数据
        self.load()

    # ========== 录制功能 ==========

    def start_recording(self):
        """开始录制平台路线"""
        self._recording = True
        self._record_points = []
        self._record_start_time = time.time()
        print("[平台录制] 开始记录，请在目标平台上走动...")

    def record_point(self, x, y):
        """
        记录一个人物坐标点（在录制模式下持续调用）

        Args:
            x, y: 人物中心点坐标
        """
        if self._recording:
            self._record_points.append((x, y))

    def stop_recording(self):
        """
        停止录制并处理数据
        对记录的坐标点做聚类，提取平台

        Returns:
            list[Platform]: 新提取的平台列表
        """
        if not self._recording:
            return []

        self._recording = False
        duration = time.time() - self._record_start_time
        print(f"[平台录制] 停止，共记录 {len(self._record_points)} 个点，耗时 {duration:.1f}s")

        new_platforms = self._extract_platforms(self._record_points)

        # 添加到已有平台（重新编号）
        start_id = len(self.platforms)
        for i, p in enumerate(new_platforms):
            p.id = start_id + i
            self.platforms.append(p)

        self.save()
        print(f"[平台录制] 提取到 {len(new_platforms)} 个平台，总计 {len(self.platforms)} 个")
        return new_platforms

    def _extract_platforms(self, points):
        """
        从记录的坐标点中提取平台
        策略: 按y坐标聚类，同一聚类内取x的最小最大值
        """
        if not points:
            return []

        arr = np.array(points)

        if HAS_SKLEARN and len(points) > 5:
            # 使用 DBSCAN 按 y 坐标聚类
            y_vals = arr[:, 1].reshape(-1, 1)
            clustering = DBSCAN(eps=25, min_samples=3).fit(y_vals)
            labels = clustering.labels_
        else:
            # 简单的 y 坐标分桶（无 sklearn 时的降级方案）
            y_sorted = np.sort(arr[:, 1])
            labels = np.zeros(len(arr), dtype=int)
            current_label = 0
            for i in range(1, len(arr)):
                if y_sorted[i] - y_sorted[i - 1] > 30:
                    current_label += 1
                # 找到原始索引
                orig_idx = np.where(arr[:, 1] == y_sorted[i])[0][0]
                labels[orig_idx] = current_label

        platforms = []
        unique_labels = set(labels)
        unique_labels.discard(-1)  # 噪声点

        for label in unique_labels:
            mask = labels == label
            cluster_points = arr[mask]
            if len(cluster_points) < 3:
                continue

            x_min = float(np.min(cluster_points[:, 0]))
            x_max = float(np.max(cluster_points[:, 0]))
            y_base = float(np.median(cluster_points[:, 1]))

            platform = Platform(
                platform_id=0,
                x_min=x_min,
                x_max=x_max,
                y_base=y_base,
                points=[tuple(p) for p in cluster_points]
            )
            platforms.append(platform)

        # 按 y_base 排序（从上到下）
        platforms.sort(key=lambda p: p.y_base)
        return platforms

    # ========== 查询功能 ==========

    def find_platform_at(self, x, y, threshold=30):
        """
        查找包含指定点的平台

        Returns:
            Platform | None
        """
        for p in self.platforms:
            if p.contains_point(x, y, threshold):
                return p
        return None

    def is_monster_on_recorded_platform(self, monster_pos, threshold=30):
        """
        判断怪物是否在已记录的平台上
        用于过滤：只打已记录平台上的怪
        """
        x, y = monster_pos
        return self.find_platform_at(x, y, threshold) is not None

    def filter_monsters_on_platforms(self, monsters, threshold=30):
        """
        过滤出在已记录平台上的怪物

        Args:
            monsters: [{"pos": (x,y), ...}, ...]

        Returns:
            list: 只包含在已记录平台上的怪物
        """
        return [
            m for m in monsters
            if self.is_monster_on_recorded_platform(m["pos"], threshold)
        ]

    def get_platform_by_id(self, platform_id):
        for p in self.platforms:
            if p.id == platform_id:
                return p
        return None

    # ========== 保存/加载 ==========

    def save(self):
        """保存平台数据到 JSON"""
        data = {
            "platforms": [p.to_dict() for p in self.platforms],
            "count": len(self.platforms)
        }
        with open(self.save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self):
        """从 JSON 加载平台数据"""
        if not os.path.exists(self.save_path):
            self.platforms = []
            return

        try:
            with open(self.save_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.platforms = [Platform.from_dict(p) for p in data.get("platforms", [])]
            print(f"[平台管理] 加载了 {len(self.platforms)} 个平台")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[平台管理] 加载失败: {e}")
            self.platforms = []

    def clear(self):
        """清除所有平台数据"""
        self.platforms = []
        self.save()

    def remove_platform(self, platform_id):
        """删除指定平台"""
        self.platforms = [p for p in self.platforms if p.id != platform_id]
        # 重新编号
        for i, p in enumerate(self.platforms):
            p.id = i
        self.save()

    @property
    def is_recording(self):
        return self._recording

    @property
    def record_point_count(self):
        return len(self._record_points)
