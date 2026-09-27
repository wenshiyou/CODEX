# -*- coding: utf-8 -*-
import io, re
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines = io.open(P, encoding='utf-8', errors='ignore').read().splitlines()
t_re = re.compile(r'^\[(\d\d):(\d\d):(\d\d)\]')
def sec(l):
    m = t_re.match(l)
    return (int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3))) if m else -1
START = 0*3600+45*60+39
DROP = ('血条检测', '识别B耗时', 'WM_PAINT', '特征点0个', '光点锁定', '光点测速', '光门模糊', '新版比例')
KEEP = ('瞬移', 'manual_tp', '台端', '台界', '越线', '回退', '平台', '锁', '主攻', '群攻', '攻击', '空',
        '决策', '方向', '巡游', 'roam', '到边', '硬闸', '拉回', '边缘', '起跳', '下跳', '梯', '模式', '选台', '越界')
out=[]
for l in lines:
    s=sec(l)
    if s < START: continue
    if any(d in l for d in DROP): continue
    if any(k in l for k in KEEP):
        out.append((s,l))
for s,l in out[-220:]:
    print(l[-260:])
print("TOTAL_KEPT", len(out))
