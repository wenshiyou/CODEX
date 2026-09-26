# -*- coding: utf-8 -*-
# 真机验收:方向滞回修复后,本轮(最近N分钟)锁怪横跳分类 + 空打连续判死段。
import io, re, sys
LOG = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
mins = int(sys.argv[1]) if len(sys.argv) > 1 else 3
def sec(h, m, s): return int(h)*3600 + int(m)*60 + int(s)
tj = re.compile(r'^\[(\d{2}):(\d{2}):(\d{2})\].*\[锁怪横跳诊断\] (.*)$')
kj = re.compile(r'^\[(\d{2}):(\d{2}):(\d{2})\]\s*\[空怪诊断\]\s*状态=(\w+)\s+活着=(True|False)\s+drop=(True|False)\s+伤害=(True|False)\s+已出手=(True|False)')
jumps, diag, last_t = [], [], 0
with io.open(LOG, encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = tj.search(line)
        if m:
            t = sec(*m.group(1, 2, 3)); last_t = max(last_t, t)
            jumps.append((t, m.group(4).rstrip('\n')))
        k = kj.search(line)
        if k:
            t = sec(*k.group(1, 2, 3)); last_t = max(last_t, t)
            diag.append((t, k.group(4), k.group(5) == 'True', k.group(6) == 'True', k.group(8) == 'True'))
cut = last_t - mins*60
jumps = [j for j in jumps if j[0] >= cut]
diag = [d for d in diag if d[0] >= cut]

def ts(t): return '%02d:%02d:%02d' % (t//3600, (t % 3600)//60, t % 60)
# 横跳分类
out_j = [j for j in jumps if 'pursue[out]' in j[1]]
cross_j = [j for j in jumps if 'cross[cross]' in j[1]]
in_j = [j for j in jumps if 'cast[in]' in j[1]]
other = [j for j in jumps if j not in out_j and j not in cross_j and j not in in_j]
print('=== 锁怪横跳诊断(最近%d分钟) 总=%d ===' % (mins, len(jumps)))
print('  同层pursue[out]大跳 = %d (修复目标,应≈0;近身正确切换走cast[in])' % len(out_j))
print('  cross跨层大跳 = %d (本轮不动跨层,可接受)' % len(cross_j))
print('  cast[in]近身切换 = %d' % len(in_j))
print('  其它 = %d' % len(other))
for t, body in out_j:
    print('  [OUT]', ts(t), body)
# 空打连续段
bad, cur = [], None
for t, st, alive, drop, hit in diag:
    cond = st == 'cast' and not alive and not drop and not hit
    if cond:
        if cur and t - cur[-1][0] <= 2: cur.append((t,))
        else:
            if cur: bad.append(cur)
            cur = [(t,)]
    else:
        if cur: bad.append(cur); cur = None
if cur: bad.append(cur)
seg = sorted(bad, key=lambda b: b[-1][0]-b[0][0], reverse=True)
print('=== 空打未判死连续段 ===')
for b in seg[:5]:
    print('  起=%s 止=%s 跨度=%ds' % (ts(b[0][0]), ts(b[-1][0]), b[-1][0]-b[0][0]))
print('  跨度>=3s卡死段 = %d (旧bug=连续9s,目标0)' % len([b for b in bad if b[-1][0]-b[0][0] >= 3]))
print('  drop成功换锁 = %d ; 真怪活着续打 = %d ; cast采样=%d pursue采样=%d' % (
    sum(1 for d in diag if d[3] and d[4]), sum(1 for d in diag if d[2]),
    sum(1 for d in diag if d[1] == 'cast'), sum(1 for d in diag if d[1] == 'pursue')))
