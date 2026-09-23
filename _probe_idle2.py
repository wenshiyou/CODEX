# -*- coding: utf-8 -*-
import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
LOG=r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
lines=open(LOG,'rb').read().decode('utf-8','replace').splitlines()
def sec(l):
    m=re.match(r'\[(\d\d):(\d\d):(\d\d)\]',l)
    return (int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)),m.group(0)) if m else (None,None)
tail=lines[-6000:]
# 末尾时间
end=None
for l in reversed(tail):
    s,_=sec(l)
    if s is not None: end=s; break
win=[]
for l in tail:
    s,ts=sec(l)
    if s is None: continue
    d=end-s
    if 0<=d<=150:   # 最近150s,同段不倒流
        win.append((d,ts,l))
win.sort(key=lambda x:-x[0])  # 按时间正序(d大=早)
NOISE=['光点','角色跟踪','FPS','主循环分段','识别B耗时','人物耗时','截图耗时','窗口固定','镜头检测','光点测速','怪物蒙板','蒙板同步','黑框方向','光点锁定','伤害探针','空怪诊断','MP检测','HP检测','血条检测','MP界面','MP遮挡','人物匹配','加药','加载','模板','人物定位','判活汇总','攻击判定','战斗诊断']
print("末尾时间=%s 窗口条数=%d"%(ts if end else '?', len(win)))
# 关键事件最后出现(距末尾秒)
def last_d(k):
    for d,ts,l in win:
        if k in l: return (d,l[:170])
    return None
for k in ['发键','[主攻]','[打怪决策]','瞬移','[跨层','爬梯','选梯','锁怪开关','跨层卡住','cross_wait','fail_pause','到顶','到新平台','[锁定梯]','实行跳高打','[下行','下跳','梯/台段结束']:
    r=last_d(k)
    print(("最后%-10s 距今%3ds  %s"%(k, r[0], r[1])) if r else ("最后%-10s 无"%k,))
print("\n== 最近150s 行为序列(非噪声) ==")
for d,ts,l in win:
    if any(n in l for n in NOISE): continue
    print("-%3ds %s"%(d,l[:190]))
