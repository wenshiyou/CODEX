# -*- coding: utf-8 -*-
import io, re, statistics as st

p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
lines = io.open(p, 'r', encoding='utf-8', errors='ignore').read().splitlines()
print('TOTAL_LINES', len(lines), ' first=', lines[0][:10] if lines else '-', ' last=', lines[-1][:12] if lines else '-')

def med(x):
    return round(st.median(x), 1) if x else None
def p90(x):
    return round(sorted(x)[int(len(x)*0.9)-1], 1) if x else None
def mx(x):
    return round(max(x), 1) if x else None

# 截图耗时
cap_busy_loop, cap_idle_loop, cap_busy_grab, cap_idle_grab, busy_t = [], [], [], [], []
re_cap = re.compile(r'\[([\d:]+)\].*周期(忙|闲).*?截图(\d+)\s*目标(\d+)ms\s*本轮(\d+)ms')
for x in lines:
    m = re_cap.search(x)
    if m:
        t, mode, grab, tgt, loop = m.group(1), m.group(2), int(m.group(3)), int(m.group(4)), int(m.group(5))
        if mode == '忙':
            cap_busy_loop.append(loop); cap_busy_grab.append(grab); busy_t.append(t)
        else:
            cap_idle_loop.append(loop); cap_idle_grab.append(grab)
print('\n[截图] 忙档样本=%d 闲档样本=%d' % (len(cap_busy_loop), len(cap_idle_loop)))
if cap_busy_loop:
    print('  忙档本轮周期ms med/p90/max =', med(cap_busy_loop), p90(cap_busy_loop), mx(cap_busy_loop),
          ' 目标33~60; 忙档时间', busy_t[0], '~', busy_t[-1])
    print('  忙档grab累计ms/秒 med/max =', med(cap_busy_grab), mx(cap_busy_grab))
if cap_idle_loop:
    print('  闲档本轮周期ms med/p90/max =', med(cap_idle_loop), p90(cap_idle_loop), mx(cap_idle_loop), ' 目标100')

# 人物耗时
pp = [int(m.group(1)) for x in lines for m in [re.search(r'人物匹配(\d+)\s*\(ms/秒\)', x)] if m]
print('\n[人物线程] ms/秒 样本=%d med/p90/max =' % len(pp), med(pp), p90(pp), mx(pp))

# FPS统计
fps, draw, up = [], [], []
for x in lines:
    m = re.search(r'帧率=([\d.]+).*?绘制=(\d+)ms\s*上屏=(\d+)ms', x)
    if m:
        fps.append(float(m.group(1))); draw.append(int(m.group(2))); up.append(int(m.group(3)))
print('\n[主线FPS] 样本=%d 帧率med/min =' % len(fps), med(fps), (round(min(fps),1) if fps else None),
      ' 绘制ms/秒 med/max =', med(draw), mx(draw), ' 上屏med/max=', med(up), mx(up))

# 忙帧监管
fb = [x for x in lines if '忙帧监管' in x]
print('\n[忙帧监管] 全文次数=%d' % len(fb))
for x in fb[-6]:
    print('  ', x[:150])

# 运行态标签探查
print('\n[运行态探查]')
for kw in ['运行=True', '运行=False', '开始自动', '停止', 'F10', 'F12', '文件触发', '自动打怪']:
    h = [x for x in lines if kw in x]
    print('  %-8s 次数=%d  末样=%s' % (kw, len(h), (h[-1][:110] if h else '-')))
