# -*- coding: utf-8 -*-
import io, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
data = io.open(P, encoding='utf-8', errors='replace').read().splitlines()
lo, hi = '02:28:04', '02:28:14'
DROP=['FPS','draw分段','主循环分段','窗口固定','空槽判定','MP界面','截图耗时','人物耗时','识别B耗时','怪物蒙板','光点测速','判活汇总','绘制','血条检测(新版','HP检测','MP检测','光点]','黑框方向','角色跟踪','光点锁定']
total=0; kept=0
for l in data:
    m = re.match(r'\[(\d{2}:\d{2}:\d{2})\]', l)
    if not m: continue
    ts=m.group(1)
    if ts < lo or ts > hi: continue
    total+=1
    if any(d in l for d in DROP): continue
    print(l); kept+=1
print("\n[原始 %d 输出 %d]"%(total,kept))
