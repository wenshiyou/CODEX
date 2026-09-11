# -*- coding: utf-8 -*-
"""
动作权仲裁器 + 技能范围双阈值迟滞（多线程统一管控架构·第1块地基，用户2026-09-12定稿）

设计目标（对应架构定稿）：
- 真正会"动手"的线程只有两个：巡路(ROUTE，移动/上梯/瞬移/归位) 与 打怪(FIGHT，原地普攻/原地跳打)，二者同一时刻只生效一个。
- 边界拉回(BOUND)优先级最高：激活期间巡路+打怪全部停手；加药(POTION)本版与攻击并行、默认不参与抢占，仅预留。
- 分界线 = 锁定怪"在不在技能范围"：在范围内给打怪，不在范围/没目标给巡路；范围判定走双阈值迟滞(RangeGate)，
  即"走到 R-靠近余量 才开打、退到 R+回差 才回巡路"，根治射程边界打一下走一下的抖动（用户定：靠近50、回差25，均可配）。
- 任何时刻只有一个动作权 owner；切换动作权时【先让旧 owner 全松键，再让新 owner 动手】(on_leave/on_enter 回调，
  主程序在回调里统一收键)，从根上消灭两套方向键相抵。
- 每个动作线程每轮用 allowed(role) 自查"现在还归不归我管"，不归立刻松键 return，做双保险。

本模块【纯逻辑】：不 import cv2/numpy/不发键、不碰屏幕，可离线用合成数据单测（见 test_action_arbiter.py）。
主程序后续只负责：识别线程喂数据 → RangeGate 算 in_range → ActionArbiter.update 定 owner → 在回调里收/放键。
"""
import threading


class ActionMode(object):
    """动作权取值。字符串常量，便于日志直读。"""
    IDLE = "idle"      # 信息不足(如快照过期/还没锁怪且in_range未知)：所有动作线程停手，宁停不乱按
    ROUTE = "route"    # 巡路：移动/上下梯子/瞬移/掉台归位，把人送进开打距离
    FIGHT = "fight"    # 打怪：范围内原地普攻或原地跳打(攻击前短按方向定朝向)，不做长距离找人
    BOUND = "bound"    # 边界拉回：最高优先独占，期间巡路/打怪全停
    POTION = "potion"  # 加药：预留(本版加药与攻击并行，默认不抢占)


# 优先级数值越大越优先；ROUTE/FIGHT 同档互斥(由范围决定)，不互相抢占
_PRIORITY = {ActionMode.IDLE: 0, ActionMode.ROUTE: 1, ActionMode.FIGHT: 1,
             ActionMode.POTION: 2, ActionMode.BOUND: 3}


class RangeGate(object):
    """技能范围双阈值迟滞门（用户2026-09-12定稿）。

    enter_keep：开打靠近余量——巡路要走到 d <= R-enter_keep 才交打怪（例：R=300 时走到250再打，贴够近不空打）。
    exit_back：回差缓冲——已在打怪时，要 d >  R+exit_back 才交回巡路（例：退到325才回巡路）；
               [R-keep, R+back] 之间维持现状，不抖。数值全部可配，不写死；对小射程做下限保护。
    只判 X 距离迟滞；Y 必须落在方向Y带内(y_ok)才允许在打怪态，Y不带立即退出（Y抖动小，不另设迟滞）。
    """

    def __init__(self, enter_keep=50, exit_back=25):
        self.enter_keep = int(enter_keep)
        self.exit_back = int(exit_back)
        self.in_fight = False

    def reset(self):
        self.in_fight = False

    def update(self, dx, y_ok, skill_range):
        """每帧喂入：|人-锁怪| X距离dx、Y是否在带y_ok、面板技能射程skill_range；返回当前是否应处于打怪态。"""
        r = max(1, int(skill_range))
        enter_d = max(1, r - self.enter_keep)   # 进入开打距离(下限保护,不会因小射程减成<=0)
        exit_d = r + self.exit_back             # 退回巡路距离
        d = abs(int(dx))
        if self.in_fight:
            # 已在打：维持，除非退出超界 或 Y不在带
            if d > exit_d or not y_ok:
                self.in_fight = False
        else:
            # 未在打：要足够近 且 Y在带 才进入
            if d <= enter_d and y_ok:
                self.in_fight = True
        return self.in_fight


class ActionArbiter(object):
    """统一动作权仲裁器（线程安全）。

    用法：协调者每轮调用 update(...) 得到当前 owner 与本轮切换事件；on_leave/on_enter 回调由主程序注入，
    分别用于"旧权全松键""新权起步"。动作线程执行前用 allowed(自己) 自查。
    """

    def __init__(self, on_leave=None, on_enter=None):
        self._lock = threading.RLock()
        self.owner = ActionMode.IDLE
        self._on_leave = on_leave   # 回调 fn(old_mode)：旧 owner 交权，主程序在此松开它按的全部键
        self._on_enter = on_enter   # 回调 fn(new_mode)：新 owner 获权起步（一般无需动作，留口）
        self.last_switch = None     # (prev, new) 最近一次切换，便于日志/排查

    def _switch(self, desired):
        """实际切换（调用方持锁）。状态不变则无事件；变则先 leave 旧、再 enter 新，返回事件列表。"""
        events = []
        if desired == self.owner:
            return events
        old = self.owner
        if old != ActionMode.IDLE and self._on_leave:
            self._on_leave(old)         # ★先让旧权全松键
        events.append(("leave", old))
        self.owner = desired
        if desired != ActionMode.IDLE and self._on_enter:
            self._on_enter(desired)
        events.append(("enter", desired))
        self.last_switch = (old, desired)
        return events

    def update(self, bound=False, has_target=True, in_range=None, potion=False):
        """每轮仲裁，返回 (owner, events)。
        bound      : 边界拉回是否激活（最高优先，True 即独占）
        has_target : 当前是否有巡路锁定的目标怪（没目标→巡路去找，绝不停在原地空等/空打）
        in_range   : 锁定怪是否已进技能范围（True 打怪 / False 巡路靠近 / None 信息不足→IDLE停手）
        potion     : 加药是否需独占（本版并行，默认 False；预留）
        """
        with self._lock:
            if bound:
                desired = ActionMode.BOUND
            elif potion:
                desired = ActionMode.POTION
            elif not has_target:
                desired = ActionMode.ROUTE
            elif in_range is True:
                desired = ActionMode.FIGHT
            elif in_range is False:
                desired = ActionMode.ROUTE
            else:
                desired = ActionMode.IDLE
            events = self._switch(desired)   # 先切换(内部更新self.owner)
            return self.owner, events       # 再返回切换后的当前owner

    def allowed(self, role):
        """动作线程自查：现在是否轮到自己发键。"""
        with self._lock:
            return self.owner == role

    @property
    def priority(self):
        return _PRIORITY.get(self.owner, 0)

    def force_reset(self):
        """全局兜底硬清零（看门狗总复位用）：回到 IDLE 并触发旧权松键。"""
        with self._lock:
            events = self._switch(ActionMode.IDLE)
            return self.owner, events
