# -*- coding: utf-8 -*-
# 精确核验方案A:统一速度门真机是否生效。区分诊断行旧基准last=与本帧命中name=,统计拦截日志
import re, io, math
P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
with io.open(P, 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()
win = lines[-1400:]

re_last = re.compile(r'last=\((\d+),\s*(\d+)\)')
re_name = re.compile(r'name=(\d\.\d+).*?name=\((\d+),\s*(\d+)\)')
re_mode = re.compile(r'模式=(\S+?) ')

track = []   # (mode, last, name_or_None, score)
gate = {'main': 0, 'r2': 0, 'r0': 0}
for ln in win:
    if '统一速度门' in ln:
        if '黑框重捕' in ln: gate['r2'] += 1
        elif '冷启动' in ln: gate['r0'] += 1
        else: gate['main'] += 1
    if '[角色跟踪]' in ln:
        ml = re_last.search(ln)
        if not ml:
            continue
        last = (int(ml.group(1)), int(ml.group(2)))
        mn = re_name.search(ln)
        name = (int(mn.group(2)), int(mn.group(3))) if mn else None
        sc = float(mn.group(1)) if mn else -1
        mm = re_mode.search(ln)
        mode = mm.group(1) if mm else '?'
        track.append((mode, last, name, sc, ln))

def dist(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1]) if (a and b) else -1

def bucket(seq):
    d = {'<20': 0, '20-50': 0, '>50': 0, 'big': []}
    for i in range(1, len(seq)):
        if seq[i] is None or seq[i-1] is None:
            continue
        j = dist(seq[i-1], seq[i])
        if j < 20: d['<20'] += 1
        elif j <= 50: d['20-50'] += 1
        else:
            d['>50'] += 1
            if len(d['big']) < 12: d['big'].append((i, round(j), seq[i-1], seq[i]))
    return d

last_seq = [t[1] for t in track]
name_seq = [t[2] for t in track]
print('角色跟踪行数=%d' % len(track))
print('统一速度门拦截条数: 主匹配=%d 黑框r2=%d 冷启动r0=%d' % (gate['main'], gate['r2'], gate['r0']))
print('采信基准 last= 相邻跳变分档:', bucket(last_seq))
print('本帧name命中 相邻跳变分档:', bucket(name_seq))
print('--- 前14条原始(模式 | last | name/分) ---')
for t in track[:14]:
    print('  %s last=%s name=%s %.2f' % (t[0], t[1], t[2], t[3]))
