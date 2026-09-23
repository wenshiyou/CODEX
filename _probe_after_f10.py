# -*- coding: utf-8 -*-
import time, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
time.sleep(85)
P=r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
lines=open(P,'rb').read().decode('utf-8','replace').splitlines()[-6000:]
def cnt(k): return sum(1 for l in lines if k in l)
def tail(k,n=6):
    return [l for l in lines if k in l][-n:]
print("总行(末6000) =",len(lines))
print("\n== 启停 ==")
for l in tail('[启动] F10',3)+tail('战斗已启动',3)+tail('[停止]',3)+tail('运行按钮已触发',2): print(l[:150])
print("\n== 计数: 打怪决策=%d 发键=%d 主攻=%d 群攻=%d 判活汇总=%d 田字=%d 下行避梯=%d 下行方式=%d Traceback=%d" % (
    cnt('[打怪决策]'),cnt('发键'),cnt('[主攻]'),cnt('[群攻]'),cnt('[判活汇总]'),cnt('[田字诊断]'),
    cnt('[下行·避梯]'),cnt('[下行·方式'),cnt('Traceback')))
print("\n== 战斗诊断(看运行=与时钟余,不应再-1.79e12) ==")
for l in tail('[战斗诊断]',4): print(l[:240])
print("\n== 打怪决策 近6 ==")
for l in tail('[打怪决策]',6): print(l[:160])
print("\n== 发键 近8 ==")
for l in tail('发键',8): print(l[:150])
print("\n== 判活汇总 近3 ==")
for l in tail('[判活汇总]',3): print(l[:230])
print("\n== 田字诊断 近6 (上移时gap应~150非500) ==")
for l in tail('[田字诊断]',6): print(l[:200])
print("\n== 下行避梯/方式 近10 ==")
for l in (tail('[下行·避梯]',10)+tail('[下行·方式',6)): print(l[:200])
print("\n== 异常/Traceback 近5 ==")
for l in tail('Traceback',5): print(l[:200])
