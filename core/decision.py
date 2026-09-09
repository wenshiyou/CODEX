"""
攻击决策模块
根据人物和怪物位置，按优先级决定下一步动作:
  优先级1: 左右最近的怪（同平台 + 攻击范围内）→ 直接攻击
  优先级2: 同平台远距离怪（同平台 + 超出攻击范围）→ 向怪靠近
  优先级3: 上下平台的怪（不同平台）→ 需要跳/瞬移或爬梯子

攻击范围由技能管理器中所有攻击技能的最大距离决定（职业不同技能范围不同）
"""
from enum import Enum


class ActionType(Enum):
    ATTACK = "attack"           # 攻击
    MOVE_LEFT = "move_left"     # 向左移动
    MOVE_RIGHT = "move_right"   # 向右移动
    JUMP = "jump"               # 跳跃
    TELEPORT = "teleport"       # 瞬移
    CLIMB_UP = "climb_up"       # 向上爬梯子
    CLIMB_DOWN = "climb_down"   # 向下爬梯子
    MOVE_TO_LADDER = "move_to_ladder"  # 移动到梯子位置
    IDLE = "idle"               # 无动作
    SEARCH = "search"           # 搜索怪物（来回走动）


class CombatDecision:
    def __init__(self, platform_y_threshold=30, move_step_duration=0.1,
                 skill_manager=None):
        """
        Args:
            platform_y_threshold: 判断同一平台的垂直像素阈值
            move_step_duration: 每次移动按键持续时间
            skill_manager: SkillManager 实例，用于获取攻击范围和瞬移距离
        """
        self.platform_y_threshold = platform_y_threshold
        self.move_step_duration = move_step_duration
        self.skill_manager = skill_manager
        self._fallback_attack_range = 150

    @property
    def attack_range(self):
        """
        攻击范围 = 所有攻击技能中的最大距离
        职业不同技能范围不同，由技能配置决定
        """
        if self.skill_manager:
            return self.skill_manager.get_max_attack_range()
        return self._fallback_attack_range

    @property
    def teleport_range(self):
        """瞬移距离 = 所有瞬移技能中的最大距离"""
        if self.skill_manager:
            return self.skill_manager.get_max_teleport_distance()
        return 0

    def set_skill_manager(self, skill_manager):
        self.skill_manager = skill_manager

    def decide(self, locator):
        """
        根据定位信息决定下一步动作

        Returns:
            dict: {
                "action": ActionType,
                "target": dict | None,
                "reason": str,
                "attack_range_used": float  # 本次决策使用的攻击范围
            }
        """
        if not locator.has_player():
            return {"action": ActionType.IDLE, "target": None,
                    "reason": "未检测到人物", "attack_range_used": self.attack_range}

        ar = self.attack_range

        # 优先级1: 攻击范围内的怪
        nearby = locator.find_nearby_monsters(ar)
        if nearby:
            target = nearby[0]
            return {
                "action": ActionType.ATTACK,
                "target": target,
                "reason": f"攻击范围内发现怪物，h_dist={target['h_dist']:.0f}px (范围={ar:.0f})",
                "attack_range_used": ar
            }

        # 优先级2: 同平台但距离较远的怪 → 靠近
        far_same = locator.find_same_platform_far_monsters(ar)
        if far_same:
            target = far_same[0]
            # 如果有瞬移技能且距离在瞬移范围内，优先瞬移
            if self.teleport_range > 0 and target["h_dist"] <= self.teleport_range:
                return {
                    "action": ActionType.TELEPORT,
                    "target": target,
                    "reason": f"同平台远处怪物，瞬移可达 h_dist={target['h_dist']:.0f}px",
                    "attack_range_used": ar
                }
            if target["direction"] == "left":
                action = ActionType.MOVE_LEFT
            else:
                action = ActionType.MOVE_RIGHT
            return {
                "action": action,
                "target": target,
                "reason": f"同平台远处怪物，方向={target['direction']}，h_dist={target['h_dist']:.0f}px",
                "attack_range_used": ar
            }

        # 优先级3: 其他平台的怪
        other = locator.find_other_platform_monsters()
        if other:
            target = other[0]
            return self._decide_platform_switch(locator, target)

        # 没有怪物，搜索模式
        return {
            "action": ActionType.SEARCH,
            "target": None,
            "reason": "当前视野无怪物，进入搜索模式",
            "attack_range_used": ar
        }

    def _decide_platform_switch(self, locator, target):
        """
        决定如何切换到目标平台
        结合跳跃技能、瞬移技能和梯子记录来决策
        """
        player_y = locator.player_pos[1]
        target_y = target["pos"][1]
        dy = target_y - player_y  # 正=目标在下方，负=目标在上方

        # 如果有瞬移技能且垂直差在瞬移范围内，优先瞬移
        if self.teleport_range > 0 and abs(dy) <= self.teleport_range:
            return {
                "action": ActionType.TELEPORT,
                "target": target,
                "reason": f"目标在其他平台，瞬移可达 v_dist={abs(dy):.0f}px",
                "attack_range_used": self.attack_range
            }

        # 垂直差小，先水平移动再跳
        if abs(dy) < 150:
            if target["direction"] == "left":
                return {
                    "action": ActionType.MOVE_LEFT,
                    "target": target,
                    "reason": f"目标平台 v_dist={abs(dy):.0f}px，先向左靠近后跳跃",
                    "attack_range_used": self.attack_range
                }
            else:
                return {
                    "action": ActionType.MOVE_RIGHT,
                    "target": target,
                    "reason": f"目标平台 v_dist={abs(dy):.0f}px，先向右靠近后跳跃",
                    "attack_range_used": self.attack_range
                }
        else:
            # 垂直差大，需要找梯子
            nearest_ladder = locator.get_nearest_ladder()
            if nearest_ladder:
                ladder_x = nearest_ladder["pos"][0]
                player_x = locator.player_pos[0]
                if abs(ladder_x - player_x) > 30:
                    action = ActionType.MOVE_LEFT if ladder_x < player_x else ActionType.MOVE_RIGHT
                    return {
                        "action": action,
                        "target": target,
                        "reason": f"目标平台 v_dist={abs(dy):.0f}px，移动到最近梯子",
                        "attack_range_used": self.attack_range
                    }
                else:
                    if dy < 0:
                        return {"action": ActionType.CLIMB_UP, "target": target,
                                "reason": "向上爬梯子", "attack_range_used": self.attack_range}
                    else:
                        return {"action": ActionType.CLIMB_DOWN, "target": target,
                                "reason": "向下爬梯子", "attack_range_used": self.attack_range}

        return {
            "action": ActionType.SEARCH,
            "target": target,
            "reason": "无法到达目标平台，搜索中",
            "attack_range_used": self.attack_range
        }
