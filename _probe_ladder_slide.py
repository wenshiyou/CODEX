# -*- coding: utf-8 -*-
import io, sys, re, collections
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
LOG=r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
lines=open(LOG,'rb').read().decode('utf-8','replace').splitlines()
def sec(l):
    m=re.match(r'\[(\d\d):(\d\d):(\d\d)\]',l)
    return int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)) if m else None
# 最后一次 F10 之后
idx0=max(i for i,l in enumerate(lines) if '[启动] F10 已触发' in l)
seg=lines[idx0:]
tss=[(sec(l),l) for l in seg if sec(l)]
maxt=max(t for t,_ in tss)
lo=maxt-300   # 最近5分钟
win=[l for t,l in tss if t>=lo]
print("F10行=%d 最新=%02d:%02d:%02d 近5分钟行数=%d" % (idx0,maxt//3600,maxt%3600//60,maxt%60,len(win)))
# 启停确认
for l in win:
    if '[启动]' in l or '[停止]' in l or '[热键]' in l: print(l[:150])
# 上梯/下梯/跨层/锁/决策 事件链
KW=['爬梯','下行','跨层','到顶','清锁','清旧锁','重锁','重扫','松键开主线','状态=cross','状态=descend','状态=lift',
    '锁梯','锁定梯子','放弃梯','抓不住','自由落体','落地','滑','后脑','climb','enter','切换状态','状态机']
print("\n===== 上梯/下梯/跨层/锁定 事件链(近5分钟,去噪) =====")
for l in win:
    if any(k in l for k in KW):
        # 跳过每帧刷屏的后脑连续行,只留关键转折
        if '[爬梯·后脑] back=' in l and '到顶标志=False' in l: continue
        print(l[:210])
