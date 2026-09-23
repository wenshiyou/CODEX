# -*- coding: utf-8 -*-
import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
LOG=r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
lines=open(LOG,'rb').read().decode('utf-8','replace').splitlines()
# 锚点(按行号,不按秒排序)
anchors=[(i,l[:120]) for i,l in enumerate(lines) if ('[初始化] 路线=' in l or '战斗已启动(F10)' in l or '[启动] F10' in l or '战斗已停止(F12)' in l or '[停止] F12' in l)]
print("== 启停/初始化锚点(最后8个) ==")
for i,l in anchors[-8:]: print("行%d %s"%(i,l))
# 最后一次 直跳3次
p3=[i for i,l in enumerate(lines) if '直跳3次仍没抓住' in l or '直跳%d次仍没抓住' in l]
print("\n直跳3次行号:",p3[-5:])
NOISE=['光点','角色跟踪','FPS','主循环分段','识别B耗时','人物耗时','截图耗时','窗口固定','镜头检测','光点测速','怪物蒙板','蒙板同步','黑框方向','光点锁定','伤害探针','空怪诊断','维护','田字','背景','MP界面','MP遮挡','人物匹配','加药','配置','鼠标','加载','模板']
if p3:
    p=p3[-1]
    print("\n== 最后一次直跳3次(行%d) 前260行~后15行 的行为序列 =="%p)
    for i in range(max(0,p-260), min(len(lines),p+15)):
        l=lines[i]
        if any(n in l for n in NOISE): continue
        m=re.match(r'\[\d\d:\d\d:\d\d\]',l)
        if not m: continue
        print("行%d %s"%(i,l[:195]))
else:
    print("\n!! 文件中已无'直跳3次'记录(被5分钟滚动清掉),无法取前序")
    # 打印文件最后40条非噪声行看当前状态
    print("== 文件末尾40条非噪声 ==")
    c=0
    for l in reversed(lines):
        if any(n in l for n in NOISE): continue
        if not re.match(r'\[\d\d:\d\d:\d\d\]',l): continue
        print(l[:195]); c+=1
        if c>=40: break
