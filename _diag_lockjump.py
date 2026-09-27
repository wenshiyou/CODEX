# -*- coding: utf-8 -*-
import io, re
LOG = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
jump, run_true, atk, diag = [], 0, 0, []
with io.open(LOG, encoding='utf-8', errors='ignore') as f:
    for line in f:
        if '锁怪横跳诊断' in line:
            jump.append(line.rstrip('\n'))
        if '战斗诊断' in line and '运行=True' in line:
            run_true += 1
        if ('发键 x ' in line) or ('发键 c ' in line):
            atk += 1
        if '空怪诊断' in line:
            diag.append(line.rstrip('\n'))
print('运行=True战斗诊断行 =', run_true)
print('主攻发键(x/c)行 =', atk)
print('锁怪横跳诊断条数 =', len(jump))
for l in jump[-25:]:
    print(l)
