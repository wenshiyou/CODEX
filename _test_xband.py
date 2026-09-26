# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import combat_logic as C

SKILL=200; AOE=100; FAR=400; YUP=100; YDN=25
def mob(cx, cy): return (cx-10, cy-40, cx+10, cy, 9)
def gmp(cx, cy): return None
def step(px,py,monsters,mode,band=None,lock=None,cup=True,cdn=True,slope=None):
    return C.combat_step(0,px,py,monsters,[],SKILL,AOE,FAR,lock,[],False,True,True,
                         None,False,True,gmp,0,False,0,None,False,YUP,YDN,True,
                         freeze_lock=False,can_strike=True,lock_tier=(None if not lock else 'in'),
                         slope_y_up=slope,combat_mode=mode,allow_cross_up=cup,allow_cross_down=cdn,
                         lock_grace_ms=10**9, manual_x_band=band)
def show(tag,d):
    print("%-38s state=%-6s target=%s dist=%s"%(tag,d['state'],d['target'],d['dist']))

px,py=550,500
BAND=(400,700)   # 本台屏幕可达X带(已含内缩)
# 1 平台 带内同台近怪 -> cast
show("1 single 带内同台", step(px,py,[mob(600,475)],'single',band=BAND))
# 2 平台 右侧带外同高异台怪 X差300 -> 不锁 idle
show("2 single 右带外同高X300", step(px,py,[mob(850,495)],'single',band=BAND))
# 3 平台 左侧带外同高 X差400 -> 不锁
show("3 single 左带外同高X400", step(px,py,[mob(150,495)],'single',band=BAND))
# 4 平台 带内近怪+右带外远怪并存 -> 锁带内
show("4 single 带内+带外并存", step(px,py,[mob(850,495),mob(600,475)],'single',band=BAND))
# 5 边界: cx=700(=带上沿)保留cast; cx=701滤掉
show("5a single 边界cx=700", step(px,py,[mob(700,475)],'single',band=BAND))
show("5b single 边界cx=701", step(px,py,[mob(701,475)],'single',band=BAND))
# 6 multi 带外同高怪同样滤
show("6 multi 右带外", step(px,py,[mob(850,495)],'multi',band=BAND))
# 7 自由 random band=None: 同高远怪照常pursue走近(不过滤)
show("7 random 不带 远怪pursue", step(px,py,[mob(850,495)],'random',band=None))
# 8 平台 band=None(光点缺失兜底): 不锁死,同台近怪仍cast
show("8 single band缺失兜底", step(px,py,[mob(600,475)],'single',band=None))
# 9 平台 带外但Y别台(上层)怪也滤(不cross)
show("9 single 带外上层怪", step(px,py,[mob(850,320)],'single',band=BAND))
