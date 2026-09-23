# -*- coding: utf-8 -*-
import io, sys, re, collections
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
LOG=r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
lines=open(LOG,'rb').read().decode('utf-8','replace').splitlines()
def sec(l):
    m=re.match(r'\[(\d\d):(\d\d):(\d\d)\]',l)
    return int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)) if m else None
idx0=max(i for i,l in enumerate(lines) if '[启动] F10 已触发' in l)
seg=lines[idx0:]
# 近90s标签分布
tss=[(sec(l),l) for l in seg if sec(l)]
maxt=max(t for t,_ in tss)
last90=[l for t,l in tss if t>=maxt-90]
tag=collections.Counter()
for l in last90:
    m=re.match(r'\[\d\d:\d\d:\d\d\]\s*(\[[^\]]+\])',l)
    if m: tag[m.group(1)]+=1
print("== 近90s标签Top20(看当前在干嘛) ==")
for k,v in tag.most_common(20): print("%-18s %d"%(k,v))
print("近90s 运行/停止/决策:", [l[:90] for l in last90 if ('[启动]' in l or '[停止]' in l or '打怪决策' in l)][-6:])
# 11:39:00 起所有 跳/爬梯/选梯/钉梯/校准/梯身/对齐
cut=11*3600+39*60
print("\n== 11:39:00起 跳跃/爬梯/选梯/钉梯 全记录 ==")
for t,l in tss:
    if t<cut: continue
    if any(k in l for k in ['跳','爬梯','选梯','钉梯','梯身','校准','对齐','y_bottom','底端','跨层','锁怪开关','放弃']):
        if '[爬梯·后脑] back=' in l: continue
        print(l[:220])
