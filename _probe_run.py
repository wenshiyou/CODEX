# -*- coding: utf-8 -*-
import time, io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
time.sleep(70)
LOG=r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
lg=open(LOG,'rb').read().decode('utf-8','replace').splitlines()
# 只看 F10(11:26:39) 之后
run=[l for l in lg if re.match(r'\[11:(2[6-9]|[3-5]\d):', l) and ('[' in l)]
def ts(l):
    m=re.match(r'\[(\d\d):(\d\d):(\d\d)\]',l)
    return (int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3))) if m else None
def cnt(k,ls=run): return sum(1 for l in ls if k in l)
print("运行态行数=%d  窗口 11:26:39~" % len(run))
print("发键=%d 主攻=%d 群攻=%d 打怪决策=%d 怪分类=%d 判活汇总=%d 战斗诊断=%d 下行避梯=%d 下行方式=%d Traceback=%d" % (
 cnt('发键'),cnt('[主攻]'),cnt('[群攻]'),cnt('[打怪决策]'),cnt('[怪分类]'),cnt('[判活汇总]'),cnt('[战斗诊断]'),
 cnt('[下行·避梯]'),cnt('[下行·方式'),cnt('Traceback')))
def maxgap(key):
    t=[ts(l) for l in run if key in l and ts(l)]
    g=max((b-a for a,b in zip(t,t[1:])),default=0)
    return g
print("发键相邻最大gap=%ds  打怪决策相邻最大gap=%ds  怪分类相邻最大gap=%ds" % (maxgap('发键'),maxgap('[打怪决策]'),maxgap('[怪分类]')))
print("\n== 战斗诊断近4(时钟余应>=0) ==")
for l in [l for l in run if '[战斗诊断]' in l][-4:]: print(l[:250])
print("\n== 判活汇总近3(运行态应有真实主攻/血条数) ==")
for l in [l for l in run if '[判活汇总]' in l][-3:]: print(l[:230])
print("\n== 下行避梯/方式 近10 ==")
for l in [l for l in run if ('[下行·避梯]' in l or '[下行·方式' in l)][-10:]: print(l[:200])
print("\n== 爬梯结果 近8(成功/失败/到顶) ==")
for l in [l for l in run if ('[爬梯' in l) and ('到顶' in l or '失败' in l or '抓住' in l or '登顶' in l)][-8:]: print(l[:180])
print("\n== 田字 gap 取值分布 ==")
import collections
g=collections.Counter(re.findall(r'gap(\d+)', '\n'.join(run)))
print(dict(g))
print("\n== 异常 近5 ==")
for l in [l for l in run if ('Traceback' in l or '异常' in l or 'Error' in l)][-5:]: print(l[:180])
print("\n== 最后6行 ==")
for l in run[-6:]: print(l[:170])
