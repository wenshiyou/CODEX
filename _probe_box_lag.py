# -*- coding: utf-8 -*-
# 量化框/锁延迟: 取最后运行段(F10后、MP前台)的FPS统计(YOLO ms/秒)、锁怪->出手间隔
import io, os, re, time, statistics
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines = io.open(P,'rb').read().decode('utf-8','replace').replace('\r\n','\n').split('\n')
print("总行数", len(lines))

# 时间戳解析 [HH:MM:SS]
def ts(l):
    m = re.match(r'\[(\d{2}):(\d{2}):(\d{2})\]', l)
    return int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)) if m else None

# 找最后一个 F10/运行开始 锚点(用[初始化]或'运行=True'或'F10')
run_idx = [i for i,l in enumerate(lines) if re.search(r'(\[初始化\]|开始运行|运行=True|F10|启动战斗)', l)]
seg_start = run_idx[-1] if run_idx else max(0,len(lines)-4000)
seg = lines[seg_start:]
print("最后运行段起始行%d, 行数%d" % (seg_start+1, len(seg)))

# 前台判定: MP横带匹配度
mp = [float(x) for l in seg for x in re.findall(r'底部横带匹配度([0-9.]+)', l)]
print("MP横带样本%d, 最大%.2f, >0.85占比%.0f%%" % (len(mp), max(mp or [0]),
      100*sum(1 for x in mp if x>=0.85)/max(1,len(mp))))

# FPS统计: 帧率/人物匹配/YOLO/绘制
fps_rows=[]
for l in seg:
    m = re.search(r'\[FPS统计\]\s*帧率=([0-9.]+).*?人物匹配=([0-9]+)ms.*?YOLO=([0-9]+)ms.*?绘制=([0-9]+)ms', l)
    if m:
        fps_rows.append(tuple(float(m.group(i)) for i in range(1,5)))
print("FPS统计样本%d" % len(fps_rows))
if fps_rows:
    for idx,name in [(0,'帧率'),(1,'人物匹配ms/秒'),(2,'YOLO ms/秒'),(3,'绘制ms/秒')]:
        vals=[r[idx] for r in fps_rows]
        print("  %-14s 均值%.1f 最大%.1f 末5:%s" % (name, statistics.mean(vals), max(vals), [round(v) for v in vals[-5:]]))

# 锁怪/决策 与 攻击/出手 时间线(最后60条相关行)
kw = re.compile(r'(\[打怪决策\]|锁定|出手|攻击|空怪|drop|YOLO推理|怪物=|识别到)', re.I)
rel=[l for l in seg if kw.search(l)]
print("\n相关日志最后30条:")
for l in rel[-30:]:
    print(l[:160])
