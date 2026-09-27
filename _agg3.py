# -*- coding: utf-8 -*-
import re, io, collections
P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
with io.open(P, 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()
win = lines[-1300:]
rel = pers = rej = 0
samples = []
for ln in win:
    if '门·大跳变放行' in ln:
        m = re.search(r'jd=([\d.]+)>\d+ reloc=(\d) pers=(\d) dt=([\d.]+)', ln)
        if m:
            if m.group(2) == '1': rel += 1
            if m.group(3) == '1': pers += 1
            if len(samples) < 14: samples.append('jd=%s reloc=%s pers=%s dt=%s' % m.groups())
    if '跳变拦截' in ln:
        rej += 1
print('门·大跳变放行 总=%d 其中瞬移窗reloc=%d 持续丢失pers=%d' % (rel+pers, rel, pers))
print('跳变拦截(拒绝)总=%d' % rej)
print('--- 放行样本 ---')
for s in samples: print('  '+s)
# 主攻计数
import os
bo = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\_boot_out.txt'
if os.path.exists(bo):
    with io.open(bo, 'r', encoding='utf-8', errors='replace') as f:
        b = f.read()
    for kw in ('主攻', '群攻', '跳高'):
        print('stdout[%s]行数=%d' % (kw, b.count(kw)))
