# -*- coding: utf-8 -*-
import io
p=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log.bak"
L=io.open(p,'r',encoding='utf-8',errors='replace').read().splitlines()
# 从 23:44:28 起,去噪
NOISE=['识别B耗时','截图耗时','血条检测','空槽判定','HP检测','MP检测','田字诊断','光点测速','光点锁定','角色跟踪','怪物蒙板','窗口固定','FPS统计','draw分段','主循环分段','打怪区域','人物耗时','黑框方向','蒙板同步','战斗诊断','光点]','帧]','YOLO']
start=None
for i,l in enumerate(L):
    if l.startswith('[23:44:28]') or l.startswith('[23:44:29]') or l.startswith('[23:44:3'):
        start=i; break
print("起始行",start,"总行",len(L))
for l in L[start:]:
    if any(n in l for n in NOISE): continue
    print(l[:160])
