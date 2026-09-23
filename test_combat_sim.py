# -*- coding: utf-8 -*-
"""
打怪决策核心 - 合成场景验证（无需游戏，真实、可重复、有证据）。
直接调用 combat_logic.select_combat_target，喂合成数据，断言输出是否符合预期。
跑法: python test_combat_sim.py
"""
import sys
import combat_logic as cl

PX, PY = 500, 300        # 人物屏幕坐标
SKILL = 150              # 技能射程
FAR = 500                # 500同平台
OK, BAD = 0, 0


def mon(cx, cy, w=30, h=40):
    """由中心x和脚y生成怪物bbox (x1,y1,x2,y2,score)"""
    return (cx - w // 2, cy - h, cx + w // 2, cy, 0.9)


def run(name, monsters, probe_side, probe_switched=False, lock=None, alive=False,
        is_platform=True, now=0, lock_time=0, **expect):
    """跑一个场景：expect 是要校验的字段(state/target/direction/dist)"""
    global OK, BAD
    d = cl.select_combat_target(
        PX, PY, monsters, [], SKILL, FAR,
        (lock[0] if lock else None), (lock[1] if lock else None), alive,
        (lambda cx, cy: is_platform), (lambda cx, cy: None),
        probe_side, probe_switched, None, None, None, True, now, lock_time)
    problems = []
    for k, v in expect.items():
        got = d[k]
        if k == 'target':
            if v is None and got is not None:
                problems.append('target=%s(期望None)' % (got,))
            elif v is not None and (got is None or abs(got[0]-v[0]) > 5 or abs(got[1]-v[1]) > 5):
                problems.append('target=%s(期望%s)' % (got, v))
        elif got != v:
            problems.append('%s=%s(期望%s)' % (k, got, v))
    if problems:
        BAD += 1
        print("[FAIL] %s -> %s  状态=%s" % (name, "; ".join(problems), d))
    else:
        OK += 1
        print("[PASS] %s -> state=%s target=%s dir=%s dist=%s" % (
            name, d['state'], d['target'], d['direction'], d['dist']))


# 1 怪在右、探测边=右 → 打右边，方向右
run("怪在右(射程内) probe右", [mon(600, 300)], 1,
    state='cast', target=(600, 300), direction='right', dist=100)
# 2 怪在左(同平台可直打) → 不管探测边，直接打左边(改：不再分左右边，取最近可打怪)
run("怪在左=直接打", [mon(400, 300)], 1,
    state='cast', target=(400, 300), direction='left', dist=100)
# 3 怪在左、探测边=左 → 打左边，方向左
run("怪在左(射程内) probe左", [mon(400, 300)], -1,
    state='cast', target=(400, 300), direction='left', dist=100)
# 4 左右各一只 → 取最近的(改：无探测边，取最近可打怪)
run("左右各一只=取最近", [mon(400, 300), mon(580, 300)], 1,
    state='cast', target=(580, 300), direction='right')
# 5 怪在500档(150<d<500)、probe右 → 走近，方向右
run("怪在500档 probe右=走近", [mon(750, 300)], 1,
    state='pursue', target=(750, 300), direction='right')
# 6 无怪 → 待机
run("无怪=待机", [], 1, state='idle', target=None, direction=None)
# 7 怪在不同层(Y差大超攻击Y范围) → 跨层候选（用户2026-09-07：只看Y差，不用is_on_platform）
_cross1 = cl.select_combat_target(PX, PY, [mon(600, 100)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: False), (lambda cx, cy: None), 1, False, None, 100, 100, True)
if _cross1['state'] == 'cross' and _cross1['target'] == (600, 100):
    OK += 1; print("[PASS] 跨层怪(Y差大)=跨层 -> state=%s target=%s" % (_cross1['state'], _cross1['target']))
else:
    BAD += 1; print("[FAIL] 跨层怪(Y差大)=跨层 -> state=%s target=%s (期望cross(600,100))" % (_cross1['state'], _cross1['target']))
# 8 锁定目标活着、出现在列表 → 维持锁定，不被别的怪抢
run("锁定怪在列表且活=维持", [mon(400, 300), mon(600, 300)], 1,
    lock=(600, 300), alive=True, state='cast', target=(600, 300), direction='right')
# 9 锁定目标脱检(本帧列表空) → 绝不对旧坐标空打，转待机(用户2026-09-07：没红框真实怪不出手)
run("锁定脱检(列表空)=不打空转待机", [], 1,
    lock=(600, 300), alive=True, state='idle', target=None)
# 9b 锁定目标脱检，但身边列表里有另一只可直打怪 → 立刻重锁那只(不空打、不发愣)
run("锁定脱检+身边有怪=重锁近身", [mon(400, 300)], 1,
    lock=(600, 300), alive=True, state='cast', target=(400, 300), direction='left')
# 10 锁定目标已死(列表空+不活) → 不维持，转待机/跨层
run("锁定死(无血条伤害)=换", [], 1,
    lock=(600, 300), alive=False, state='idle', target=None)

# ---- 存活判定 decide_alive ----
def chk_alive(name, has_hp, has_dmg, expect):
    global OK, BAD
    got = cl.decide_alive(has_hp, has_dmg)
    mark(got == expect, name, "alive=%s" % got, "期望%s" % expect)


# ---- 锁定状态 lock_status（2026-09-07精简：删除2.5秒超时丢弃，只留血条消失2帧/出手后无反馈两条）----
def chk_lock(name, has_hp, has_dmg, hp_confirmed, gone, attacked, expect):
    global OK, BAD
    r = cl.lock_status(has_hp, has_dmg, hp_confirmed, gone, attacked)
    mark(r['alive'] == expect.get('alive') and r['drop'] == expect.get('drop')
         and r['hp_confirmed'] == expect.get('hp_confirmed'),
         name, "alive=%s drop=%s confirmed=%s" % (r['alive'], r['drop'], r['hp_confirmed']),
         "期望%s" % expect)


# ---- 技能施放 decide_attack ----
def chk_atk(name, t_dist, skill, aoe, cnt, main_ok, aoe_ok, expect):
    global OK, BAD
    got = cl.decide_attack(t_dist, skill, aoe, cnt, main_ok, aoe_ok)
    mark(got == expect, name, "act=%s" % got, "期望%s" % expect)


def mark(cond, name, got, want):
    global OK, BAD
    if cond:
        OK += 1
        print("[PASS] %s -> %s" % (name, got))
    else:
        BAD += 1
        print("[FAIL] %s -> %s (%s)" % (name, got, want))


chk_alive("有血条=活", True, False, True)
chk_alive("有伤害=活", False, True, True)
chk_alive("无血条无伤害=死", False, False, False)
# 已确认血条：连续2帧无血条=打死放弃（第1帧不drop，第2帧drop）
chk_lock("命中后1帧无血条=不弃", False, False, True, 0, False,
         {'alive': False, 'drop': False, 'hp_confirmed': True})
chk_lock("命中后2帧无血条=弃(打死)", False, False, True, 1, False,
         {'alive': False, 'drop': True, 'hp_confirmed': True})
# 出手后无血条无伤害=空怪/背景，立即弃（不再等任何2.5秒超时）
chk_lock("出手后无血条无伤害=空怪弃", False, False, False, 0, True,
         {'alive': False, 'drop': True, 'hp_confirmed': False})
# 出手后仍有伤害数字=真怪不弃
chk_lock("出手后有伤害=真怪不弃", False, True, False, 0, True,
         {'alive': True, 'drop': False, 'hp_confirmed': False})
# 没出手时(如射程外赶路)哪怕一直无血条无伤害也绝不丢——可达性归防卡，不做时间丢弃
chk_lock("未出手+无反馈=不丢(射程外赶路)", False, False, False, 0, False,
         {'alive': False, 'drop': False, 'hp_confirmed': False})
# 首次见血条=命中确认
chk_lock("首次见血条=确认命中", True, False, False, 0, False,
         {'alive': True, 'drop': False, 'hp_confirmed': True})
# 技能施放：主攻优先，不被群攻抢；群攻=补充
chk_atk("目标在射程内+主攻冷却OK=主攻", 100, 150, 200, 4, True, True, 'main')
chk_atk("目标在射程外+群攻≥3+冷却OK=群攻", 300, 150, 200, 4, True, True, 'aoe')
chk_atk("目标在射程内+主攻冷却中+群攻≥3=群攻补充", 100, 150, 200, 4, False, True, 'aoe')
chk_atk("目标在射程外+群攻<3=不放", 300, 150, 200, 2, True, True, 'none')
chk_atk("目标在射程内+主攻冷却OK+群攻也有=仍主攻", 100, 150, 200, 4, True, True, 'main')

# ---- 完整编排 combat_step ----
def st(name, monsters, probe_side=1, probe_switched=False, lock=None, hp_bars=(),
       has_dmg=False, main_cd_ok=True, aoe_cd_ok=True, is_platform=True,
       lt=1000, hc_in=False, gf_in=0, aoe_range=200, now=2000, **expect):
    global OK, BAD
    d = cl.combat_step(
        now, PX, PY, monsters, [], SKILL, aoe_range, FAR,
        lock, hp_bars, has_dmg, main_cd_ok, aoe_cd_ok,
        probe_side, probe_switched,
        (lambda cx, cy: is_platform), (lambda cx, cy: None),
        lt, hc_in, gf_in)
    problems = []
    for k, v in expect.items():
        got = d[k]
        if k == 'target':
            if v is None and got is not None:
                problems.append('target=%s(期望None)' % (got,))
            elif v is not None and (got is None or abs(got[0]-v[0]) > 5 or abs(got[1]-v[1]) > 5):
                problems.append('target=%s(期望%s)' % (got, v))
        elif got != v:
            problems.append('%s=%s(期望%s)' % (k, got, v))
    if problems:
        BAD += 1
        print("[FAIL] %s -> %s  决策=%s" % (name, "; ".join(problems), d))
    else:
        OK += 1
        print("[PASS] %s -> state=%s target=%s dir=%s skill=%s alive=%s" % (
            name, d['state'], d['target'], d['direction'], d['skill'], d['alive']))


st("无怪无锁=待机", [], state='idle', target=None, skill='none')
st("怪右射程内无锁=打", [mon(600, 300)], state='cast', target=(600, 300), skill='main')
st("锁定+血条/伤害=活", [mon(600, 300)], lock=(600, 300),
   hp_bars=[(585, 270, 30, 10)], has_dmg=True, hc_in=True,
   state='cast', target=(600, 300), alive=True, skill='main')
st("命中后无反馈第1帧=不弃", [mon(600, 300)], lock=(600, 300),
   hc_in=True, gf_in=0, state='cast', target=(600, 300), gone_frames=1, drop=False)
st("怪已死(无他怪)=弃锁待机", [], lock=(600, 300),
   hc_in=True, gf_in=1, state='idle', drop=True, target=None)
st("主攻冷却+群攻4只=群攻补充", [mon(580, 300), mon(600, 300), mon(620, 300), mon(640, 300)],
   main_cd_ok=False, aoe_cd_ok=True, skill='aoe')
st("锁定+左边来怪=维持锁定", [mon(400, 300), mon(600, 300)], lock=(600, 300),
   hp_bars=[(585, 270, 30, 10)], has_dmg=True, hc_in=True,
   target=(600, 300), direction='right', skill='main')

# ---- 跨层目标稳定：cur_cross 还在候选里就维持它，不左右摇摆 ----
_dx = cl.select_combat_target(PX, PY, [mon(400, 100), mon(600, 100)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: False), (lambda cx, cy: None), 1, False, (600, 100), 100, 100, True)
mark(_dx['state'] == 'cross' and _dx['target'] and abs(_dx['target'][0]-600) <= 5,
     "跨层目标维持cur_cross", "target=%s" % (_dx['target'],), "期望维持(600,100)")

# ---- 用户2026-09-07：锁定远处怪(700,技能范围外打不到)、身边一刷近身怪(600,tier0) → 不管锁多久/是否在移动，立刻切近身(600) ----
_ds_a = cl.select_combat_target(PX, PY, [mon(600, 300), mon(700, 300)], [], SKILL, FAR,
    700, 300, True, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None,
    now=500, lock_time=0)
mark(_ds_a['state'] == 'cast' and _ds_a['target'] and abs(_ds_a['target'][0]-600) <= 5,
     "锁定远处打不到+身边刷近怪=立刻切近身(600,不等1秒)", "target=%s state=%s" % (_ds_a['target'], _ds_a['state']),
     "期望 cast(600,300)")
# ---- 锁定远处、身边没有可打近怪 → 继续追锁定目标(700) ----
_ds_b = cl.select_combat_target(PX, PY, [mon(700, 300)], [], SKILL, FAR,
    700, 300, True, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None,
    now=2000, lock_time=0)
mark(_ds_b['state'] == 'pursue' and _ds_b['target'] and abs(_ds_b['target'][0]-700) <= 5,
     "锁定远处+身边无近怪=继续追(700)", "target=%s state=%s" % (_ds_b['target'], _ds_b['state']),
     "期望 pursue(700,300)")
# ---- 锁定怪在技能范围内(600,300,tier0)→无论多久都维持不换 ----
_ds2 = cl.select_combat_target(PX, PY, [mon(600, 300), mon(700, 300)], [], SKILL, FAR,
    600, 300, True, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None,
    now=9000, lock_time=0)
mark(_ds2['target'] and abs(_ds2['target'][0]-600) <= 5,
     "锁定怪在技能范围内→维持", "target=%s" % (_ds2['target'],), "期望维持(600,300)")

# ---- 新规则：打了一下无血条无伤害 = 空怪 → drop ----
_dk = cl.combat_step(2000, PX, PY, [mon(616, 432)], [], SKILL, 200, FAR,
    (616, 432), [], False, True, True, 1, False,
    (lambda cx, cy: True), (lambda cx, cy: None), 1000, False, 0, None, True)
mark(_dk['drop'] and not _dk['alive'],
     "打一下无血条无伤害=空怪且drop", "drop=%s alive=%s" % (_dk['drop'], _dk['alive']),
     "期望 drop=True alive=False")

# ---- 新规则：怪在正上方(Y差120)超技能Y范围(上100) → 不cast(避免从下面打上平台空打错位) ----
_dy = cl.select_combat_target(PX, PY, [mon(500, 180)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, (500, 180), 100, 100)
mark(_dy['state'] != 'cast',
     "Y差120>技能Y范围上100=不cast(防空打错位)", "state=%s" % (_dy['state'],), "期望非cast(改为靠近/跨层)")

# ---- 新规则：关闭跨平台(allow_cross=False)时，跨层怪(Y差大)被忽略 → idle，只做同平台 ----
_dc = cl.select_combat_target(PX, PY, [mon(400, 100)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: False), (lambda cx, cy: None), 1, False, None, 100, 100, False)
mark(_dc['state'] == 'idle' and _dc['target'] is None,
     "关闭跨平台=跨层怪忽略→idle(先专注同平台)", "state=%s" % (_dc['state'],), "期望 idle")

# ---- 2026-09-07 用户新逻辑：Y差大(超攻击Y范围)=跨层候选，不是pursue；allow_cross=True时进cross ----
_ap = cl.select_combat_target(PX, PY, [mon(PX+400, PY-120)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None, 100, 100, True)
mark(_ap['state'] == 'cross' and _ap['target'] == (PX+400, PY-120),
     "Y差大=跨层候选(不是pursue)", "state=%s target=%s" % (_ap['state'], _ap['target']), "期望 cross 锁定该怪")

# ---- 2026-09-07 用户新逻辑：Y相近的怪不管X差多少都锁定，X差大就pursue(移动过去打)，不分平台 ----
_of = cl.select_combat_target(PX, PY, [mon(PX+600, PY)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None, None, None, True)
mark(_of['state'] == 'pursue' and _of['target'] == (PX+600, PY),
     "Y相近X差大=pursue(移动过去打)", "state=%s target=%s" % (_of['state'], _of['target']), "期望 pursue")

# ---- 2026-09-07 范围外粘性①：锁定的范围外怪本帧漏检、只剩另一侧范围外怪、无范围内怪→沿最后坐标继续追,不横跳 ----
_st1 = cl.select_combat_target(PX, PY, [mon(PX-250, PY)], [], SKILL, FAR,
    PX+300, PY, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None, 100, 100, False)
mark(_st1['state'] == 'pursue' and _st1['target'] == (PX+300, PY),
     "范围外锁定漏检+无范围内怪=粘性追最后坐标不横跳", "state=%s target=%s" % (_st1['state'], _st1['target']),
     "期望 pursue 锁定旧坐标(800,300)")

# ---- 范围外粘性②：锁着范围外怪时身边刷出范围内怪→允许范围内替换,改锁最近近身怪并cast ----
_st2 = cl.select_combat_target(PX, PY, [mon(PX+300, PY), mon(PX+60, PY)], [], SKILL, FAR,
    PX+300, PY, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None, 100, 100, False)
mark(_st2['state'] == 'cast' and _st2['target'] == (PX+60, PY),
     "范围外锁定+出现范围内怪=换近身怪打", "state=%s target=%s" % (_st2['state'], _st2['target']),
     "期望 cast 近身怪(560,300)")

# ---- 范围外粘性③：原范围内锁定怪本帧脱检(刚死)→不粘,立刻重选最近怪(哪怕在范围外),打完快速换锁 ----
_st3 = cl.select_combat_target(PX, PY, [mon(PX+200, PY)], [], SKILL, FAR,
    PX+60, PY, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None, 100, 100, False)
mark(_st3['state'] == 'pursue' and _st3['target'] == (PX+200, PY),
     "原范围内怪脱检=快速重选最近不等待", "state=%s target=%s" % (_st3['state'], _st3['target']),
     "期望 pursue 新目标(700,300)")

# ---- 范围外粘性④：两只范围外怪,锁定那只仍在→死咬锁定目标,不被更近的另一只范围外怪抢走 ----
_st4 = cl.select_combat_target(PX, PY, [mon(PX+300, PY), mon(PX+180, PY)], [], SKILL, FAR,
    PX+300, PY, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None, 100, 100, False)
mark(_st4['state'] == 'pursue' and _st4['target'] == (PX+300, PY),
     "范围外双怪=死咬已锁那只不换另一只范围外", "state=%s target=%s" % (_st4['state'], _st4['target']),
     "期望 pursue 维持(800,300)")

print("\n==== 结果: PASS=%d  FAIL=%d ====" % (OK, BAD))
sys.exit(1 if BAD else 0)