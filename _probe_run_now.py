# -*- coding: utf-8 -*-
import io, sys, re, collections
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
LOG=r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
lines=open(LOG,'rb').read().decode('utf-8','replace').splitlines()
def ts(l):
    m=re.match(r'\[(\d\d):(\d\d):(\d\d)\]',l)
    return (int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3))) if m else None
# 最后一次 F10 启动的文件位置
idx0=0
for i,l in enumerate(lines):
    if '[启动] F10 已触发' in l: idx0=i
seg=lines[idx0:]
print("总行=%d  最后F10行号=%d  本次运行态行数=%d" % (len(lines), idx0, len(seg)))
# 时间戳分钟分布(看是否干净=今天11点)
mins=collections.Counter(re.match(r'\[(\d\d:\d\d):',l).group(1) for l in seg if re.match(r'\[\d\d:\d\d:',l))
print("运行态时间戳分钟分布:", dict(sorted(mins.items())))
tss=[(ts(l),l) for l in seg if ts(l)]
maxt=max(t for t,_ in tss)
win=[l for t,l in tss if t>=maxt-180]
print("最新时刻=%02d:%02d:%02d  最近180s行数=%d" % (maxt//3600,maxt%3600//60,maxt%60,len(win)))
def cnt(k,ls=win): return sum(1 for l in ls if k in l)
print("\n== 最近3分钟(运行态)计数 ==")
print("发键=%d 主攻=%d 群攻=%d 打怪决策=%d 怪分类=%d 战斗诊断=%d 判活汇总=%d | 爬梯=%d 下行避梯=%d 下行方式=%d Traceback=%d" % (
 cnt('发键'),cnt('[主攻]'),cnt('[群攻]'),cnt('[打怪决策]'),cnt('[怪分类]'),cnt('[战斗诊断]'),cnt('[判活汇总]'),
 cnt('[爬梯'),cnt('[下行·避梯]'),cnt('[下行·方式'),cnt('Traceback')))
def gaps(key,ls=win):
    t=sorted({ts(l) for l in ls if key in l})
    return [(b-a) for a,b in zip(t,t[1:])]
for key,nm in [('发键','发键'),('[打怪决策]','打怪决策'),('[怪分类]','怪分类')]:
    g=gaps(key); print("%s 相邻最大gap=%ss Top3=%s 样本秒数=%d" % (nm,(max(g) if g else -1),sorted(g,reverse=True)[:3],len(g)+1))
print("\n== 战斗诊断近6(运行=? react/turn/busy余应>=0) ==")
for l in [l for l in win if '[战斗诊断]' in l][-6:]: print(l[:270])
print("\n== 判活汇总近4 ==")
for l in [l for l in win if '[判活汇总]' in l][-4:]: print(l[:230])
print("\n== 下行避梯(新代码) 全部 ==")
for l in [l for l in seg if '[下行·避梯]' in l][-10:]: print(l[:200])
print("\n== 下行方式/爬梯 近10 ==")
for l in [l for l in win if ('[下行·方式' in l or '[爬梯' in l)][-10:]: print(l[:190])
print("\n== 打怪决策近8 ==")
for l in [l for l in win if '[打怪决策]' in l][-8:]: print(l[:190])
print("\n== Traceback/Error 近3 ==")
for l in [l for l in seg if ('Traceback' in l or ' Error' in l)][-3:]: print(l[:200])
print("\n== 最后12行 ==")
for l in seg[-12:]: print(l[:160])
