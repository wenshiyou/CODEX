# -*- coding: utf-8 -*-
import io,re,collections
P=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines=io.open(P,'r',encoding='utf-8',errors='replace').read().splitlines()
def ts(l):
    m=re.match(r'\[(\d{2}:\d{2}:\d{2})\]',l)
    return m.group(1) if m else None
# 取20:21:40之后
rows=[l for l in lines if (ts(l) or '')>='20:21:40']
print("窗口行数",len(rows))
print("\n=== 热键/运行切换/让路/截图周期 事件 ===")
for l in rows:
    if any(k in l for k in ['检测到按键 VK=0x79','检测到按键 VK=0x7B','忙帧监管','开始运行','已停止','运行=True','运行=False']):
        print((ts(l) or '')+' '+l.split('] ',1)[-1][:120])
print("\n=== 每秒 FPS/绘制/人物/截图/YOLO + 6combat ===")
cur=None
for l in rows:
    t=ts(l)
    if not t: continue
    sec=t
    m=re.search(r'\[FPS统计\] 帧率=([\d.]+).*?截图=(\d+)ms 人物匹配=(\d+)ms 怪物匹配=(\d+)ms YOLO=(\d+)ms 绘制=(\d+)ms',l)
    if m:
        fps,cap,per,mon,yolo,draw=map(float,m.groups())
        print("%s fps=%5.1f draw=%4.0f person=%4.0f cap=%3.0f yolo=%3.0f | draw/帧=%4.1fms"%(
            t,fps,draw,per,cap,yolo, draw/fps if fps else 0))
print("\n=== 截图耗时 周期/目标/轮数(看忙档周期轨迹) ===")
n=0
for l in rows:
    if '[截图耗时]' in l:
        m=re.search(r'(\d+)轮 周期(忙|闲) 截图\d+ 目标(\d+)ms',l)
        if m:
            print((ts(l) or ''),'轮%s'%m.group(1),m.group(2),'目标%sm'%m.group(3)); n+=1
    if n>=22: break
print("\n=== draw分段(若有) 样本 ===")
c=0
for l in rows:
    if 'draw分段' in l or 'draw]' in l:
        print(l[:160]); c+=1
        if c>=12: break
print("draw分段条数(窗口内):", sum(1 for l in rows if 'draw分段' in l))
