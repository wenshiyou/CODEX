# -*- coding: utf-8 -*-
import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
LOG=r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
lines=open(LOG,'rb').read().decode('utf-8','replace').splitlines()
def sec(l):
    m=re.match(r'\[(\d\d):(\d\d):(\d\d)\]',l)
    return int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)) if m else None
idx0=max(i for i,l in enumerate(lines) if '[启动] F10 已触发' in l)
seg=lines[idx0:]
# 事件链(放宽, 含下行/自由落体/落地/锁怪开关/到顶/抓住/滑落)
KW=['爬梯','下行','跨层','到顶','清旧锁','重扫','恢复锁怪','关闭锁怪','松键开主线','自由落体','落地','抓不住','状态=cross','状态=descend','空怪诊断']
print("===== 事件链(本次F10后) =====")
for l in seg:
    if any(k in l for k in KW):
        if '[爬梯·后脑] back=' in l: continue
        print(l[:215])
# 人物Y 时间序列(从打怪决策/战斗诊断/跨层)
print("\n===== 人物/锁定 Y 时间序列(跨层/决策) =====")
for l in seg:
    if ('[跨层]' in l) or ('状态=cross' in l) or ('到顶' in l) or ('下行]' in l and ('落地' in l or '穿到' in l)):
        print(l[:200])
# 到顶后锁怪Y差正负统计
print("\n===== 到顶/下行 计数 =====")
print("快判到顶=%d  恢复锁怪=%d  进上梯=%d  自由落体落地=%d  方式一下跳=%d  方式二=%d" % (
 sum('快判到顶' in l for l in seg),sum('恢复锁怪' in l for l in seg),sum('进纯屏幕上梯' in l for l in seg),
 sum('自由落体' in l and '落地' in l for l in seg),sum('下行·方式一' in l and '第二跳' in l for l in seg),sum('下行·方式二' in l for l in seg)))
