# -*- coding: utf-8 -*-
import io, re, datetime
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
lines = io.open(p, 'r', encoding='utf-8', errors='ignore').read().splitlines()
now = datetime.datetime.now()
def ts(l):
    m = re.match(r'(\d{4}-\d\d-\d\d )?(\d\d):(\d\d):(\d\d)', l)
    if not m: return None
    hh, mm, ss = int(m.group(2)), int(m.group(3)), int(m.group(4))
    t = now.replace(hour=hh, minute=mm, second=ss, microsecond=0)
    if (now - t).total_seconds() > 1800: t += datetime.timedelta(days=1)
    return t
cut = now - datetime.timedelta(minutes=3)
diag = [l for l in lines if '锁怪横跳诊断' in l and (ts(l) is None or ts(l) >= cut)]
print('最近3分钟横跳诊断 =', len(diag))
for l in diag[-15:]:
    i = l.find('[锁怪横跳诊断]')
    print(l[i:][:230])
# 同时统计这些里 drop=True 占比
tr = sum(1 for l in diag if 'drop=True' in l)
print('drop=True 条数 =', tr, '/', len(diag))
