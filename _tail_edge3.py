# -*- coding: utf-8 -*-
import io, re
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines = io.open(P, encoding='utf-8', errors='ignore').read().splitlines()
t_re = re.compile(r'^\[(\d\d):(\d\d):(\d\d)\]')
def sec(l):
    m = t_re.match(l)
    return (int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3))) if m else -1
START = 0*3600+45*60+39
DROP = ('血条检测','识别B耗时','WM_PAINT','特征点0','光点','蒙板同步','黑框方向','角色跟踪','新版比例','绘制','FPS','HP','MP')
KEEP = ('瞬移','manual_tp','台端','台界','越线','回退','平台选台','B决策','锁定','主攻','群攻','空打','越界',
        '到边','硬闸','决策','cast','pursue','重锁','清锁','关锁','开锁','选台','边缘','拉回','攻击','技能范围')
out=[]
for l in lines:
    s=sec(l)
    if s < START: continue
    if any(d in l for d in DROP): continue
    if any(k in l for k in KEEP): out.append((s,l))
for s,l in out[-130:]:
    print(l[-260:])
print("TOTAL_KEPT", len(out))
