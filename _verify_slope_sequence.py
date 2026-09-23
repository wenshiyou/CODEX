# -*- coding: utf-8 -*-
"""多帧时序集成断言:复现08:47同层/上层反复换锁+腾空Y污染,验证三档+钉死+锚点切断根因。"""
import importlib.util
spec = importlib.util.spec_from_file_location('cl', r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py')
cl = importlib.util.module_from_spec(spec); spec.loader.exec_module(cl)

PX, PY = 600, 515
SKILL=250; FAR=500; YUP=100; YDN=25; SJMAX=200
SPF=[]; gpf=lambda *a,**k: None
def M(cx,cy): return (cx-10,cy-30,cx+10,cy,1)
PLANE=(621,494)    # 同层怪 X21 Y-21
HIGH=(640,320)     # 上层怪 X40 Y-195(slope)

def step(monsters, lock, py=PY, alive=False, lt=None, attacked=False, can_strike=True, hp=None, dmg=False):
    bars = hp or []
    return cl.combat_step(0, PX, py, monsters, SPF, SKILL, 250, FAR, lock,
                          bars, dmg, True, True, 1, False, False, gpf, 0, False, 0, None,
                          attacked, YUP, YDN, True, can_strike=can_strike, lock_tier=lt,
                          slope_y_up=SJMAX)

fails=[]
def ck(n,c,e=''):
    print(('PASS' if c else 'FAIL'),n,e)
    if not c: fails.append(n)

# 帧1:同层+上层都在 → cast同层
d=step([M(*PLANE),M(*HIGH)],None); ck('帧1 混合→cast同层', d['state']=='cast' and d['target']==PLANE,(d['state'],d['target']))
# 帧2:仍锁同层(上层在)→ 维持cast不被上层带走
d=step([M(*PLANE),M(*HIGH)],PLANE,alive=True,lt='in'); ck('帧2 锁同层维持cast', d['state']=='cast' and d['target']==PLANE,d['state'])
# 帧3:同层打死(怪表只剩上层)→ 转slope
d=step([M(*HIGH)],PLANE,alive=False,lt='in'); ck('帧3 同层清空→slope', d['state']=='slope' and d['target']==HIGH,(d['state'],d['target']))
# 帧4:已锁slope,同层怪又误检出一帧(漏帧/新刷)→ 仍钉死slope不回cast(关键:跳-打-跳不被打断)
d=step([M(*PLANE),M(*HIGH)],HIGH,alive=True,lt='slope'); ck('帧4 slope钉死不被同层打断', d['state']=='slope' and d['target']==HIGH,(d['state'],d['target']))
# 帧5:继续slope(同层一直在)→ 仍slope
d=step([M(*PLANE),M(*HIGH)],HIGH,alive=True,lt='slope'); ck('帧5 slope连续钉死', d['state']=='slope' and d['target']==HIGH,d['state'])
# 帧6:slope打空(attacked一次,无血无伤,can_strike=False因不在主攻Y带)→ drop,落pick;此时同层在→cast同层
d=step([M(*PLANE),M(*HIGH)],HIGH,alive=False,lt='slope',attacked=True,can_strike=False)
ck('帧6 slope打空一帧drop回同层', d['drop'] is True and d['state']=='cast' and d['target']==PLANE,(d['drop'],d['state'],d['target']))
# 帧7:slope打空但同层也空 → drop后落pick仍选slope(继续找上层打,不idle)
d=step([M(*HIGH)],HIGH,alive=False,lt='slope',attacked=True,can_strike=False)
ck('帧7 slope打空同层空→重选slope', d['drop'] is True and d['state']=='slope' and d['target']==HIGH,(d['drop'],d['state']))

# === 腾空锚点Y验证(根因3) ===
# 锁HIGH(Y-195@落地py515)。人起跳腾空,若B误用空中py=380 → dy=320-380=-60 落进同层档→误判cast(证明污染)
d_air_bad=step([M(*HIGH)],HIGH,py=380,alive=True,lt='slope')
ck('腾空误用空中py会误判(污染实证)', d_air_bad['state']=='cast', d_air_bad['state'])
# B实际腾空窗传锚点py=515 → 维持slope正确
d_air_ok=step([M(*HIGH)],HIGH,py=PY,alive=True,lt='slope')
ck('腾空用落地锚点py维持slope', d_air_ok['state']=='slope' and d_air_ok['target']==HIGH,(d_air_ok['state'],d_air_ok['target']))
# 腾空更高 py=300(dy=-20 明显同层)用锚点仍slope
d_air_ok2=step([M(*PLANE),M(*HIGH)],HIGH,py=300,alive=True,lt='slope')
# 注意:这里直接传py=300模拟"没锚点";锚点路径是调用方传py=515,已由上一条验证。本条确认污染幅度
ck('腾空py=300污染更重(反证锚点必要)', d_air_ok2['state']=='cast', d_air_ok2['state'])

# === slope 见血条继续打(不drop) ===
d=step([M(*HIGH)],HIGH,alive=True,lt='slope',can_strike=False,hp=[(HIGH[0]-30,HIGH[1]-120,60,8)])
ck('slope见血条不drop继续', d['drop'] is False and d['state']=='slope',(d['drop'],d['state']))

print()
if fails: print('==== %d失败:%s'%(len(fails),fails)); raise SystemExit(1)
print('==== 多帧时序+腾空锚点 集成断言 ALL PASS ====')
