# -*- coding: utf-8 -*-
# 离线验证 _pick_desc_side 避梯方向(不起GUI)
import sys, types, random
sys.path.insert(0, r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2')
import maple_route_ui as M
C = M.MinimapRouteRecorder
AVOID = M.DESC_AVOID_LADDER_MM
print("DESC_AVOID_LADDER_MM =", AVOID)

def mk(ladders, tx=None, map_pos=(100,80)):
    o = object.__new__(C)
    o.ladders = ladders
    o._target_monster_x = tx
    o._player_x = map_pos[0]
    o._player_map_pos = map_pos
    return o

def cov(x, top=40, bot=120):
    return {'x': x, 'y_top': top, 'y_bottom': bot}

cases = []
# 1 左有梯(gap10)右无 -> 跳右 +1
cases.append(("左梯右空", mk([cov(90)]), 100,80, 1))
# 2 右有梯(gap10)左无 -> 跳左 -1
cases.append(("右梯左空", mk([cov(110)]), 100,80, -1))
# 3 两侧都有,左gap10 右gap12 -> 更远=右 +1
cases.append(("两侧有梯跳更远(右12)", mk([cov(90), cov(112)]), 100,80, 1))
# 4 两侧都有,左gap12 右gap10 -> 更远=左 -1
cases.append(("两侧有梯跳更远(左12)", mk([cov(88), cov(110)]), 100,80, -1))
# 5 别层梯(梯身不覆盖py=80)当无梯; 怪在右 -> 怪方向 +1
cases.append(("别层梯忽略+怪在右", mk([cov(90, top=0, bot=30)], tx=150), 100,80, 1))
# 6 两侧无梯+怪在左 -> -1
cases.append(("无梯怪在左", mk([], tx=60), 100,80, -1))
# 7 无梯无怪参照 -> 不报错, 返回±1
o7 = mk([]); o7._target_monster_x=None
r7 = o7._pick_desc_side(100,80); assert r7 in (-1,1), r7
print("无梯无怪参照 ->", r7, "OK")
# 8 梯恰在阈值边界 gap=18 算近; 左gap18右空 -> +1
cases.append(("左梯边界gap18", mk([cov(82)]), 100,80, 1))
# 9 梯 gap=25 超阈值当无梯, 无怪 -> 随机不报错
o9 = mk([cov(75)]); o9._target_monster_x=None
r9 = o9._pick_desc_side(100,80); assert r9 in (-1,1)
print("超阈gap25当无梯 ->", r9, "OK")

fails=0
for name,o,px,py,exp in cases:
    r=o._pick_desc_side(px,py)
    ok=(r==exp)
    if not ok: fails+=1
    print(("%-22s 期望%+d 实得%+d %s")%(name,exp,r,"OK" if ok else "FAIL"))
print("RESULT:", "ALL PASS" if fails==0 else ("%d FAIL"%fails))
sys.exit(1 if fails else 0)
