# -*- coding: utf-8 -*-
import io, re
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines = io.open(P, encoding='utf-8', errors='ignore').read().splitlines()
t_re = re.compile(r'^\[(\d\d):(\d\d):(\d\d)\]')
def sec(l):
    m = t_re.match(l)
    return (int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3))) if m else -1
START = 1*3600+0*60+43
DROP = ('血条检测','识别B耗时','WM_PAINT','特征点0','光点','蒙板同步','黑框方向','角色跟踪','新版比例','绘制','FPS','HP','MP','判活汇总','战斗诊断')
KEEP = ('瞬移','manual_tp','台端','台界','越线','回退','平台选台','打怪决策','主攻','群攻','空打','越界',
        '到边','硬闸','cast','pursue','重锁','清锁','关锁','开锁','选台','边缘','拉回','攻击判定','锁怪横跳','模式','mode','single','multi')
out=[]
for l in lines:
    s=sec(l)
    if s < START: continue
    if any(d in l for d in DROP): continue
    if any(k in l for k in KEEP): out.append((s,l))
for s,l in out[-150:]:
    print(l[-250:])
print("TOTAL_KEPT", len(out))
