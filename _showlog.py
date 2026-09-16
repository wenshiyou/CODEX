# -*- coding: utf-8 -*-
import io, os, re, datetime
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug.log')
lines = io.open(p, encoding='utf-8', errors='ignore').read().splitlines()
def t_of(s):
    m = re.match(r'\[(\d\d):(\d\d):(\d\d)\]', s)
    return int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)) if m else None
ts = [t_of(x) for x in lines]
ts = [t for t in ts if t]
last = max(ts)
lo = last-60
keep = ['跨层','梯','选梯','白框','对位','起跳','跑跳','直跳','realign','失败集合','post_jump',
        'transit','climb','cross','爬','Traceback','Error','异常','object is not','找梯','上梯','扫描','ROI','roi']
drop = ['光点','战斗诊断','识别B耗时']
out=[]
for ln in lines:
    t=t_of(ln)
    if t is None or t<lo: continue
    if any(d in ln for d in drop) and '梯' not in ln: continue
    if any(k in ln for k in keep): out.append(ln)
print('窗口=%ds  命中%d行' % (last-lo, len(out)))
for ln in out[-160:]:
    print(ln)
