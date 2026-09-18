# -*- coding: utf-8 -*-
"""阶段一 combat_logic 重构离线对照单测(用完即删)。
A. 机械抽取零变化:旧版(15180b5) vs 新版,在 target在位/存活/无锁选新/freeze/让位/群攻/cross粘滞 场景输出一致;
B. 有意变更单独断言新版:in/out脱检落空重选、真怪一帧判死、pick_next排除current、combat_step同帧晋升。"""
import os, sys, subprocess, importlib.util

ROOT = os.path.dirname(os.path.abspath(__file__))
OLD = os.path.join(ROOT, "_combat_logic_old.py")
data = subprocess.run(["git", "show", "15180b5:combat_logic.py"], cwd=ROOT,
                      capture_output=True).stdout
open(OLD, "wb").write(data)
print("导出旧版 combat_logic 字节数:", len(data))

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

old = load("combat_logic_old", OLD)
new = load("combat_logic_new", os.path.join(ROOT, "combat_logic.py"))

PX, PY = 500, 500
SKILL = 150
AUP, ADN = 100, 80

def box(cx, cy, w=40, h=80, s=0.9):
    return (cx - w // 2, cy - h, cx + w // 2, cy, s)

# 标准怪: in(60,同层) / out(200,同层) / cross上(60,高200) / 远X(400,高200)
M_IN    = box(560, 500)
M_OUT   = box(700, 500)
M_CROSS = box(560, 300)
M_FAR   = box(900, 300)

def S(mod, monsters, target=None, **kw):
    """统一参数调 select_combat_target"""
    tcx, tcy = target if target else (None, None)
    kw0 = dict(
        px=PX, py=PY, monsters=monsters, selected_platforms=[], skill_range=SKILL, far_range=0,
        target_cx=tcx, target_cy=tcy, target_alive=True, is_on_platform=True,
        get_monster_platform=None, probe_side=1, probe_switched=False, cur_cross=None,
        attack_y_up=AUP, attack_y_down=ADN, allow_cross=True, now=0, lock_time=0,
        freeze_lock=False, lock_tier=None, group_priority=False, group_radius=0,
        aoe_y_up=None, aoe_y_down=None, aoe_dual=False, same_platform_fn=None, metric=None)
    kw0.update(kw)
    return mod.select_combat_target(**kw0)

def sig(d):
    return (d["state"], d["target"], d.get("tier"),
            (d["group"][0], d["group"][1]) if d.get("group") else None)

fails = []
def check_same(tag, monsters, target, **kw):
    a, b = S(old, monsters, target, **kw), S(new, monsters, target, **kw)
    sa, sb = sig(a), sig(b)
    ok = sa == sb
    print(("[A 零变化] %-28s %s  old=%s new=%s" % (tag, "PASS" if ok else "FAIL", sa, sb)))
    if not ok:
        fails.append(tag)

print("\n===== A. 机械抽取:新旧零变化 =====")
# 1) in 在位存活
check_same("in在位→cast", [M_IN, M_OUT], (560, 500), lock_tier="in")
# 2) out 在位、无近身怪 → pursue
check_same("out在位无近身→pursue", [M_OUT], (700, 500), lock_tier="out")
# 3) cross 在位、无近身怪 → cross
check_same("cross在位→cross", [M_CROSS], (560, 300), lock_tier="cross")
# 4) freeze + cross 脱检 → 沿旧坐标 cross
check_same("freeze cross脱检续cross", [M_IN], (560, 300), freeze_lock=True, lock_tier="cross")
# 5) freeze + 目标已进 cand(爬到同层)
check_same("freeze 目标到同层→cast/pursue", [M_IN], (560, 500), freeze_lock=True, lock_tier="cross")
# 6) 让位:锁 out,身边刷 in 怪 → 落 pick 打 in
check_same("让位 out途中刷in→cast", [M_OUT, M_IN], (700, 500), lock_tier="out")
# 7) 让位:锁 cross,身边刷 in → cast
check_same("让位 cross途中刷in→cast", [M_CROSS, M_IN], (560, 300), lock_tier="cross")
# 8) 无锁选新:有 in 有 out 有 cross → 选 in
check_same("无锁选in", [M_OUT, M_CROSS, M_IN], None)
# 9) 无锁:只有 out → pursue
check_same("无锁只有out→pursue", [M_OUT], None)
# 10) 无锁:只有 cross → cross
check_same("无锁只有cross→cross", [M_CROSS], None)
# 11) 无锁:空表 → idle
check_same("空表→idle", [], None)
# 12) 远X(≥300)即使高也进 cand 先走近
check_same("远X高怪→cand走近", [M_FAR], None)
# 13) cross 同层同侧粘滞(cur_cross)
check_same("cross同层同侧粘滞", [box(565, 305)], (560, 300), lock_tier="cross", cur_cross=(560, 300))
# 14) 群攻:3只近身怪单向 → group
g1, g2, g3 = box(560, 500), box(590, 502), box(620, 498)
check_same("群攻3只近身→group", [g1, g2, g3], None,
           group_priority=True, group_radius=120, aoe_y_up=120, aoe_y_down=100, aoe_dual=False)
# 15) in 在位、怪框轻微抖动(±10px)仍 cast
check_same("in抖动仍cast", [box(568, 506)], (560, 500), lock_tier="in")

print("\n===== B. 有意变更:新版行为断言 =====")
# B1) in 脱检(目标不在表、表里只有一只out怪):旧续cast旧坐标,新落空pursue真实怪
GHOST = (200, 200)
do_ = S(old, [M_OUT], GHOST, lock_tier="in")
dn = S(new, [M_OUT], GHOST, lock_tier="in")
b1 = (do_["state"] == "cast" and do_["target"] == GHOST) and (dn["state"] == "pursue" and dn["target"] == (700, 500))
print(("[B1 in脱检落空] %s  old=%s/%s new=%s/%s" % ("PASS" if b1 else "FAIL",
      do_["state"], do_["target"], dn["state"], dn["target"])))
if not b1: fails.append("B1")

# B2) out 脱检(目标不在表、身边也没有能直打的in怪,只有一只真实out怪):旧续pursue旧坐标,新落空追真实out怪
do_ = S(old, [M_OUT], GHOST, lock_tier="out")
dn = S(new, [M_OUT], GHOST, lock_tier="out")
b2 = (do_["state"] == "pursue" and do_["target"] == GHOST) and (dn["state"] == "pursue" and dn["target"] == (700, 500))
print(("[B2 out脱检落空] %s  old=%s/%s new=%s/%s" % ("PASS" if b2 else "FAIL",
      do_["state"], do_["target"], dn["state"], dn["target"])))
if not b2: fails.append("B2")

# B3) cross 脱检仍粘滞续 cross(例外保留)
dn = S(new, [M_IN], GHOST, lock_tier="cross", cur_cross=GHOST)
b3 = dn["state"] == "cross"
print(("[B3 cross脱检仍续cross] %s  new=%s/%s" % ("PASS" if b3 else "FAIL", dn["state"], dn["target"])))
if not b3: fails.append("B3")

# B4) 真怪一帧判死:hp_confirmed=True, attacked=True, 无血无伤 (签名顺序 has_hp,has_dmg,hp_confirmed,gone_frames,attacked,can_strike)
ls_old1 = old.lock_status(False, False, True, 0, True, can_strike=True)
ls_old3 = old.lock_status(False, False, True, 2, True, can_strike=True)
ls_new = new.lock_status(False, False, True, 0, True, can_strike=True)
b4 = (ls_old1["drop"] is False) and (ls_old3["drop"] is True) and (ls_new["drop"] is True)
print(("[B4 真怪一帧判死] %s  旧gone1.drop=%s 旧gone3.drop=%s 新.drop=%s" %
      ("PASS" if b4 else "FAIL", ls_old1["drop"], ls_old3["drop"], ls_new["drop"])))
if not b4: fails.append("B4")

# B5) 没出手(attacked=False)即使无血无伤也不丢
ls_no = new.lock_status(False, False, False, 0, False, can_strike=True)
b5 = ls_no["drop"] is False
print(("[B5 未出手不丢] %s  drop=%s" % ("PASS" if b5 else "FAIL", ls_no["drop"])))
if not b5: fails.append("B5")

# B6) pick_next 排除 current:current=in怪,另有out怪 → next=out怪,不返回current
pn = new.pick_next(PX, PY, [M_IN, M_OUT], [], SKILL, None, AUP, ADN,
                   metric=None, same_platform_fn=None, exclude=(560, 500), cur_cross=(560, 500))
b6 = pn["target"] == (700, 500)
print(("[B6 next排除current选out] %s  next=%s/%s" % ("PASS" if b6 else "FAIL", pn["state"], pn["target"])))
if not b6: fails.append("B6")

# B7) pick_next 只剩 current → idle/None
pn2 = new.pick_next(PX, PY, [M_IN], [], SKILL, None, AUP, ADN,
                    metric=None, same_platform_fn=None, exclude=(560, 500), cur_cross=(560, 500))
b7 = pn2["target"] is None
print(("[B7 next无备胎→None] %s  state=%s" % ("PASS" if b7 else "FAIL", pn2["state"])))
if not b7: fails.append("B7")

# B8) combat_step 同帧晋升:current=A(in)判死(出手无血无伤),fallback=B(in,与A相距>40不被维持容差吞并) → promoted,target=B,drop_pos=A
A = (560, 500); B = (615, 500)
monsters_ab = [box(*A), box(*B)]
d = new.combat_step(
    0, PX, PY, monsters_ab, [], SKILL, 0, 0,
    A, [], False, True, False,
    1, False, True, None,
    0, False, 0, cur_cross=None,
    attacked=True, attack_y_up=AUP, attack_y_down=ADN, allow_cross=True,
    freeze_lock=False, group_priority=False, group_radius=0,
    can_strike=True, lock_tier="in", same_platform_fn=None, metric=None,
    fallback_next=B)
b8 = (d["drop"] is True and d["drop_pos"] == A and d["promoted"] is True
      and d["target"] == B and d["state"] == "cast")
print(("[B8 current死同帧晋升next] %s  drop=%s drop_pos=%s promoted=%s state=%s target=%s" %
      ("PASS" if b8 else "FAIL", d["drop"], d["drop_pos"], d["promoted"], d["state"], d["target"])))
if not b8: fails.append("B8")

# B9) combat_step current存活时不晋升
d9 = new.combat_step(
    0, PX, PY, monsters_ab, [], SKILL, 0, 0,
    A, [(545, 470, 30, 12)], False, True, False,
    1, False, True, None,
    0, True, 0, cur_cross=None,
    attacked=True, attack_y_up=AUP, attack_y_down=ADN, allow_cross=True,
    freeze_lock=False, group_priority=False, group_radius=0,
    can_strike=True, lock_tier="in", same_platform_fn=None, metric=None,
    fallback_next=B)
b9 = (d9["drop"] is False and d9["promoted"] is False and d9["target"] == A)
print(("[B9 current存活不晋升] %s  drop=%s promoted=%s target=%s" %
      ("PASS" if b9 else "FAIL", d9["drop"], d9["promoted"], d9["target"])))
if not b9: fails.append("B9")

print("\n========================================")
if fails:
    print("失败项:", fails); sys.exit(1)
print("全部通过: A组15项零变化 + B组9项新行为")
