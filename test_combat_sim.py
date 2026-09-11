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
        is_platform=True, now=0, lock_time=0, lock_tier=None, freeze_lock=False, **expect):
    """跑一个场景：expect 是要校验的字段(state/target/direction/dist)
    lock_tier=上一帧锁定类别(in/out/cross),真机每帧回存;闪断维持语义靠它区分。"""
    global OK, BAD
    d = cl.select_combat_target(
        PX, PY, monsters, [], SKILL, FAR,
        (lock[0] if lock else None), (lock[1] if lock else None), alive,
        (lambda cx, cy: is_platform), (lambda cx, cy: None),
        probe_side, probe_switched, None, None, None, True, now, lock_time,
        freeze_lock=freeze_lock, lock_tier=lock_tier)
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
# 9 锁定目标【活着】但本帧列表空(检测闪断) → 新方针(用户2026-09-10):钉死维持原坐标cast,不因一帧没看到就停/换;
#   真打死由上层combat_step的lock_status判drop→清锚后才会idle(见后面"怪已死=弃锁待机"用例)
run("锁定活着但闪断(列表空)=钉死维持不待机", [], 1,
    lock=(600, 300), alive=True, lock_tier='in', state='cast', target=(600, 300), direction='right')
# 9b 锁定怪本就在技能范围内、本帧它闪检,身边另有一只范围内怪 → in类粘性最高,钉死锁定那只、不换边
#   ("移动途中刷近怪才换"只针对范围外out;站定输出的in闪断一帧不扭头)
run("范围内锁定闪检+身边有怪=钉死不换边", [mon(400, 300)], 1,
    lock=(600, 300), alive=True, lock_tier='in', state='cast', target=(600, 300), direction='right')
# 10 select层只认锁:只要还传着lock就维持(不在这里判死);"死→弃锁"由combat_step层drop清锚,已有专测覆盖
run("select层有锁即维持(死判在combat_step层)", [], 1,
    lock=(600, 300), alive=False, lock_tier='in', state='cast', target=(600, 300), direction='right')

# ---- 存活判定 decide_alive ----
def chk_alive(name, has_hp, has_dmg, expect):
    global OK, BAD
    got = cl.decide_alive(has_hp, has_dmg)
    mark(got == expect, name, "alive=%s" % got, "期望%s" % expect)


