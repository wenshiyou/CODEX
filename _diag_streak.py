# -*- coding: utf-8 -*-
# 只读诊断:量化"空打连续不drop"最长持续,验证判死修复。解析最近N分钟[空怪诊断]。
import re, sys, io, time
LOG = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
mins = int(sys.argv[1]) if len(sys.argv) > 1 else 4
pat = re.compile(r'\[(\d{2}):(\d{2}):(\d{2})\]\s*\[空怪诊断\]\s*状态=(\w+)\s+活着=(True|False)\s+drop=(True|False)\s+伤害=(True|False)\s+已出手=(True|False)')
rows = []
last_t = 0
with io.open(LOG, encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = pat.search(line)
        if not m:
            continue
        h, mi, s, st, alive, drop, dmg, hit = m.groups()
        t = int(h)*3600 + int(mi)*60 + int(s)
        last_t = max(last_t, t)
        rows.append((t, st, alive == 'True', drop == 'True', dmg == 'True', hit == 'True'))
cut = last_t - mins*60
rows = [r for r in rows if r[0] >= cut]

# 严格连续段: 状态=cast & 活着False & dropFalse & 已出手False; 相邻采样间隔<=2s视为同段
bad = []
cur = None
for t, st, alive, drop, dmg, hit in rows:
    cond = (st == 'cast' and not alive and not drop and not hit)
    if cond:
        if cur and t - cur[-1][0] <= 2:
            cur.append((t, st, alive, drop, dmg, hit))
        else:
            if cur: bad.append(cur)
            cur = [(t, st, alive, drop, dmg, hit)]
    else:
        if cur: bad.append(cur); cur = None
if cur: bad.append(cur)

def ts(t): return '%02d:%02d:%02d' % (t//3600, (t % 3600)//60, t % 60)

seg = sorted(bad, key=lambda b: (b[-1][0]-b[0][0], len(b)), reverse=True)
print('窗口最近%d分钟 空怪诊断采样=%d' % (mins, len(rows)))
print('cast空打未判死连续段(条件:cast+活False+dropFalse+已出手False):')
for b in seg[:8]:
    print('  起=%s 止=%s 采样=%d 跨度=%ds' % (ts(b[0][0]), ts(b[-1][0]), len(b), b[-1][0]-b[0][0]))
over = [b for b in bad if (b[-1][0]-b[0][0]) >= 3]
print('跨度>=3s的卡死段数量 =', len(over), '(旧bug铁证为连续9s/4s,修复后应为0)')
print('drop=True且已出手=True(成功判死换锁)次数 =', sum(1 for r in rows if r[3] and r[5]))
print('活着=True(真怪续打)采样数 =', sum(1 for r in rows if r[2]))
print('cast总采样 =', sum(1 for r in rows if r[1]=='cast'), ' pursue总采样 =', sum(1 for r in rows if r[1]=='pursue'))
