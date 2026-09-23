"""
目标定位模块
从 YOLO 检测结果中提取人物、怪物位置，计算距离差，筛选目标。
"""
from utils.geometry import (
    distance, horizontal_distance, vertical_distance,
    direction, is_on_same_platform
)


class ObjectLocator:
    def __init__(self, platform_y_threshold=30):
        self.platform_y_threshold = platform_y_threshold
        self.player_pos = None       # (x, y) 人物中心点
        self.player_direction = None  # "left" / "right" / None
        self.player_confidence = 0.0  # 人物定位置信度
        self.monsters = []           # [{"pos": (x,y), "bbox": [...], "conf": float}, ...]
        self.ladders = []            # [{"pos": (x,y), "bbox": [...], ...}, ...]

    def set_player_position(self, pos, direction=None, confidence=1.0):
        """
        外部设置人物位置（模板匹配定位时调用）

        Args:
            pos: (x, y) 人物中心点
            direction: "left" / "right"
            confidence: 定位置信度
        """
        self.player_pos = pos
        self.player_direction = direction
        self.player_confidence = confidence

    def update(self, detections, include_player=True):
        """
        从检测结果更新定位信息

        Args:
            detections: YoloDetector.detect() 返回的检测结果列表
            include_player: 是否从检测结果中提取人物（False时人物位置由外部设置）
        """
        if include_player:
            self.player_pos = None
            self.player_direction = None
            self.player_confidence = 0.0
        self.monsters = []
        self.ladders = []

        for det in detections:
            cls = det["class"]
            if cls == "player" and include_player:
                if self.player_pos is None or det["confidence"] > self.player_confidence:
                    self.player_pos = det["center"]
                    self.player_confidence = det["confidence"]
            elif cls == "monster":
                self.monsters.append({
                    "pos": det["center"],
                    "bbox": det["bbox"],
                    "confidence": det["confidence"]
                })
            elif cls == "ladder":
                self.ladders.append({
                    "pos": det["center"],
                    "bbox": det["bbox"],
                    "confidence": det["confidence"]
                })

    def has_player(self):
        return self.player_pos is not None

    def get_monster_distances(self):
        """
        获取所有怪物与玩家的距离信息

        Returns:
            list[dict]: 每个怪物的距离信息，按总距离排序
            [
                {
                    "pos": (x, y),
                    "distance": float,        # 欧氏距离
                    "h_dist": float,          # 水平距离
                    "v_dist": float,          # 垂直距离
                    "direction": "left"/"right"/"same",
                    "same_platform": bool,    # 是否在同一平台
                    "bbox": [...]
                },
                ...
            ]
        """
        if not self.player_pos:
            return []

        results = []
        for m in self.monsters:
            d = distance(self.player_pos, m["pos"])
            hd = horizontal_distance(self.player_pos, m["pos"])
            vd = vertical_distance(self.player_pos, m["pos"])
            dir_ = direction(self.player_pos, m["pos"])
            same_plat = is_on_same_platform(
                self.player_pos[1], m["pos"][1], self.platform_y_threshold
            )

            results.append({
                "pos": m["pos"],
                "distance": d,
                "h_dist": hd,
                "v_dist": vd,
                "direction": dir_,
                "same_platform": same_plat,
                "bbox": m["bbox"],
                "confidence": m["confidence"]
            })

        results.sort(key=lambda x: x["distance"])
        return results

    def find_nearby_monsters(self, attack_range):
        """
        查找攻击范围内的怪物（左右最近的怪）

        优先级1: 同平台且水平距离在攻击范围内
        """
        monsters = self.get_monster_distances()
        return [
            m for m in monsters
            if m["same_platform"] and m["h_dist"] <= attack_range
        ]

    def find_same_platform_far_monsters(self, attack_range):
        """
        查找同平台但超出攻击范围的怪物（需要靠近）

        优先级2: 同平台但水平距离 > 攻击范围
        """
        monsters = self.get_monster_distances()
        return [
            m for m in monsters
            if m["same_platform"] and m["h_dist"] > attack_range
        ]

    def find_other_platform_monsters(self):
        """
        查找其他平台的怪物（需要跳/爬梯子）

        优先级3: 不在同一平台
        """
        monsters = self.get_monster_distances()
        return [m for m in monsters if not m["same_platform"]]

    def get_nearest_monster(self):
        """获取最近的怪物（不考虑平台）"""
        monsters = self.get_monster_distances()
        return monsters[0] if monsters else None

    def get_nearest_ladder(self):
        """获取最近的梯子"""
        if not self.player_pos or not self.ladders:
            return None

        nearest = min(
            self.ladders,
            key=lambda l: distance(self.player_pos, l["pos"])
        )
        return nearest
