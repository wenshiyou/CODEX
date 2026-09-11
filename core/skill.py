"""
技能系统模块（四大类）
  1. 攻击技能 attack  - 自定义按键、自定义频率(冷却)、自定义距离(攻击范围)
  2. BUFF技能 buff    - 自定义按键、自定义冷却时间
  3. 跳跃技能 jump    - 自定义按键
  4. 瞬移技能 teleport - 自定义按键、自定义距离(瞬移范围)

每个技能可配置: 名称、按键、冷却/频率、距离、类型、是否启用、优先级
"""
import time
from enum import Enum


class SkillType(Enum):
    ATTACK = "attack"       # 攻击技能
    BUFF = "buff"           # BUFF技能
    JUMP = "jump"           # 跳跃技能
    TELEPORT = "teleport"   # 瞬移技能


class Skill:
    """单个技能"""

    def __init__(self, name, key, skill_type, cooldown=0.5,
                 distance=150, enabled=True, priority=0):
        """
        Args:
            name: 技能名称
            key: 按键
            skill_type: SkillType 或字符串
            cooldown: 冷却时间/频率（秒），攻击技能为攻击间隔，BUFF为持续时间
            distance: 技能距离（像素），攻击技能为攻击范围，瞬移为瞬移距离
            enabled: 是否启用
            priority: 优先级（数字越小越优先，攻击技能按此顺序释放）
        """
        self.name = name
        self.key = key
        self.type = SkillType(skill_type)
        self.cooldown = cooldown
        self.distance = distance
        self.enabled = enabled
        self.priority = priority
        self.last_used_time = 0
        self.use_count = 0

    def is_ready(self):
        """技能是否就绪（冷却结束）"""
        if not self.enabled:
            return False
        elapsed = time.time() - self.last_used_time
        return elapsed >= self.cooldown

    def use(self, controller):
        """使用技能"""
        if not self.is_ready():
            return False
        controller.use_skill(self.key)
        self.last_used_time = time.time()
        self.use_count += 1
        return True

    def get_remaining_cooldown(self):
        """获取剩余冷却时间"""
        if not self.enabled:
            return 0
        elapsed = time.time() - self.last_used_time
        return max(0, self.cooldown - elapsed)

    def to_dict(self):
        return {
            "name": self.name,
            "key": self.key,
            "type": self.type.value,
            "cooldown": self.cooldown,
            "distance": self.distance,
            "enabled": self.enabled,
            "priority": self.priority
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d["name"],
            key=d["key"],
            skill_type=d["type"],
            cooldown=d.get("cooldown", 0.5),
            distance=d.get("distance", 150),
            enabled=d.get("enabled", True),
            priority=d.get("priority", 0)
        )

    def __repr__(self):
        return (f"Skill({self.name}, type={self.type.value}, "
                f"key={self.key}, cd={self.cooldown}s, dist={self.distance}px)")


class SkillManager:
    """技能管理器"""

    def __init__(self, controller):
        self.controller = controller
        self.skills = []

    def load_from_config(self, skills_config):
        """从配置加载技能列表"""
        self.skills = []
        for s in skills_config:
            skill = Skill.from_dict(s)
            self.skills.append(skill)
        # 按优先级排序
        self.skills.sort(key=lambda s: s.priority)
        print(f"[技能管理] 加载了 {len(self.skills)} 个技能")
        for s in self.skills:
            print(f"  - {s}")

    def add_skill(self, name, key, skill_type, cooldown=0.5,
                  distance=150, enabled=True, priority=0):
        """添加一个技能"""
        skill = Skill(name, key, skill_type, cooldown, distance, enabled, priority)
        self.skills.append(skill)
        self.skills.sort(key=lambda s: s.priority)
        return skill

    def remove_skill(self, name):
        """移除技能"""
        self.skills = [s for s in self.skills if s.name != name]

    def get_skill(self, name):
        for s in self.skills:
            if s.name == name:
                return s
        return None

    def get_skills_by_type(self, skill_type):
        """按类型获取技能列表"""
        st = SkillType(skill_type)
        return [s for s in self.skills if s.type == st and s.enabled]

    # ========== 攻击技能 ==========

    def get_attack_skills(self):
        """获取所有启用的攻击技能（按优先级排序）"""
        attacks = [s for s in self.skills if s.type == SkillType.ATTACK and s.enabled]
        attacks.sort(key=lambda s: s.priority)
        return attacks

    def get_max_attack_range(self):
        """
        获取所有攻击技能中的最大距离
        用于决策模块判断怪物是否在攻击范围内
        """
        attacks = self.get_attack_skills()
        if not attacks:
            return 150  # 默认值
        return max(s.distance for s in attacks)

    def do_attacks(self, monster_distance=None):
        """
        执行所有就绪的攻击技能
        按优先级顺序释放，每个技能检查冷却

        Args:
            monster_distance: 当前目标怪物的水平距离，用于判断哪些技能能打到

        Returns:
            int: 成功释放的技能数量
        """
        attacks = self.get_attack_skills()
        if not attacks:
            return 0

        used_count = 0
        for skill in attacks:
            # 如果指定了怪物距离，只释放在范围内的技能
            if monster_distance is not None and monster_distance > skill.distance:
                continue
            if skill.is_ready():
                if skill.use(self.controller):
                    used_count += 1
                    time.sleep(0.05)  # 技能间短暂间隔

        return used_count

    # ========== BUFF技能 ==========

    def get_buff_skills(self):
        """获取所有启用的BUFF技能"""
        return [s for s in self.skills if s.type == SkillType.BUFF and s.enabled]

    def check_and_use_buffs(self):
        """
        检查并自动释放到期的BUFF
        返回释放的BUFF名称列表
        """
        used = []
        for skill in self.get_buff_skills():
            if skill.is_ready():
                if skill.use(self.controller):
                    used.append(skill.name)
                    time.sleep(0.1)
        return used

    # ========== 跳跃技能 ==========

    def get_jump_skills(self):
        """获取所有启用的跳跃技能"""
        return [s for s in self.skills if s.type == SkillType.JUMP and s.enabled]

    def do_jump(self):
        """
        执行跳跃（使用第一个就绪的跳跃技能）
        返回是否成功
        """
        for skill in self.get_jump_skills():
            if skill.is_ready():
                return skill.use(self.controller)
        # 没有配置跳跃技能，返回False
        return False

    # ========== 瞬移技能 ==========

    def get_teleport_skills(self):
        """获取所有启用的瞬移技能"""
        return [s for s in self.skills if s.type == SkillType.TELEPORT and s.enabled]

    def get_max_teleport_distance(self):
        """获取最大瞬移距离"""
        teles = self.get_teleport_skills()
        if not teles:
            return 0
        return max(s.distance for s in teles)

    def do_teleport(self):
        """
        执行瞬移（使用第一个就绪的瞬移技能）
        返回是否成功
        """
        for skill in self.get_teleport_skills():
            if skill.is_ready():
                return skill.use(self.controller)
        return False

    # ========== 导出 ==========

    def to_config_list(self):
        """导出为配置列表（用于保存）"""
        return [s.to_dict() for s in self.skills]
