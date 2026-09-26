# -*- coding: utf-8 -*-
import os, re, time, datetime
WD = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2'
LOG = os.path.join(WD, 'debug.log'); FLAG = os.path.join(WD, 'data', '_run_cmd.flag')

def med(a):
    if not a: return '-'
    b = sorted(a); return b[len(b)//2]
def ts_s(l):
    m = re.match(r'^\[(\d\d):(\d\d):(\d\d)\]', l)
    return ('%s:%s:%s' % (m.group(1), m.group(2), m.group(3))) if m else None

print('RUNNING_AT', datetime.datetime.now().strftime('%H:%M:%S'), '采集22秒...', flush=True)
time.sleep(22)
we = datetime.datetime.now()
with open(FLAG, 'w', encoding='ascii') as f: f.write('F12')
print('F12 sent @', we.strftime('%H:%M:%S'), flush=True)
time.sleep(2)
ws = we - datetime.timedelta(seconds=20)
s_lo, s_hi = ws.strftime('%H:%M:%S'), we.strftime('%H:%M:%S')
win = []
with open(LOG, encoding='utf-8', errors='ignore') as f:
    for line in f:
        t = ts_s(line)
        if t and s_lo <= t <= s_hi:
            win.append(line.rstrip('\n'))
print('WINDOW %s~%s lines=%d' % (s_lo, s_hi, len(win)))

fps=[]; draw=[]
br=[]; bg=[]; tgt=''; idle=busy=0
pm=[]; nf=[]; yolo=[]; hb=[]
dn=tn=mmax=msum=pursue=0; last=[]
re_fps=re.compile(r'\[FPS统计\] 帧率=([\d.]+).*?绘制=(\d+)')
re_busy=re.compile(r'\[截图耗时\]\s*(\d+)轮\s*周期忙\s*截图\d+\s*目标(\d+)ms\s*本轮(\d+)ms')
re_pm=re.compile(r'\[人物耗时\] \d+帧 人物匹配(\d+)')
re_b=re.compile(r'\[识别B耗时\] (\d+)新帧 怪模板(\d+) YOLO(\d+) 血条(\d+)')
re_dg=re.compile(r'\[战斗诊断\].*?怪数=(\d+) has_target=(\w+).*?锁定=(\S+)')
for l in win:
    m=re_fps.search(l)
    if m: fps.append(float(m.group(1))); draw.append(int(m.group(2)))
    m=re_busy.search(l)
    if m: busy+=1; br.append(int(m.group(1))); tgt=m.group(2); bg.append(int(m.group(3)))
    elif '周期闲' in l: idle+=1
    m=re_pm.search(l)
    if m: pm.append(int(m.group(1)))
    m=re_b.search(l)
    if m: nf.append(int(m.group(1))); yolo.append(int(m.group(3))); hb.append(int(m.group(4)))
    m=re_dg.search(l)
    if m:
        dn+=1; mm=int(m.group(1)); mmax=max(mmax,mm); msum+=mm
        if m.group(3)!='None': tn+=1
        last.append(l)
    if '状态=pursue' in l: pursue+=1

def mm_s(a):
    return ('min=%s med=%s max=%s' % (min(a), med(a), max(a))) if a else 'n/a'
if fps: print('帧率fps', mm_s(fps), '| 绘制ms med=%s max=%s' % (med(draw), max(draw)))
if br: print('截图忙: 忙秒=%d 闲秒=%d 目标=%sms 轮/秒 med=%s min=%s | grab本轮 med=%s %s' % (busy,idle,tgt,med(br),min(br),med(bg),mm_s(bg)))
if pm: print('人物匹配 ms/秒 med=%s max=%s' % (med(pm), max(pm)))
if nf: print('B 新帧/秒 med=%s | YOLO ms med=%s max=%s | 血条 ms med=%s' % (med(nf), med(yolo), max(yolo), med(hb)))
if dn: print('战斗诊断 n=%d 锁定非空率=%d%% 怪数max=%d 均值=%.1f pursue行=%d' % (dn, 100*tn//dn, mmax, msum/dn, pursue))
for kw in ['主攻','群攻','空怪诊断','空打','发呆','无位移','平台边界','爬梯','cross','瞬移','Traceback','异常','伤害数字','出手','技能']:
    c=sum(1 for l in win if kw in l)
    if c: print('EVENT %-6s x%d' % (kw,c))
print('--- 异常/空怪/边界 样本(末10) ---')
sam=[l for l in win if re.search(r'发呆|无位移|平台边界|Traceback|异常|空怪诊断|爬梯|cross', l)]
for l in sam[-10:]: print(l)
print('--- 战斗诊断 末5 ---')
for l in last[-5:]: print(l)
print('END', datetime.datetime.now().strftime('%H:%M:%S'))
