# -*- coding: utf-8 -*-
import io,re,glob,json,collections
base=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"
print("=== 录制梯数据(长度=y_bottom-y_top) ===")
for f in sorted(glob.glob(base+r"\data\route_*_ladders.json")):
    try:
        d=json.load(io.open(f,'r',encoding='utf-8-sig'))
    except Exception as e:
        print(f.split('\\')[-1],"读取失败",e); continue
    arr=d if isinstance(d,list) else d.get('ladders',d)
    if isinstance(arr,dict): arr=list(arr.values())
    name=f.split('\\')[-1]
    line=[]
    for t in arr:
        try:
            tt=float(t.get('y_top')); tb=float(t.get('y_bottom')); x=t.get('x'); i=t.get('id')
            line.append("id%s x%s[%s~%s]len%.0f"%(i,x,tt,tb,tb-tt))
        except Exception as e:
            line.append("?%s"%str(t)[:40])
    print(name, " | ".join(line))

print("\n=== debug.log 最后3分钟 卡死证据 ===")
P=base+r"\debug.log"
lines=io.open(P,'r',encoding='utf-8',errors='replace').read().splitlines()
def ts(l):
    m=re.match(r'\[(\d{2}:\d{2}:\d{2})\]',l); return m.group(1) if m else None
# 找最后F10运行段起点
lastf10=None
for l in reversed(lines):
    if '检测到按键 VK=0x79' in l: lastf10=ts(l); break
print("最后F10:",lastf10)
cut=lastf10 or '23:13:30'
rows=[l for l in lines if (ts(l) or '')>=cut]
print("段内行数",len(rows),"起",cut)
ybad=[l for l in rows if '锁后Y不合格' in l]
lock=[l for l in rows if ('锁定梯id' in l and '整条上梯' in l)]
print("锁后Y不合格次数:",len(ybad)," 锁定梯次数:",len(lock))
ids=collections.Counter(re.findall(r'锁定梯id=(\S+)'," ".join(lock)))
print("锁定id分布:",dict(ids))
# 光点坐标
dots=re.findall(r'\[光点\] 中心=\(([\d]+),\s*([\d]+)\)',"\n".join(rows))
uc=collections.Counter(dots)
print("光点样本",len(dots),"唯一坐标数",len(uc)," top5:",uc.most_common(5))
# 动作
for kw in ['打怪决策','发键','起跳','开始跑跳','开始直跳','抓住','到顶','回主线','放弃','climb','上梯失败','_decide_climb']:
    print("  '%s' 条数: %d"%(kw, sum(1 for l in rows if kw in l)))
# F12
print("F12次数:", sum(1 for l in rows if 'VK=0x7B' in l))
# fps序列(每秒)
fps=re.findall(r'\[(\d{2}:\d{2}:\d{2})\] \[FPS统计\] 帧率=([\d.]+).*?绘制=(\d+)ms',"\n".join(rows))
if fps:
    vals=[(t,float(f),int(d)) for t,f,d in fps]
    print("fps样本数",len(vals),"前6:",[(t,f) for t,f,d in vals[:6]],"后6:",[(t,f) for t,f,d in vals[-6:]])
print("[draw分段]条数:", sum(1 for l in rows if '[draw分段]' in l))
for l in rows:
    if '[draw分段]' in l:
        print("  ",l.split('] ',1)[-1][:150]); 
        if rows.index(l)> [i for i,x in enumerate(rows) if '[draw分段]' in x][4]: break
