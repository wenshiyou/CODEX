# -*- coding: utf-8 -*-
import io, re, os
WD = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
LOG = os.path.join(WD, 'debug.log')
OUT = os.path.join(WD, '_boot_out.txt')

def secs(line):
    m = re.match(r'\[(\d{2}):(\d{2}):(\d{2})\]', line)
    return int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)) if m else None

lines = io.open(LOG, encoding='utf-8', errors='ignore').read().splitlines()
# 最后一次 F10 / F12 时间
t0 = t1 = None
for ln in lines:
    if ('F10 已触发' in ln) or ('[启动]' in ln) or ('收到 start' in ln) or ('收到 run' in ln):
        t0 = secs(ln)
    if ('F12 已触发' in ln) or ('[停止]' in ln) or ('收到 stop' in ln):
        t1 = secs(ln)
if t0 is None:
    # 退化:最后一段连续 运行=True
    rt = [secs(l) for l in lines if '运行=True' in l and secs(l)]
    t0, t1 = (rt[0], rt[-1]) if rt else (0, 0)
if t1 is None or t1 < t0:
    t1 = t0 + 60

win = [l for l in lines if (lambda s: s is not None and t0-1 <= s <= t1+1)(secs(l))]
print('运行窗 %s-%s (%ds) 窗内行数=%d' % (t0, t1, t1-t0, len(win)))

re_trk = re.compile(r'\[角色跟踪\] 模式=(\S+) last=\((-?\d+),\s*(-?\d+)\)')
re_diag = re.compile(r'\[战斗诊断\] 运行=True 人物=\((-?\d+),\s*(-?\d+)\) 怪数=(\d+).*?锁定=(\S+)')
pts = []; n_local=n_full=0; big=[]; prev=None
ndiag=0; nmon=0; nlock=0; py_list=[]
for l in win:
    m = re_trk.search(l)
    if m:
        mode, x, y = m.group(1), int(m.group(2)), int(m.group(3))
        if mode == '局部': n_local += 1
        else: n_full += 1
        if prev is not None:
            d = abs(x-prev[0]) + abs(y-prev[1])
            if d > 50:
                big.append((secs(l), prev, (x, y), d, mode))
        prev = (x, y); pts.append((secs(l), x, y, mode))
    d = re_diag.search(l)
    if d:
        ndiag += 1
        g = int(d.group(3)); lock = d.group(4)
        if g > 0: nmon += 1
        if lock not in ('None',): nlock += 1
        py_list.append((int(d.group(1)), int(d.group(2)), g, lock))

# last 采信点相邻位移分档
bins = {'<20稳':0, '20-50':0, '>50大跳变':0}
for i in range(1, len(pts)):
    dd = abs(pts[i][1]-pts[i-1][1]) + abs(pts[i][2]-pts[i-1][2])
    if dd < 20: bins['<20稳'] += 1
    elif dd <= 50: bins['20-50'] += 1
    else: bins['>50大跳变'] += 1
print('角色跟踪采样=%d  局部=%d 全图=%d  相邻位移分档=%s' % (len(pts), n_local, n_full, bins))
print('战斗诊断条数=%d 其中怪数>0=%d 有锁定=%d' % (ndiag, nmon, nlock))
print('--- 采信点>50px大跳变明细(最多15) ---')
for b in big[:15]:
    print('  t=%s %s->%s |d|=%d 模式=%s' % b)

# hold/沿用 钉住痕迹
hold = [l for l in win if ('char_hold' in l or '钉' in l or '上一可信' in l or '沿用' in l)]
print('钉住相关日志条数=%d' % len(hold))
for l in hold[:6]: print('  ', l[:120])

# stdout 出手计数
atk=aoe=slope=0
if os.path.exists(OUT):
    for l in io.open(OUT, encoding='utf-8', errors='ignore').read().splitlines():
        if '[主攻]' in l: atk += 1
        elif '[群攻]' in l: aoe += 1
        elif '跳高打' in l and '实行' in l: slope += 1
print('stdout出手计数: 主攻=%d 群攻=%d 跳高打启动=%d' % (atk, aoe, slope))
