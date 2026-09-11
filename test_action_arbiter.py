# -*- coding: utf-8 -*-
"""
动作权仲裁器 + 世界快照 离线单测（架构第1块地基）。
纯Python、不依赖cv2/numpy/游戏： python test_action_arbiter.py
覆盖：范围双阈值迟滞、边界最高抢占、巡路/打怪互斥、切换先松旧权、动作线程自查、快照原子替换与过期。
"""
import time
from core.action_arbiter import ActionMode, ActionArbiter, RangeGate
from core.world_snapshot import WorldSnapshot, SnapshotStore

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s" % name)


print("== 1. RangeGate 双阈值迟滞 (R=300, 靠近50→250进, 回差25→325出) ==")
g = RangeGate(enter_keep=50, exit_back=25)
check("远处300还不该开打(未到250)", g.update(300, True, 300) is False)
check("走到250进入开打", g.update(250, True, 300) is True)
check("打后被推到300仍维持(不抖)", g.update(300, True, 300) is True)
check("打后到325仍维持(回差带内)", g.update(325, True, 300) is True)
check("退到326才回巡路", g.update(326, True, 300) is False)
check("再靠近到251仍不打(迟滞,要<=250)", g.update(251, True, 300) is False)
check("Y不在带,即便X够近也不进", RangeGate().update(10, False, 300) is False)
g2 = RangeGate()
g2.update(10, True, 300)
check("打之中Y掉出带立即退出", g2.update(10, False, 300) is False)
check("小射程下限保护不报错", RangeGate(50, 25).update(1, True, 30) is True)

print("== 2. ActionArbiter 巡路/打怪互斥、没目标归巡路 ==")
log = []
arb = ActionArbiter(on_leave=lambda old: log.append("leave:%s" % old),
                    on_enter=lambda new: log.append("enter:%s" % new))
owner, ev = arb.update(has_target=False, in_range=None)
check("没目标→ROUTE", owner == ActionMode.ROUTE)
owner, ev = arb.update(has_target=True, in_range=False)
check("有目标但不在范围→ROUTE", owner == ActionMode.ROUTE and not ev)  # 同为route无切换
owner, ev = arb.update(has_target=True, in_range=True)
check("进范围→FIGHT 且先leave route再enter fight",
      owner == ActionMode.FIGHT and log[-2:] == ["leave:route", "enter:fight"])
check("打怪线程allowed(fight)=True, 巡路allowed(route)=False",
      arb.allowed(ActionMode.FIGHT) and not arb.allowed(ActionMode.ROUTE))
owner, ev = arb.update(has_target=True, in_range=True)
check("状态不变不产生切换事件", not ev)

print("== 3. 边界最高优先抢占, 撤巡路/打怪; 解除后按范围恢复 ==")
owner, ev = arb.update(bound=True, has_target=True, in_range=True)
check("边界抢占→BOUND(即便在范围内也撤打怪)", owner == ActionMode.BOUND
      and log[-2:] == ["leave:fight", "enter:bound"])
check("BOUND时打怪/巡路都不allowed",
      not arb.allowed(ActionMode.FIGHT) and not arb.allowed(ActionMode.ROUTE))
owner, ev = arb.update(bound=False, has_target=True, in_range=True)
check("边界解除、仍在范围→恢复FIGHT", owner == ActionMode.FIGHT)
owner, ev = arb.update(bound=False, has_target=True, in_range=False)
check("边界解除、不在范围→ROUTE", owner == ActionMode.ROUTE)

print("== 4. 信息不足→IDLE, 所有动作线程停手 ==")
owner, _ = arb.update(has_target=True, in_range=None)
check("in_range未知→IDLE", owner == ActionMode.IDLE)
check("IDLE时巡路/打怪都不allowed",
      not arb.allowed(ActionMode.ROUTE) and not arb.allowed(ActionMode.FIGHT))
owner, _ = arb.update(has_target=True, in_range=True)
owner, ev = arb.force_reset()
check("force_reset回IDLE并触发旧权松键", owner == ActionMode.IDLE and log[-1] == "leave:fight")

print("== 5. 随机序列下任意时刻只有一个动作权 ==")
import random
random.seed(7)
a2 = ActionArbiter()
ok = True
for _ in range(20000):
    o, _ = a2.update(bound=random.random() < 0.1,
                     has_target=random.random() < 0.9,
                     in_range=random.choice([True, False, None]))
    if o not in (ActionMode.IDLE, ActionMode.ROUTE, ActionMode.FIGHT, ActionMode.BOUND, ActionMode.POTION):
        ok = False
        break
check("2万次仲裁owner始终为单一合法值", ok)

print("== 6. SnapshotStore 原子替换 + 过期判定 ==")
store = SnapshotStore()
check("未发布=stale", store.is_stale(0.1) and store.latest() is None)
s1 = WorldSnapshot(t=time.time() - 1.0, player_screen=(10, 20), monsters=[(1, 2, 3, 4, 9)])
store.publish(s1)
check("发布后latest取回同一帧", store.latest() is s1 and store.latest().player_screen == (10, 20))
check("1秒帧、阈值0.5s=过期", store.is_stale(0.5) and not store.is_stale(2.0))
s2 = WorldSnapshot(t=time.time(), player_screen=(30, 40))
store.publish(s2)
check("新帧原子替换旧帧", store.latest() is s2 and store.latest().player_screen == (30, 40))

print("\n==== 结果: %d 通过, %d 失败 ====" % (PASS, FAIL))
raise SystemExit(1 if FAIL else 0)
