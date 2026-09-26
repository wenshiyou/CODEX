# -*- coding: utf-8 -*-
import os, re, time, datetime
WD = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
LOG = os.path.join(WD, 'debug.log'); FLAG = os.path.join(WD, 'data', '_run_cmd.flag')

def med(a):
    if not a: return '-'
    b=sorted(a); return b[len(b)//2]
def stat(name, a):
    if not a: print(name, 'n/a'); return
    print('%-16s med=%s max=%s (n=%d)' % (name, med(a), max(a), len(a)))
def ts(l):
    m=re.match(r'^\[(\d\d):(\d\d):(\d\d)\]', l); return m.group(0)[1:-1] if m else None

# 自启停: F10 -> 24s -> F12, 稳态窗 t+4..t+24
t0=datetime.datetime.now()
with open(FLAG,'w',encoding='ascii') as f: f.write('F10')
print('F10 @', t0.strftime('%H:%M:%S'), flush=True)
time.sleep(24)
t1=datetime.datetime.now()
with open(FLAG,'w',encoding='ascii') as f: f.write('F12')
print('F12 @', t1.strftime('%H:%M:%S'), flush=True)
time.sleep(2)
s_lo=(t0+datetime.timedelta(seconds=4)).strftime('%H:%M:%S'); s_hi=t1.strftime('%H:%M:%S')
win=[]
with open(LOG,encoding='utf-8',errors='ignore') as f:
    for line in f:
        t=ts(line)
        if t and s_lo<=t<=s_hi: win.append(line.rstrip('\n'))
print('WINDOW %s~%s lines=%d' % (s_lo,s_hi,len(win)))

fps=[];draw=[];br=[];bg=[];pm=[];yolo=[];hb=[];nf=[]
dseg={k:[] for k in ['log','mid','ctrl','map','bg','rest']}
n_full=n_local=n_paint=n_flow=n_cam=0; tgt=''
re_fps=re.compile(r'\[FPS统计\] 帧率=([\d.]+).*?绘制=(\d+)')
re_busy=re.compile(r'\[截图耗时\]\s*(\d+)轮\s*周期忙\s*截图\d+\s*目标(\d+)ms\s*本轮(\d+)ms')
re_pm=re.compile(r'\[人物耗时\] \d+帧 人物匹配(\d+)')
re_b=re.compile(r'\[识别B耗时\] (\d+)新帧 怪模板\d+ YOLO(\d+) 血条(\d+)')
re_draw=re.compile(r'\[draw分段\].*?log=(\d+)ms mid=(\d+)ms ctrl=(\d+)ms map=(\d+)ms bg=(\d+)ms rest=(\d+)ms')
for l in win:
    m=re_fps.search(l)
    if m: fps.append(float(m.group(1))); draw.append(int(m.group(2)))
    m=re_busy.search(l)
    if m: br.append(int(m.group(1))); tgt=m.group(2); bg.append(int(m.group(3)))
    m=re_pm.search(l)
    if m: pm.append(int(m.group(1)))
    m=re_b.search(l)
    if m: nf.append(int(m.group(1))); yolo.append(int(m.group(2))); hb.append(int(m.group(3)))
    m=re_draw.search(l)
    if m:
        for i,k in enumerate(dseg): dseg[k].append(int(m.group(i+1)))
    if '模式=全图' in l: n_full+=1
    if '模式=局部' in l: n_local+=1
    if 'WM_PAINT' in l and '蒙板' in l: n_paint+=1
    if '[田字诊断]' in l: n_flow+=1
    if '相机' in l or 'camera' in l.lower(): n_cam+=1

if fps: print('帧率fps min=%s med=%s max=%s | 绘制 med=%s max=%s' % (min(fps),med(fps),max(fps),med(draw),max(draw)))
if br: print('截图忙 目标=%sms 轮/秒 med=%s min=%s | grab本轮 med=%s min=%s max=%s' % (tgt,med(br),min(br),med(bg),min(bg),max(bg)))
stat('人物匹配ms/秒', pm)
print('人物跟踪帧: 局部=%d 全图=%d  -> 全图占比 %d%%' % (n_local,n_full,(100*n_full//max(1,n_local+n_full))))
print('YOLO ms/秒 med=%s max=%s | 血条 med=%s | B新帧 med=%s' % (med(yolo),max(yolo),med(hb),med(nf)))
print('--- draw分段 ms/秒 (运行态193ms花在哪) ---')
for k in dseg: stat('  draw.'+k, dseg[k])
print('怪物蒙板WM_PAINT x%d, 田字诊断行 x%d, 相机相关行 x%d' % (n_paint,n_flow,n_cam))
for kw in ['主攻','群攻','空怪诊断','瞬移无位移','平台边界','发呆','无位移','出手']:
    c=sum(1 for l in win if kw in l)
    if c: print('EVENT %-6s x%d' % (kw,c))
