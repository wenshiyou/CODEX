"""
梯子记录与管理模块
功能:
  1. 录制模式: 人物爬梯子时记录梯子的位置和上下端点
  2. 保存/加载梯子数据到 JSON
  3. 提供梯子信息给路径选择模块（决定跳还是爬）
"""
import json
import os
import time


class Ladder:
    """单个梯子的数据结构"""
    def __init__(self, ladder_id, x, y_top, y_bottom):
        self.id = ladder_id
        self.x = x              # 梯子的x坐标（水平位置）
        self.y_top = y_top      # 梯子顶端y坐标
        self.y_bottom = y_bottom  # 梯子底端y坐标

    @property
    def height(self):
        return abs(self.y_bottom - self.y_top)

    @property
    def center_y(self):
        return (self.y_top + self.y_bottom) / 2

    def is_near_x(self, x, threshold=40):
        """判断x坐标是否在梯子水平附近"""
        return abs(x - self.x) <= threshold

    def connects_platforms(self, top_y, bottom_y, threshold=30):
        """判断梯子是否连接两个平台"""
        return (abs(self.y_top - top_y) <= threshold and
                abs(self.y_bottom - bottom_y) <= threshold)

    def to_dict(self):
        return {
            "id": self.id,
            "x": self.x,
            "y_top": self.y_top,
            "y_bottom": self.y_bottom
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            ladder_id=d["id"],
            x=d["x"],
            y_top=d["y_top"],
            y_bottom=d["y_bottom"]
        )

    def __repr__(self):
        return f"Ladder(id={self.id}, x={self.x:.0f}, y=[{self.y_top:.0f},{self.y_bottom:.0f}])"


class LadderManager:
    """梯子管理器"""

    def __init__(self, save_path="data/ladders.json"):
        self.save_path = save_path
        self.ladders = []
        self._recording = False
        self._record_points = []
        self._record_start_time = None

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        self.load()

    # ========== 录制功能 ==========

    def start_recording(self):
        """开始录制梯子位置"""
        self._recording = True
        self._record_points = []
        self._record_start_time = time.time()
        print("[梯子录制] 开始记录，请爬一遍目标梯子...")

    def record_point(self, x, y):
        """记录一个人物坐标点（爬梯子时持续调用）"""
        if self._recording:
            self._record_points.append((x, y))

    def stop_recording(self):
        """
        停止录制并提取梯子
        从记录的点中取x的中位数作为梯子x，y的最小最大值作为上下端

        Returns:
            list[Ladder]: 新提取的梯子列表
        """
        if not self._recording:
            return []

        self._recording = False
        duration = time.time() - self._record_start_time
        print(f"[梯子录制] 停止，共记录 {len(self._record_points)} 个点，耗时 {duration:.1f}s")

        new_ladders = self._extract_ladders(self._record_points)

        start_id = len(self.ladders)
        for i, ladder in enumerate(new_ladders):
            ladder.id = start_id + i
            self.ladders.append(ladder)

        self.save()
        print(f"[梯子录制] 提取到 {len(new_ladders)} 个梯子，总计 {len(self.ladders)} 个")
        return new_ladders

    def _extract_ladders(self, points):
        """从记录点中提取梯子"""
        if not points:
            return []

        # 简单策略: 一次录制只记录一个梯子
        # x取中位数，y取最小最大值
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]

        x_median = sorted(xs)[len(xs) // 2]
        y_top = min(ys)
        y_bottom = max(ys)

        # 确保 y_top < y_bottom（图像坐标y向下增大）
        if y_top > y_bottom:
            y_top, y_bottom = y_bottom, y_top

        ladder = Ladder(
            ladder_id=0,
            x=x_median,
            y_top=y_top,
            y_bottom=y_bottom
        )
        return [ladder]

    # ========== 查询功能 ==========

    def find_nearest_ladder(self, x, y):
        """
        查找离指定点最近的梯子

        Returns:
            Ladder | None
        """
        if not self.ladders:
            return None

        def dist(ladder):
            return abs(x - ladder.x) + abs(y - ladder.center_y)

        return min(self.ladders, key=dist)

    def find_ladder_between_platforms(self, top_y, bottom_y, threshold=30):
        """
        查找连接两个平台的梯子

        Args:
            top_y: 上方平台的y
            bottom_y: 下方平台的y
            threshold: y坐标容差

        Returns:
            Ladder | None
        """
        for ladder in self.ladders:
            if ladder.connects_platforms(top_y, bottom_y, threshold):
                return ladder
        return None

    def get_ladder_by_id(self, ladder_id):
        for ladder in self.ladders:
            if ladder.id == ladder_id:
                return ladder
        return None

    # ========== 保存/加载 ==========

    def save(self):
        data = {
            "ladders": [l.to_dict() for l in self.ladders],
            "count": len(self.ladders)
        }
        with open(self.save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self):
        if not os.path.exists(self.save_path):
            self.ladders = []
            return

        try:
            with open(self.save_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.ladders = [Ladder.from_dict(l) for l in data.get("ladders", [])]
            print(f"[梯子管理] 加载了 {len(self.ladders)} 个梯子")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[梯子管理] 加载失败: {e}")
            self.ladders = []

    def clear(self):
        self.ladders = []
        self.save()

    def remove_ladder(self, ladder_id):
        self.ladders = [l for l in self.ladders if l.id != ladder_id]
        for i, l in enumerate(self.ladders):
            l.id = i
        self.save()

    @property
    def is_recording(self):
        return self._recording

    @property
    def record_point_count(self):
        return len(self._record_points)
