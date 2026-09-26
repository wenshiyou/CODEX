# -*- coding: utf-8 -*-
import io, re, statistics as st

p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
lines = io.open(p, 'r', encoding='utf-8', errors='ignore').read().splitlines()
out = []
def w(s=''):
    out.append(str(s))

def ts(x):
    m = re.match(r'\[(\d\d:\d\d:\d\d)\]', x)
    return m.group(1) if m else None
def med(a): return round(st.median(a),1) if a else None
def p90(a): return round(sorted(a)[max(0,int(len(a)*0.9)-1)],1) if a else None
def mx(a): return round(max(a),1) if a else None
def mn(a): return round(min(a),1) if a else None

# 定位最后一段 F10 -> F12
t_start=t_end=None
for x in lines:
    if 'F10 已触发' in x or ('F10' in x and '启动' in x):
        t_start=ts(x)
for x in lines:
    if t_start and ts(x) and ts(x)>=t_start and ('F12 已触发' in x or ('F12' in x and '停止' in x)):
        t_end=ts(x)
w('运行段: %s ~ %s' % (t_start,t_end))
seg=[x for x in lines if t_start and t_end and ts(x) and t_start<=ts(x)<=t_end]
w('段内行数=%d  全文件行数=%d' % (len(seg),len(lines)))

re_cap=re.compile(r'周期(忙|闲).*?截图(\d+)\s*目标(\d+)ms\s*本轮(\d+)ms')
busy_loop,idle_loop,busy_grab,idle_grab=[],[],[],[]
for x in seg:
    m=re_cap.search(x)
    if m:
        mode,grab,tgt,loop=m.group(1),int(m.group(2)),int(m.group(3)),int(m.group(4))
        (busy_loop if mode=='忙' else idle_loop).append(loop)
        (busy_grab if mode=='忙' else idle_grab).append(grab)
w('\n[截图线程·运行段] 忙档样本=%d 闲档样本=%d' % (len(busy_loop),len(idle_loop)))
w(' 忙档本轮周期ms med/p90/max=%s/%s/%s (目标33,退避封顶60)' % (med(busy_loop),p90(busy_loop),mx(busy_loop)))
w(' 忙档grab累计 ms/秒 med/max=%s/%s' % (med(busy_grab),mx(busy_grab)))
w(' 闲档本轮周期ms med/max=%s/%s ; 闲档grab med/max=%s/%s' % (med(idle_loop),mx(idle_loop),med(idle_grab),mx(idle_grab)))

pp=[int(m.group(1)) for x in seg for m in [re.search(r'人物匹配(\d+)\s*\(ms/秒\)',x)] if m]
w('\n[人物线程·运行段] ms/秒 样本=%d med/p90/max=%s/%s/%s' % (len(pp),med(pp),p90(pp),mx(pp)))

fps,draw,up=[],[],[]
for x in seg:
    m=re.search(r'帧率=([\d.]+).*?绘制=(\d+)ms\s*上屏=(\d+)ms',x)
    if m: fps.append(float(m.group(1))); draw.append(int(m.group(2))); up.append(int(m.group(3)))
w('\n[主线·运行段] FPS样本=%d 帧率med/min=%s/%s' % (len(fps),med(fps),mn(fps)))
w(' 绘制 ms/秒 med/p90/max=%s/%s/%s ; 上屏 med/max=%s/%s' % (med(draw),p90(draw),mx(draw),med(up),mx(up)))

# draw分段
seg_log=[int(m.group(1)) for x in seg for m in [re.search(r'log=(\d+)ms',x)] if m]
seg_mid=[int(m.group(1)) for x in seg for m in [re.search(r'mid=(\d+)ms',x)] if m]
seg_ctrl=[int(m.group(1)) for x in seg for m in [re.search(r'ctrl=(\d+)ms',x)] if m]
seg_map=[int(m.group(1)) for x in seg for m in [re.search(r'map=(\d+)ms',x)] if m]
w('[draw分段·运行段] log med/max=%s/%s mid=%s ctrl=%s map=%s (ms/秒)' % (med(seg_log),mx(seg_log),med(seg_mid),med(seg_ctrl),med(seg_map)))

# 角色跟踪 全图占比 + name分数
full=sum('模式=全图' in x for x in seg); loc=sum('模式=局部' in x for x in seg)
w('\n[角色跟踪·运行段] 全图=%d 局部=%d 全图占比=%s%%' % (full,loc,round(100*full/max(1,full+loc),1)))
w(' 跳变拦截=%d  忙帧监管=%d  转全图persistent=%d' % (sum('跳变拦截' in x for x in seg),sum('忙帧监管' in x for x in seg),sum('转全图' in x for x in seg)))
names=[float(m.group(1)) for x in seg for m in [re.search(r'name=([\d.]+)',x)] if m]
if names:
    low=sum(1 for v in names if v<0.75)
    w(' name分数 样本=%d med=%s <0.75占比=%s%% min=%s' % (len(names),med(names),round(100*low/len(names),1),mn(names)))
# 锁定/怪数
import collections
tgt_none=sum('锁定=None' in x for x in seg)
w(' 战斗诊断 锁定=None行数=%d / 运行诊断行=%d' % (tgt_none, sum('战斗诊断' in x for x in seg)))

io.open(r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\_perf_report.txt','w',encoding='utf-8').write('\n'.join(out))
print('written', len(out), 'lines')
