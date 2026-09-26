# -*- coding: utf-8 -*-
import io, re, datetime
P=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
now=datetime.datetime.now()
def t_of(l):
    m=re.search(r'(\d{2}):(\d{2}):(\d{2})',l)
    if not m:return None
    t=now.replace(hour=int(m.group(1)),minute=int(m.group(2)),second=int(m.group(3)),microsecond=0)
    if (now-t).total_seconds()>12*3600:t+=datetime.timedelta(days=1)
    return t
anchors={'F10运行':['F10 已触发','运行已触发'],'F12停止':['F12','已停止','停止运行'],
 '战斗诊断':['[战斗诊断]'],'主攻出手':['[主攻]'],'群攻出手':['[群攻]'],
 '锁怪横跳':['锁怪横跳诊断'],'空打空怪':['空打','空怪','判死','无血条'],
 '平台边界':['[平台边界]'],'模式切换':['[模式]']}
last={k:[] for k in anchors}
cnt3={k:0 for k in anchors}
for l in io.open(P,encoding='utf-8',errors='replace'):
    t=t_of(l)
    for k,ws in anchors.items():
        if any(w in l for w in ws):
            last[k].append((t,l.rstrip()))
            if t and 0<=(now-t).total_seconds()<=180: cnt3[k]+=1
out=["now=%s"%now.strftime('%H:%M:%S'),"== 最近3分钟计数 == "+str(cnt3),""]
for k in anchors:
    out.append("==== %s 最后3条 ===="%k)
    for t,l in last[k][-3:]:
        out.append("%s %s"%(t.strftime('%H:%M:%S') if t else '?', l[:150]))
    out.append("")
io.open(r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\_chk4.txt","w",encoding="utf-8").write("\n".join(out))
print("OK")
