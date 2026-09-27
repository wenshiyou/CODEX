# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import importlib
import combat_logic as C
importlib.reload(C)

SKILL=200; AOE=100; FAR=400; YUP=100; YDN=25
CASTR = SKILL*4//5   # 160 停步射程
def mob(cx, cy): return (cx-10, cy-40, cx+10, cy, 9)
def gmp(cx, cy): return None
def step(px,py,monsters,mode,rl,rr,lock=None):
    return C.combat_step(0,px,py,monsters,[],SKILL,AOE,FAR,lock,[],False,True,True,
                         None,False,True,gmp,0,False,0,None,False,YUP,YDN,True,
                         freeze_lock=False,can_strike=True,lock_tier=(None if not lock else 'in'),
                         combat_mode=mode,allow_cross_up=True,allow_cross_down=True,
                         lock_grace_ms=10**9, reach_left=rl, reach_right=rr)
def show(tag,d):
    print("%-40s state=%-6s target=%s dist=%s"%(tag,d['state'],d['target'],d['dist']))

px,py=550,500
print("cast_range =", CASTR)
# 台中间 两侧可达: 右近怪cast
show("1 台中 右近怪", step(px,py,[mob(600,475)],'single',True,True))
# 台中间 左侧同台X250(射程外但还没到边) -> pursue, 不被误滤(漏怪修复关键)
show("2 台中 左同台X250", step(px,py,[mob(300,495)],'single',True,True))
# 人到右边(右不可达) 右外侧射程外X300 -> idle
show("3 到右边 右外X300", step(px,py,[mob(850,495)],'single',True,False))
# 到右边 右脸上X150<=射程 -> cast(豁免)
show("4 到右边 右脸X150", step(px,py,[mob(700,475)],'single',True,False))
# 到右边 左侧怪 -> pursue(左没到边照锁)
show("5 到右边 左侧怪", step(px,py,[mob(300,495)],'single',True,False))
# 到左边 左外侧X400 -> idle
show("6 到左边 左外X400", step(px,py,[mob(150,495)],'single',False,True))
# 自由 右远怪X300 -> pursue(不滤)
show("7 自由 右远怪", step(px,py,[mob(850,495)],'random',True,True))
# 边界 X=160(=cast_range) 保留cast; X=161滤
show("8a 到右边 X=160", step(px,py,[mob(710,475)],'single',True,False))
show("8b 到右边 X=161", step(px,py,[mob(711,475)],'single',True,False))
# 两侧都到边 正上方同台怪(cx==px) -> cast 不拦
show("9 两边到边 正上怪", step(px,py,[mob(550,470)],'single',False,False))
# multi 同样口径
show("10 multi 到右边右外", step(px,py,[mob(850,495)],'multi',True,False))
