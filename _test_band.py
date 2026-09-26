# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import combat_logic as C

def box(cx, cy, w=30, h=30):
    return (cx-w//2, cy-h, cx+w//2, cy, 1.0)

def step(mode, monsters, lock=None, band=None, attacked=False, hp=None, dmg=False,
         ayup=100, aydn=100, skill=200, cup=True, cdn=True):
    return C.combat_step(
        now=1000, px=600, py=500, monsters=monsters, selected_platforms=[],
        skill_range=skill, aoe_range=120, far_range=600,
        lock=lock, hp_bars=(hp or []), has_dmg=dmg, main_cd_ok=True, aoe_cd_ok=True,
        probe_side=None, probe_switched=False, is_on_platform=True,
        get_monster_platform=lambda *a: None, lock_time=0, hp_confirmed=False,
        gone_frames=0, attacked=attacked, attack_y_up=ayup, attack_y_down=aydn,
        allow_cross=True, can_strike=True, lock_tier=None,
        same_platform_fn=None, metric=None, slope_y_up=None,
        combat_mode=mode, manual_same_y=40, allow_cross_up=cup, allow_cross_down=cdn,
        lock_grace_ms=10**9, manual_x_band=band)

fails=0
def ck(name, cond, extra=""):
    global fails
    print(("PASS " if cond else "FAIL ")+name+("  "+extra if extra else ""))
    if not cond: fails+=1

BAND=(100,750)

# 1 平台:带内同台怪锁cast
d=step('single',[box(650,510)],band=BAND)
ck("1带内同台怪cast", d['state']=='cast' and d['target']==(650,510), str(d['state'])+str(d['target']))

# 2 平台:带外同台怪不锁(被X带滤) -> idle
d=step('single',[box(800,510)],band=BAND)
ck("2带外同台怪不锁", d['state']=='idle' and d['target'] is None, str(d['state'])+str(d['target']))

# 3 平台:带内+带外同台怪并存,锁带内那只
d=step('single',[box(800,510),box(640,512)],band=BAND)
ck("3并存锁带内", d['state']=='cast' and d['target']==(640,512), str(d['state'])+str(d['target']))

# 4 平台:带内但Y超40上层怪,single跨层关 -> idle
d=step('single',[box(650,300)],band=BAND)
ck("4带内上层single不锁", d['state']=='idle', str(d['state'])+str(d['target']))

# 5 平台:带外上层怪被X带滤 -> idle
d=step('single',[box(700,300)],band=(100,680))
ck("5带外上层滤", d['state']=='idle', str(d['state'])+str(d['target']))

# 6 band=None(标定失效)不过滤:同台远怪可pursue
d=step('single',[box(800,510)],band=None)
ck("6None不过滤", d['state'] in('pursue','cast') and d['target']==(800,510), str(d['state'])+str(d['target']))

# 7 自由模式:给band也忽略,带外怪照锁
d=step('random',[box(800,510)],band=BAND)
ck("7自由忽略X带", d['target']==(800,510), str(d['state'])+str(d['target']))

# 8 空打死锁:平台锁脸上(607,515)但本帧脱检,怪表只剩带外别台怪,已出手无血无伤 -> idle不补打
d=step('single',[box(900,400)],lock=(607,515),band=BAND,attacked=True)
ck("8平台脱检不补打→idle", d['state']=='idle' and d['target'] is None, str(d['state'])+str(d['target']))

# 9 对照:自由模式 未到反馈窗(attacked=False)脱检,怪表有同台远怪,仍照原位补打一下(381分支)
d=step('random',[box(900,515)],lock=(607,515),band=BAND,attacked=False)
ck("9自由脱检仍补打", d['state']=='cast' and d['target']==(607,515), str(d['state'])+str(d['target']))

# 10 平台:脸上锁脱检,但本台带内仍有另一同台怪 -> 落pick锁那只(不钉旧坐标)
d=step('single',[box(900,400),box(660,512)],lock=(607,515),band=BAND,attacked=True)
ck("10脱检落pick锁带内新怪", d['state']=='cast' and d['target']==(660,512), str(d['state'])+str(d['target']))

# 13 平台:未到反馈窗(attacked=False)脸上锁脱检,怪表只剩带外远怪(真机空打帧) -> 不补打,idle
d=step('single',[box(900,515)],lock=(607,515),band=BAND,attacked=False)
ck("13平台脱检不补打→idle", d['state']=='idle' and d['target'] is None, str(d['state'])+str(d['target']))

# 11 Y40回归:同台Y30锁
d=step('single',[box(650,530)],band=BAND)
ck("11同台Y30锁", d['target']==(650,530), str(d['target']))
# 12 Y40回归:Y45上层single不锁
d=step('single',[box(650,545)],band=BAND)
ck("12同台Y45不锁", d['state']=='idle', str(d['state'])+str(d['target']))

print("\n==== %s ===="%("全部通过" if fails==0 else "%d项失败"%fails))
sys.exit(1 if fails else 0)
