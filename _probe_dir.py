# -*- coding: utf-8 -*-
import io,re
p=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
L=io.open(p,'r',encoding='utf-8',errors='replace').read().splitlines()
print("总行数",len(L))

def ts(l):
    m=re.match(r'\[(\d\d):(\d\d):(\d\d)\]',l)
    return (int(m.group(1)),int(m.group(2)),int(m.group(3))) if m else None

# 候选段起点:最后6个 F10 / 初始化 / 启动 行
cand=[]
for i,l in enumerate(L):
    if ('F10' in l) or ('初始化' in l) or ('启动' in l and 'bot' in l.lower()) or ('单实例' in l):
        cand.append((i,l[:90]))
print("=== 最后6个段起点候选 ===")
for i,l in cand[-6:]:
    print(i,l)

# 段起点 = 最后一个 F10 行; 否则取最后一个 23:4x 初始化
starts=[i for i,l in cand if 'F10' in l]
print("首行:",L[0][:80]); print("末行:",L[-1][:80])
# 重启后 debug.log 被重开,整文件即新进程段;若有F10则从最后F10切
starts=[i for i,l in cand if 'F10' in l]
seg0=starts[-1] if starts else 0
print("=== 切段起点行",seg0, L[seg0][:90])
seg=L[seg0:]
print("段内行数",len(seg))

# 统计
def cnt(k): return sum(1 for l in seg if k in l)
print("\n=== 新段计数 ===")
for k in ['连续2拍同梯,锁定梯','锁后Y不合格','拉黑','到顶','回主线','放弃','抓住','跑跳','直跳','打怪决策','跨层','跳高','slope','恢复锁怪','停止锁怪','上梯失败']:
    print('%-16s'%k, cnt(k))
# 发键分类
from collections import Counter
keys=Counter()
for l in seg:
    if '发键' in l:
        m=re.search(r'发键\s*(\S+)',l)
        if m: keys[m.group(1)]+=1
print("发键分布:",dict(keys))

# 抽关键决策行(最后260条),原样看侧别
KW=['怪分类','锁定=','选梯','爬梯','跨层','锁怪开关','到顶','拉黑','锁后Y不合格','跳高','起跳','朝左','朝右','回主线','放弃','抓住','恢复锁怪','停止锁怪']
key_lines=[(i,l) for i,l in enumerate(seg) if any(k in l for k in KW)]
print("\n=== 新段最后 130 条关键决策行 ===")
for i,l in key_lines[-130:]:
    print(l[:160])
