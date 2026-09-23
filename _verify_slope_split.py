# -*- coding: utf-8 -*-
"""离线验证 combat_logic 三档分桶+slope钉死(第二步根因修复)。喂构造怪表,不依赖游戏。"""
import importlib.util, io
spec = importlib.util.spec_from_file_location('cl', r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py')
cl = importlib.util.module_from_spec(spec); spec.loader.exec_module(cl)

PX, PY = 600, 500
SKILL = 250; CAST = 200; FAR = 500
YUP = 100          # 主攻同层上沿
YDN = 25           # 主攻下带
SJMAX = 200        # 跳高上限(开跳高)
SPF = []           # selected_platforms 空=不过滤平台
gpf = lambda *a, **k: None

def M(cx, cy):      # 怪基点(cx,cy=y2) → (x1,y1,x2,y2,score)
    return (cx-10, cy-30, cx+10, cy, 1)

def sel(monsters, tc=None, alive=False, lt=None, sj=True, gp=False):
    return cl.select_combat_target(
        PX, PY, monsters, SPF, SKILL, FAR,
        (tc[0] if tc else None), (tc[1] if tc else None), alive, False,
        gpf, 1, False, None, YUP, YDN, True, 0, 0, False, lt,
        gp, 0, YUP, YDN, False, None, None, SJMAX if sj else None)

fails = []
def ck(name, cond, extra=''):
    print(('PASS' if cond else 'FAIL'), name, extra)
    if not cond: fails.append(name)

# 1 同层近身+跳高怪同时在 → 只锁同层cast,不选slope
r = sel([M(637,479), M(640,305)])
ck('1 同层+跳高混合优先同层cast', r['state']=='cast' and r['tier']=='in' and r['target']==(637,479), r['target'])

# 2 只有跳高怪(Y-195,X40)开跳高 → slope
r = sel([M(640,305)])
ck('2 同层清空跳高怪→slope', r['state']=='slope' and r['tier']=='slope' and r['target']==(640,305), (r['state'],r['target']))

# 3 锁了slope后同层刷近身怪 → 仍维持slope(钉死不打断)
r = sel([M(637,479), M(640,305)], tc=(640,305), alive=True, lt='slope')
ck('3 slope锁钉死不被同层打断', r['state']=='slope' and r['target']==(640,305), (r['state'],r['target']))

# 4a slope锁脱检但活着(血/伤在) → 续slope
r = sel([M(637,479)], tc=(640,305), alive=True, lt='slope')
ck('4a slope脱检但活着续slope', r['state']=='slope' and r['target']==(640,305), (r['state'],r['target']))
# 4b slope锁脱检且死了 → 落pick打同层
r = sel([M(637,479)], tc=(640,305), alive=False, lt='slope')
ck('4b slope判死回落同层cast', r['state']=='cast' and r['target']==(637,479), (r['state'],r['target']))

# 5 超跳高上限Y-230 X100 开跳高 → cross
r = sel([M(700,270)])
ck('5 >跳高上限→cross', r['state']=='cross' and r['tier']=='cross', (r['state'],r['target']))

# 6 没开跳高(slope_y_up=None) Y-195 → cross(主攻够不着,走梯子)
r = sel([M(640,305)], sj=False)
ck('6 未开跳高Y195→cross', r['state']=='cross', r['state'])

# 7 跳高怪X270(>skill250<300) → pursue走近 tier=slope
r = sel([M(870,305)])
ck('7 slope怪X270走近pursue/tier=slope', r['state']=='pursue' and r['tier']=='slope', (r['state'],r['tier'],r['target']))

# 8 X>=300上层怪 → 同层档走近(不cross不slope)
r = sel([M(950,305)])
ck('8 X350上层怪先水平走近pursue/out', r['state']=='pursue' and r['tier']=='out', (r['state'],r['tier']))

# 9 同层空,slope怪+cross怪都在 → 选slope不选cross
r = sel([M(640,305), M(700,270)])
ck('9 slope优先于cross', r['state']=='slope' and r['target']==(640,305), (r['state'],r['target']))

# 10a cross锁维持:plane/slope都空 → 维持cross
r = sel([M(700,270)], tc=(700,270), alive=True, lt='cross')
ck('10a cross粘滞维持', r['state']=='cross' and r['target']==(700,270), (r['state'],r['target']))
# 10b cross途中刷出slope怪(同层空) → 落pick选slope(跳高够得到不必爬梯)
r = sel([M(640,305), M(700,270)], tc=(700,270), alive=True, lt='cross')
ck('10b cross途中slope可达改slope', r['state']=='slope' and r['target']==(640,305), (r['state'],r['target']))

# 11 下方超带Y+60 → cross
r = sel([M(640,560)])
ck('11 下方超带→cross', r['state']=='cross', r['state'])

# 12 同层单攻Y近优先:Y-10X40 vs Y-15X100 → 选Y更近的(640,490)
r = sel([M(700,485), M(640,490)])
ck('12 同层Y近优先', r['state']=='cast' and r['target']==(640,490), r['target'])

# 13 cast_range边界:同层X210→pursue走近;X190→cast
r = sel([M(810,500)]);  ck('13a X210同层走近', r['state']=='pursue' and r['tier']=='out', (r['state'],r['tier']))
r = sel([M(790,500)]);  ck('13b X190同层cast', r['state']=='cast' and r['tier']=='in', (r['state'],r['tier']))

# 14 下方同层Y+20 → cast
r = sel([M(630,520)]);  ck('14 下方Y20在带内cast', r['state']=='cast', r['state'])

# 15 无怪 → idle
r = sel([]);          ck('15 无怪idle', r['state']=='idle', r['state'])

# 16 plane out走近锁死:锁远处同层(810,500 X210),另一侧近身? 同层近身为空时维持pursue不换向;
#    出现同层近身(637,479 X37)才让位cast
r = sel([M(810,500)], tc=(810,500), alive=True, lt='out')
ck('16a plane out无近身维持pursue', r['state']=='pursue' and r['target']==(810,500), (r['state'],r['target']))
r = sel([M(810,500), M(637,479)], tc=(810,500), alive=True, lt='out')
ck('16b plane out刷近身让位cast', r['state']=='cast' and r['target']==(637,479), (r['state'],r['target']))

# ---- combat_step 集成:空怪一帧drop ----
# slope怪 can_strike=False(不在主攻带),attacked一次无血无伤且未确认命中 → drop
d = cl.combat_step(0, PX, PY, [M(640,305)], SPF, SKILL, 250, FAR, (640,305),
                   [], False, True, True, 1, False, False, gpf, 0, False, 0, None,
                   True, YUP, YDN, True, can_strike=False, lock_tier='slope', slope_y_up=SJMAX)
ck('17 slope打空(无血无伤)一帧drop', d['drop'] is True and d['state']=='slope', (d['drop'],d['state']))
# 同层 can_strike=True attacked 无血无伤 → drop
d = cl.combat_step(0, PX, PY, [M(637,479)], SPF, SKILL, 250, FAR, (637,479),
                   [], False, True, True, 1, False, False, gpf, 0, False, 0, None,
                   True, YUP, YDN, True, can_strike=True, lock_tier='in', slope_y_up=SJMAX)
ck('18 同层打空一帧drop', d['drop'] is True, d['drop'])
# 有血条 → 不drop,继续打
d = cl.combat_step(0, PX, PY, [M(637,479)], SPF, SKILL, 250, FAR, (637,479),
                   [(637-30, 479-120, 60, 8)], False, True, True, 1, False, False, gpf, 0, False, 0, None,
                   True, YUP, YDN, True, can_strike=True, lock_tier='in', slope_y_up=SJMAX)
ck('19 见血条不drop继续cast', d['drop'] is False and d['state']=='cast', (d['drop'],d['state']))

print()
if fails:
    print('==== %d 条断言失败: %s' % (len(fails), fails)); raise SystemExit(1)
print('==== 三档分桶+slope钉死 全部断言 ALL PASS ====')
