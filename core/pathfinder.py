"""
路径选择模块
在平台之间切换时，科学地选择到达方式:
  方式1: 跳或瞬移（适合垂直差小、水平距离近的情况）
  方式2: 爬梯子（适合垂直差大、有梯子连接的情况）

选择策略:
  1. 计算目标平台与当前平台的垂直差 Δy
  2. 如果 Δy <= 跳跃高度阈值 → 优先跳/瞬移
  3. 如果 Δy > 阈值，且有梯子连接两个平台 → 爬梯子
  4. 比较两种方式的预估耗时，选更优的
"""
from enum import Enum
from utils.geometry import distance


class TravelMethod(Enum):
    JUMP = "jump"           # 跳跃到达
    TELEPORT = "teleport"   # 瞬移到达
    LADDER = "ladder"       # 爬梯子到达
    UNREACHABLE = "unreachable"  # 无法到达


class PathPlan:
    """路径规划结果"""
    def __init__(self, method, target_platform=None, ladder=None,
                 estimated_time=0.0, reason=""):
        self.method = method
        self.target_platform = target_platform
        self.ladder = ladder
        self.estimated_time = estimated_time
        self.reason = reason

    def __repr__(self):
        return (f"PathPlan(method={self.method.value}, "
                f"time={self.estimated_time:.2f}s, reason={self.reason})")


class PathFinder:
    """路径选择器"""

    def __init__(self, platform_manager, ladder_manager,
                 jump_height_threshold=120,
                 prefer_ladder_height=200,
                 ladder_climb_time_per_100px=1.0,
                 jump_time=0.8,
                 teleport_time=0.5):
        """
        Args:
            platform_manager: PlatformManager 实例
            ladder_manager: LadderManager 实例
            jump_height_threshold: 跳跃能达到的最大垂直差（像素）
            prefer_ladder_height: 超过此高度优先考虑梯子
            ladder_climb_time_per_100px: 每爬100像素需要的时间（秒）
            jump_time: 一次跳跃的预估时间
            teleport_time: 一次瞬移的预估时间
        """
        self.pm = platform_manager
        self.lm = ladder_manager
        self.jump_height_threshold = jump_height_threshold
        self.prefer_ladder_height = prefer_ladder_height
        self.ladder_climb_time_per_100px = ladder_climb_time_per_100px
        self.jump_time = jump_time
        self.teleport_time = teleport_time

    def plan_to_platform(self, player_pos, target_platform, has_teleport=True):
        """
        规划从当前位置到目标平台的路径

        Args:
            player_pos: (x, y) 玩家当前位置
            target_platform: Platform 目标平台
            has_teleport: 是否有瞬移技能

        Returns:
            PathPlan
        """
        px, py = player_pos
        dy = abs(target_platform.y_base - py)
        dx = abs(target_platform.x_min + (target_platform.x_max - target_platform.x_min) / 2 - px)

        # 方案1: 跳/瞬移
        jump_plan = self._evaluate_jump(player_pos, target_platform, has_teleport)

        # 方案2: 爬梯子
        ladder_plan = self._evaluate_ladder(player_pos, target_platform)

        # 比较选择
        candidates = []
        if jump_plan:
            candidates.append(jump_plan)
        if ladder_plan:
            candidates.append(ladder_plan)

        if not candidates:
            return PathPlan(
                method=TravelMethod.UNREACHABLE,
                target_platform=target_platform,
                reason="无法到达目标平台"
            )

        # 选预估耗时最短的
        best = min(candidates, key=lambda p: p.estimated_time)
        return best

    def _evaluate_jump(self, player_pos, target_platform, has_teleport):
        """评估跳跃/瞬移方案"""
        px, py = player_pos
        dy = abs(target_platform.y_base - py)

        if dy > self.jump_height_threshold:
            return None  # 跳不上去

        # 计算需要的水平移动时间（简化：假设移动速度5px/帧，30fps）
        target_x = (target_platform.x_min + target_platform.x_max) / 2
        dx = abs(target_x - px)
        move_time = dx / (5 * 30)  # 简化估算

        if has_teleport and dy <= self.jump_height_threshold:
            total_time = move_time + self.teleport_time
            return PathPlan(
                method=TravelMethod.TELEPORT,
                target_platform=target_platform,
                estimated_time=total_time,
                reason=f"瞬移可达，垂直差={dy:.0f}px，预估{total_time:.2f}s"
            )
        else:
            total_time = move_time + self.jump_time
            return PathPlan(
                method=TravelMethod.JUMP,
                target_platform=target_platform,
                estimated_time=total_time,
                reason=f"跳跃可达，垂直差={dy:.0f}px，预估{total_time:.2f}s"
            )

    def _evaluate_ladder(self, player_pos, target_platform):
        """评估爬梯子方案"""
        px, py = player_pos

        # 查找连接当前平台和目标平台的梯子
        current_platform = self.pm.find_platform_at(px, py)
        if current_platform is None:
            # 尝试找最近的梯子
            nearest_ladder = self.lm.find_nearest_ladder(px, py)
            if nearest_ladder is None:
                return None
            ladder = nearest_ladder
        else:
            # 查找连接两个平台的梯子
            top_y = min(current_platform.y_base, target_platform.y_base)
            bottom_y = max(current_platform.y_base, target_platform.y_base)
            ladder = self.lm.find_ladder_between_platforms(top_y, bottom_y)
            if ladder is None:
                # 没有直接连接的梯子，找最近的
                ladder = self.lm.find_nearest_ladder(px, py)
                if ladder is None:
                    return None

        # 计算到梯子的水平移动时间
        move_to_ladder_time = abs(ladder.x - px) / (5 * 30)

        # 计算爬梯子时间
        climb_height = abs(target_platform.y_base - ladder.center_y)
        climb_time = (climb_height / 100) * self.ladder_climb_time_per_100px

        total_time = move_to_ladder_time + climb_time

        return PathPlan(
            method=TravelMethod.LADDER,
            target_platform=target_platform,
            ladder=ladder,
            estimated_time=total_time,
            reason=f"爬梯子，高度={climb_height:.0f}px，预估{total_time:.2f}s"
        )

    def find_best_target_platform(self, player_pos, monsters_on_platforms):
        """
        根据怪物分布，找到最优的目标平台

        Args:
            player_pos: (x, y)
            monsters_on_platforms: {platform_id: [monster, ...]} 各平台上的怪物

        Returns:
            (Platform, PathPlan) | (None, None)
        """
        if not monsters_on_platforms:
            return None, None

        best_platform = None
        best_plan = None
        best_score = float('inf')

        for platform_id, monsters in monsters_on_platforms.items():
            platform = self.pm.get_platform_by_id(platform_id)
            if platform is None:
                continue

            plan = self.plan_to_platform(player_pos, platform)
            if plan.method == TravelMethod.UNREACHABLE:
                continue

            # 评分: 到达时间 / 怪物数量（怪物多的平台更有价值）
            score = plan.estimated_time / max(len(monsters), 1)

            if score < best_score:
                best_score = score
                best_platform = platform
                best_plan = plan

        return best_platform, best_plan
