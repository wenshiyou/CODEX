# -*- coding: utf-8 -*-
import io, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines = io.open(P, encoding='utf-8', errors='replace').read().splitlines()
def tsec(s):
    m = re.match(r'\[(\d{2}):(\d{2}):(\d{2})\]', s)
    return int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)) if m else None
last = None
for l in reversed(lines):
    t = tsec(l)
    if t: last = t; break
cut = last-180
KEEP = ['台界带核对','平台方向门','打怪决策','平台复核','攻击判定','空怪','空打','瞬移追怪','锁怪开关','平台边界','运行已触发','mode=','锁怪横跳']
band=[]; other=[]
for l in lines:
    t=tsec(l)
    if not t or t<cut: continue
    if '台界带核对' in l: band.append(l)
    elif any(k in l for k in KEEP): other.append(l)
print("=== 台界带核对 最近25条 ===")
for l in band[-25:]: print(l)
print("\n=== 其他关键 最近70条 ===")
for l in other[-70:]: print(l)
