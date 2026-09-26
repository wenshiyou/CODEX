# -*- coding: utf-8 -*-
# 对齐每次水平瞬移前后的[光点锁定]数据坐标(FIXED_W=340空间),量出瞬移在数据坐标里的真实X阶跃。
import io, re
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines = io.open(P, encoding='utf-8', errors='ignore').read().splitlines()

def tof(t):
    h, m, s = t.split(':'); return int(h)*3600 + int(m)*60 + int(s)

tp_re = re.compile(r'\[(\d\d:\d\d:\d\d)\] \[瞬移追怪\] 水平向=(\w+) X差=(\d+)')
dot_re = re.compile(r'\[(\d\d:\d\d:\d\d)\] \[光点锁定\] 光点\((-?\d+),(-?\d+)\)')

tps = []
dots = []
for l in lines:
    m = tp_re.search(l)
    if m: tps.append((tof(m.group(1)), m.group(1), m.group(2), int(m.group(3)))); continue
    d = dot_re.search(l)
    if d: dots.append((tof(d.group(1)), d.group(1), int(d.group(2)), int(d.group(3))))

for (tf, ts, dire, xdiff) in tps[-5:]:
    win = [(tt, tstr, x, y) for (tt, tstr, x, y) in dots if tf - 3 <= tt <= tf + 3]
    # 相邻去重
    seq = []
    for w in win:
        if not seq or (seq[-1][2], seq[-1][3]) != (w[2], w[3]):
            seq.append(w)
    print("=== TP %s dir=%s X差=%d ===" % (ts, dire, xdiff))
    for (tt, tstr, x, y) in seq:
        tag = "  <-- T" if tt == tf else ""
        print("   %s dot=(%d,%d)%s" % (tstr, x, y, tag))
    # 自动估阶跃: T前最后点 vs T后0.25~0.9s首个点
    pre = [d for d in dots if tf - 1.2 <= d[0] <= tf]
    post = [d for d in dots if tf + 0.25 <= d[0] <= tf + 1.0]
    if pre and post:
        x0 = pre[-1][2]; x1 = post[0][2]
        print("   >>> 数据X阶跃 ~%d (前%d 后%d)" % (abs(x1-x0), x0, x1))
