# -*- coding: utf-8 -*-
# dump 指定时间段(HH:MM:SS-HH:MM:SS)去刷屏关键行,坐实"瞬移时有没有怪/怪在哪"
import re, io, datetime
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
t0 = ("00","06","00"); t1 = ("00","06","15")
def sec(hh,mm,ss): return int(hh)*3600+int(mm)*60+int(ss)
T0, T1 = sec(*t0), sec(*t1)
t_re = re.compile(r'(\d{1,2}):(\d{2}):(\d{2})')
DROP = ['光点]','光点锁定','田字','耗时','血条检测(新版','绘制','窗口固定','黑框方向','角色跟踪','蒙板','镜头检测','截图','主循环分段','draw分段','光点测速','人物耗时','识别B','MP界面','HP']
KEEP_HINT = ['瞬移','锁','怪','巡游','决策','pursue','追','战斗诊断','梯','cross','攻击','主攻','群攻','cast','越线','回退','关锁','重锁','判活','伤害探针','transit','移动']
out=[]
for ln in io.open(P,encoding='utf-8',errors='replace').read().splitlines():
    m=t_re.search(ln)
    if not m: continue
    t=sec(*m.groups())
    if not (T0<=t<=T1): continue
    if any(d in ln for d in DROP): continue
    if any(k in ln for k in KEEP_HINT):
        out.append(ln)
io.open(r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\_seg.txt","w",encoding="utf-8").write("\n".join(out))
print("kept=%d"%len(out))
