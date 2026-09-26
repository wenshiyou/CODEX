# -*- coding: utf-8 -*-
# 验证 平台(single/multi)同台Y=40统一 + 续锁掉出同台带立即重选 + 自由(random)不受限
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import combat_logic as C

SKILL=200; AOE=100; FAR=400; YUP=100; YDN=25
def mob(cx, cy): return (cx-10, cy-40, cx+10, cy, 9)
def gmp(cx, cy): return None     # selected_platforms 传[], 不做录制台归属过滤
def step(px,py,monsters,mode,lock=None,hp=False,cup=True,cdn=True,slope=None,attacked=False,can_strike=True):
    hpb=[]
    if lock and hp:
        lcx,lcy=lock
        byc=lcy-100
        hpb=[(lcx-5, byc-5, 10, 10)]   # 命中血条落A区 -> target_alive=True
    return C.combat_step(0,px,py,monsters,[],SKILL,AOE,FAR,lock,hpb,hp,True,True,
                         None,False,True,gmp,0,hp,0,None,attacked,YUP,YDN,True,
                         freeze_lock=False,can_strike=can_strike,lock_tier=(None if not lock else 'in'),
                         slope_y_up=slope,combat_mode=mode,allow_cross_up=cup,allow_cross_down=cdn,
                         lock_grace_ms=10**9)
def show(tag,d):
    print("%-34s state=%-6s target=%s dist=%s tier=%s"%(tag,d['state'],d['target'],d['dist'],d.get('tier')))

px,py=500,500
# T1 single 同台 Y-30 X40 -> cast
show("T1 single 同台Y30", step(px,py,[mob(540,470)],'single'))
# T2 single 上层别台 Y-196 X127 新选 -> idle(不锁)
show("T2 single 别台Y196新选", step(px,py,[mob(627,304)],'single'))
# T3 single 续锁着别台怪+有血条(活着), 人物掉台 Y-196 -> 必须idle, 不得cast空打(核心回归)
show("T3 single 续锁掉台仍活着", step(px,py,[mob(627,304)],'single',lock=(627,304),hp=True,can_strike=False))
# T4 multi 同台 Y-30 -> cast(同台口径与single一致)
show("T4 multi 同台Y30", step(px,py,[mob(540,470)],'multi'))
# T5a multi 别台Y196 上方无选中台(cross_up=False) -> idle
show("T5a multi 别台Y196顶台", step(px,py,[mob(627,304)],'multi',cup=False))
# T5b multi 别台Y196 上方还有选中台(cross_up=True) -> cross走梯(不是cast/瞬移)
show("T5b multi 别台Y196可跨", step(px,py,[mob(627,304)],'multi',cup=True))
# T6a random 自由 同台面板带内 Y-80(>40) -> 仍cast(证明自由不受40收窄)
show("T6a random Y80面板带内", step(px,py,[mob(540,420)],'random'))
# T6b random 自由 Y-196 跳高关 -> cross(自由跨层保留)
show("T6b random Y196跨层", step(px,py,[mob(627,304)],'random'))
# T7 边界 single Y-39 锁 / Y-40 不锁(严格<40)
show("T7a single Y39边界", step(px,py,[mob(540,461)],'single'))
show("T7b single Y40边界", step(px,py,[mob(540,460)],'single'))
# T8 同台有近怪时, 别台怪被忽略, 锁同台(同层非空不跨)
show("T8 single 同台+别台并存", step(px,py,[mob(540,470),mob(627,304)],'single'))
print("CONST", C.MANUAL_SINGLE_Y_GAP)