# ---- 锁定状态 lock_status（2026-09-07精简：删除2.5秒超时丢弃，只留血条消失2帧/出手后无反馈两条）----
def chk_lock(name, has_hp, has_dmg, hp_confirmed, gone, attacked, expect, can_strike=True, freeze_lock=False):
    global OK, BAD
    r = cl.lock_status(has_hp, has_dmg, hp_confirmed, gone, attacked, can_strike, freeze_lock)
    _gone_ok = ('gone_frames' not in expect) or (r['gone_frames'] == expect['gone_frames'])
    mark(r['alive'] == expect.get('alive') and r['drop'] == expect.get('drop')
         and r['hp_confirmed'] == expect.get('hp_confirmed') and _gone_ok,
         name, "alive=%s drop=%s confirmed=%s gone=%s" % (r['alive'], r['drop'], r['hp_confirmed'], r['gone_frames']),
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
# 已确认血条：连续3帧无血条=打死放弃(用户2026-09-11:2→3,抗怪多/特效/掉帧时血条偶发漏检1-2帧;第1/2帧不drop,第3帧drop)
chk_lock("命中后1帧无血条=不弃", False, False, True, 0, False,
         {'alive': False, 'drop': False, 'hp_confirmed': True})
chk_lock("命中后2帧无血条=不弃(抗漏检)", False, False, True, 1, False,
         {'alive': False, 'drop': False, 'hp_confirmed': True})
chk_lock("命中后3帧无血条=弃(打死)", False, False, True, 2, False,
         {'alive': False, 'drop': True, 'hp_confirmed': True})
# 曾确认血条=真怪,哪怕本帧attacked且血条/伤害都漏检,也不走"空怪单帧丢弃",只交给上面连续3帧判死(用户2026-09-11治一圈怪轮流锁左右抖)
chk_lock("真怪曾命中·本帧血条伤害都漏检=不单帧丢", False, False, True, 0, True,
         {'alive': False, 'drop': False, 'hp_confirmed': True})
# 从没确认到血条(hp_confirmed=False),出手满反馈窗口仍无血条无伤害=空怪/背景,才弃(不再等任何2.5秒超时)
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
# === 用户2026-09-10两类锁怪:打不到(can_strike=False)分起跳在途/平地未起跳两种 ===
# ①起跳在途 freeze_lock=True:哪怕空怪/背景也无条件锁死不drop,等登顶或失败才解锁
chk_lock("跨层在途·曾见血条现在看不见=不丢(上层怪没打不知死活)", False, False, True, 99, False,
         {'alive': False, 'drop': False, 'hp_confirmed': True, 'gone_frames': 0},
         can_strike=False, freeze_lock=True)
chk_lock("跨层在途·哪怕attacked像空怪也不丢", False, False, False, 0, True,
         {'alive': False, 'drop': False, 'hp_confirmed': False, 'gone_frames': 0},
         can_strike=False, freeze_lock=True)
# ②平地未起跳 freeze=False:范围外真怪没出手过→不丢(血条时有时无不判死,走到一半不横跳)
chk_lock("平地范围外·未出手无反馈=不丢(赶路不横跳)", False, False, False, 99, False,
         {'alive': False, 'drop': False, 'hp_confirmed': False, 'gone_frames': 0}, can_strike=False)
#   但平地已出手打过仍无血无伤=确证空怪/误检→drop清掉(治死框永久占锁/cross被上层误检钉死)
chk_lock("平地范围外·出手无反馈=空怪照样丢", False, False, False, 0, True,
         {'alive': False, 'drop': True, 'hp_confirmed': False, 'gone_frames': 0}, can_strike=False)
chk_lock("对照:本层能打到(can_strike=True)出手无反馈仍判空怪drop", False, False, False, 0, True,
         {'alive': False, 'drop': True, 'hp_confirmed': False}, can_strike=True)
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
st("命中后无反馈第2帧=不弃(抗漏检,用户2026-09-11)", [mon(600, 300)], lock=(600, 300),
   hc_in=True, gf_in=1, state='cast', target=(600, 300), gone_frames=2, drop=False)
st("怪已死(无他怪)=弃锁待机", [], lock=(600, 300),
   hc_in=True, gf_in=2, state='idle', drop=True, target=None, gone_frames=3)
st("主攻冷却+群攻4只=群攻补充", [mon(580, 300), mon(600, 300), mon(620, 300), mon(640, 300)],
   main_cd_ok=False, aoe_cd_ok=True, skill='aoe')
st("锁定+左边来怪=维持锁定", [mon(400, 300), mon(600, 300)], lock=(600, 300),
   hp_bars=[(585, 270, 30, 10)], has_dmg=True, hc_in=True,
   target=(600, 300), direction='right', skill='main')

# === 用户2026-09-10:停步出手线=技能射程4/5(SKILL150→停步120);(120,150]仍pursue一直走,≤120才cast站定,治大圈内站定碎步 ===
run("停步线外130(4/5~满射程间)=持续走近不站定", [mon(630, 300)], 1,
    state='pursue', target=(630, 300), direction='right')
run("停步线上120=站定开打", [mon(620, 300)], 1,
    state='cast', target=(620, 300), direction='right')
# cross目标本帧漏检+cur_cross吻合=维持cross去梯,绝不退化成pursue(治cross/pursue两套移动键交替原地抖)
_crx = cl.select_combat_target(PX, PY, [], [], SKILL, FAR,
    750, 100, False, (lambda x, y: False), (lambda x, y: None), 1, False, (750, 100), 100, 100, True)
mark(_crx['state'] == 'cross' and _crx['target'] == (750, 100),
     "cross目标漏检+cur_cross吻合=维持cross不退pursue", "state=%s target=%s" % (_crx['state'], _crx['target']),
     "期望 cross(750,100)")
# 对照:同层远怪漏检、无cur_cross=沿旧坐标pursue(不误判cross、不横跳)
_prx = cl.select_combat_target(PX, PY, [], [], SKILL, FAR,
    750, 300, False, (lambda x, y: True), (lambda x, y: None), 1, False, None, 100, 100, True)
mark(_prx['state'] == 'pursue' and _prx['target'] == (750, 300),
     "同层远怪漏检无cur_cross=粘性pursue", "state=%s target=%s" % (_prx['state'], _prx['target']),
     "期望 pursue(750,300)")

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

# ---- 分类滞回(用户2026-09-10治cross/pursue逐帧横跳):锁定目标Y差卡在窄带外/维持带内→稳留同层pursue;同怪作为新怪仍走窄带判cross ----
_lk = cl.select_combat_target(PX, PY, [mon(PX+300, PY-70)], [], SKILL, FAR,
    PX+300, PY-70, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None, 60, 60)
mark(_lk['state'] == 'pursue' and _lk['direction'] == 'right',
     "锁定目标Y差70(窄带60外/维持85内)=滞回留同层pursue不横跳cross", "state=%s dir=%s" % (_lk['state'], _lk['direction']), "期望 pursue/right")
_nw = cl.select_combat_target(PX, PY, [mon(PX+300, PY-70)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None, 60, 60)
mark(_nw['state'] == 'pursue',
     "新怪Y差70但X远(300>射程150)=先水平走近pursue,不在范围外判cross(用户2026-09-11)", "state=%s" % (_nw['state'],), "期望 pursue")
_nw2 = cl.select_combat_target(PX, PY, [mon(PX+80, PY-70)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None, 60, 60)
mark(_nw2['state'] == 'cross',
     "走到X射程内(80≤150)仍Y超70=这才判cross找梯子", "state=%s" % (_nw2['state'],), "期望 cross")

# ---- 新规则：关闭跨平台(allow_cross=False)时，跨层怪(Y差大)被忽略 → idle，只做同平台 ----
_dc = cl.select_combat_target(PX, PY, [mon(400, 100)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: False), (lambda cx, cy: None), 1, False, None, 100, 100, False)
mark(_dc['state'] == 'idle' and _dc['target'] is None,
     "关闭跨平台=跨层怪忽略→idle(先专注同平台)", "state=%s" % (_dc['state'],), "期望 idle")

# ---- 用户2026-09-11新X规则：Y差大但X还远→先pursue水平走近;走到X射程内仍Y超→才cross找梯子 ----
_ap = cl.select_combat_target(PX, PY, [mon(PX+400, PY-120)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None, 100, 100, True)
mark(_ap['state'] == 'pursue' and _ap['target'] == (PX+400, PY-120),
     "Y差大但X远(400>射程)=先pursue走近,不原地cross", "state=%s target=%s" % (_ap['state'], _ap['target']), "期望 pursue 锁定该怪")
_ap2 = cl.select_combat_target(PX, PY, [mon(PX+90, PY-120)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: False), (lambda cx, cy: None), 1, False, None, 100, 100, True)
mark(_ap2['state'] == 'cross',
     "走近到X射程内(90≤150)仍Y差120=cross跨层", "state=%s" % _ap2['state'], "期望 cross")

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

# ---- 范围外粘性③：原范围内锁定怪本帧闪检(没死),场上只剩一只范围外怪 → in类钉死维持原锁定cast,不转头追范围外怪 ----
_st3 = cl.select_combat_target(PX, PY, [mon(PX+200, PY)], [], SKILL, FAR,
    PX+60, PY, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None, 100, 100, False,
    lock_tier='in')
mark(_st3['state'] == 'cast' and _st3['target'] == (PX+60, PY),
     "原范围内锁定闪检=钉死维持,不追别的范围外怪", "state=%s target=%s" % (_st3['state'], _st3['target']),
     "期望 cast 维持(560,300)")

# ---- 范围外粘性④：两只范围外怪,锁定那只仍在→死咬锁定目标,不被更近的另一只范围外怪抢走 ----
_st4 = cl.select_combat_target(PX, PY, [mon(PX+300, PY), mon(PX+180, PY)], [], SKILL, FAR,
    PX+300, PY, False, (lambda cx, cy: True), (lambda cx, cy: None), 1, False, None, 100, 100, False)
mark(_st4['state'] == 'pursue' and _st4['target'] == (PX+300, PY),
     "范围外双怪=死咬已锁那只不换另一只范围外", "state=%s target=%s" % (_st4['state'], _st4['target']),
     "期望 pursue 维持(800,300)")

# ---- 同录制平台破格(用户2026-09-11治"有怪却站桩不锁"):Y差超攻击带,但怪和人归属同一条录制绿线→按同层走过去,不判cross ----
# 怪右上:cx=PX+250(范围外dist250>SKILL150),cy=PY-150(Y差150>攻击上带60,纯Y必落cross);same_platform_fn=True=同录制平台
_sp1 = cl.select_combat_target(PX, PY, [mon(PX+250, PY-150)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: False), (lambda cx, cy: None), 1, False, None, 60, 30, True,
    same_platform_fn=(lambda cx, cy: True))
mark(_sp1['state'] == 'pursue' and _sp1['target'] == (PX+250, PY-150),
     "同录制平台·Y差150破格=同层走过去(不cross站桩)", "state=%s target=%s" % (_sp1['state'], _sp1['target']),
     "期望 pursue 走过去(750,150)")
# 对照:走到X射程内(PX+100,X差100≤150)仍Y差150、且不在同一条录制平台(same=False)→cross走梯子
_sp2 = cl.select_combat_target(PX, PY, [mon(PX+100, PY-150)], [], SKILL, FAR,
    None, None, False, (lambda cx, cy: False), (lambda cx, cy: None), 1, False, None, 60, 30, True,
    same_platform_fn=(lambda cx, cy: False))
mark(_sp2['state'] == 'cross',
     "X进射程仍Y差150且不同平台=跨层cross", "state=%s" % _sp2['state'], "期望 cross")

# ---- 群攻钉死(用户2026-09-10):锁着右侧一簇在追(范围外),左侧另一簇变得更多/更近也不换簇,先打完锁定簇 ----
# 锁(PX+260,范围外dist260);右簇3只、左簇4只(更多);开群攻优先 group_radius=120。旧_doswitch会换左簇,新规则钉死右簇。
_g1 = cl.select_combat_target(PX, PY,
    [mon(PX+260, PY), mon(PX+290, PY), mon(PX+320, PY), mon(PX-300, PY), mon(PX-270, PY), mon(PX-240, PY), mon(PX-210, PY)],
    [], SKILL, FAR, PX+260, PY, False, (lambda cx, cy: True), (lambda cx, cy: None),
    1, False, None, 100, 100, True, 0, 0, False, True, 120, 100, 100, False)
mark(_g1['state'] == 'pursue' and _g1['target'] == (PX+260, PY),
     "群攻:锁簇后另一簇更多更近也钉死不换", "state=%s target=%s" % (_g1['state'], _g1['target']),
     "期望 pursue 维持锁定簇(760,300)")

# ---- 能直打近怪最优先(用户2026-09-10真机复现):无锁重选时,一只X差100能站定直打(Y差9)、另一只Y差5但X差395射程外,
#      旧"先按Y差排序"会去追395外那只,新规则必须cast能直打的近怪 ----
run("能直打近怪优先于Y更小的远怪", [mon(PX+100, PY+9), mon(PX-395, PY+5)], 1,
    state='cast', target=(PX+100, PY+9), direction='right')
# 范围内两只(X都≤停步线):X近的那只哪怕Y差更大也优先(用户:范围内只按X、不看Y,排序唯一不横跳)
run("范围内按X近不看Y", [mon(PX+40, PY-60), mon(PX+110, PY)], 1,
    state='cast', target=(PX+40, PY-60), direction='right')
# 范围外两只(X都>停步线):按Y相近优先,哪怕它X更远(用户:范围外Y近X远也选Y近这只,不左右为难)
run("范围外按Y近优先", [mon(PX+300, PY+5), mon(PX+150, PY+60)], 1,
    state='pursue', target=(PX+300, PY+5), direction='right')

# ---- 真机回归①(2026-09-10碎步不打怪):锁着X近但Y差96出攻击带的错层空框(落cross),身边有Y在带、X进停步线真怪
#      旧"只看X"把空框当范围内钉cast→对空坐标乱走、真怪顶不上来;新规则必须落重选cast身边真怪,绝不cast空框 ----
_rg1 = cl.select_combat_target(PX, PY, [mon(PX+60, PY+96), mon(PX-100, PY+9)], [], SKILL, FAR,
    PX+60, PY+96, False, (lambda a, b: True), (lambda a, b: None),
    1, False, None, 80, 30, True, lock_tier='cross')
mark(_rg1['state'] == 'cast' and _rg1['target'] == (PX-100, PY+9),
     "X近Y远错层空框不挡身边同层真怪(治碎步不打)", "state=%s target=%s" % (_rg1['state'], _rg1['target']),
     "期望 cast 身边真怪(400,309)")

# ---- 真机回归②(2026-09-10 cross呆站):上层多个误检框X在541→480漂移、层Y稳定≈299、都在右侧,
#      cur_cross按"同层Y(±40)+同侧"强粘,逐帧都钉在这一层右侧cross,不随X漂移横跳、不退pursue ----
_rg2 = cl.select_combat_target(PX, 500, [mon(523, 299), mon(510, 300), mon(480, 302)], [], SKILL, FAR,
    None, None, False, (lambda a, b: True), (lambda a, b: None),
    1, False, (541, 299), 80, 30, True)
mark(_rg2['state'] == 'cross' and _rg2['direction'] == 'right' and abs(_rg2['target'][1] - 299) <= 40,
     "上层框X漂移仍钉同层同侧cross(治cross横跳呆站)", "state=%s target=%s dir=%s" % (
         _rg2['state'], _rg2['target'], _rg2['direction']),
     "期望 cross 右侧、层Y≈299")

# ---- 群攻跳高打与普通一套(用户2026-09-11):开跳高打时attack_y_up传的是跳高上限150,群攻聚簇池不得被aoe_y(80)
#      覆盖;Y差102(在跳高区间、但>群攻带80)的高处怪必须进可打池走近后high_slope跳打,不能判cross去找梯子 ----
_gs = cl.select_combat_target(PX, PY, [mon(PX+80, PY-102)], [], SKILL, FAR,
    None, None, False, (lambda a, b: True), (lambda a, b: None), 1, False, None,
    150, 30, True, group_priority=True, group_radius=150, aoe_y_up=80, aoe_y_down=60)
mark(_gs['state'] == 'cast',
     "群攻+开跳高打:Y差102高处怪进可打池(不cross找梯子)", "state=%s" % _gs['state'], "期望 cast")
# 对照:没开跳高打(attack_y_up=主攻带60),群攻池=max(60,80)=80,Y差102仍超带→cross(真够不着才跨层,不误留)
_gs2 = cl.select_combat_target(PX, PY, [mon(PX+80, PY-102)], [], SKILL, FAR,
    None, None, False, (lambda a, b: True), (lambda a, b: None), 1, False, None,
    60, 30, True, group_priority=True, group_radius=150, aoe_y_up=80, aoe_y_down=60)
mark(_gs2['state'] == 'cross',
     "群攻+没开跳高打:Y差102超群攻带=cross对照", "state=%s" % _gs2['state'], "期望 cross")

print("\n==== 结果: PASS=%d  FAIL=%d ====" % (OK, BAD))
sys.exit(1 if BAD else 0)