# -*- coding: utf-8 -*-
# 诊断"打着打着不动了": 最后运行段 + 最后3分钟窗口, 卡住点时间线/异常/最后动作
import io, re
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines = io.open(P,'rb').read().decode('utf-8','replace').replace('\r\n','\n').split('\n')
def ts(l):
    m = re.match(r'\[(\d{2}):(\d{2}):(\d{2})\]', l)
    return int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)) if m else None
def hms(t): return "%02d:%02d:%02d"%(t//3600,(t%3600)//60,t%60)

anch=[i for i,l in enumerate(lines) if re.search(r'(\[初始化\]|开始运行|运行=True|F10|启动战斗|开始挂机)', l)]
ai = anch[-1] if anch else max(0,len(lines)-6000)
seg = lines[ai:]
tseg=[ts(l) for l in seg if ts(l)]
t_end=max(tseg)
win_t=t_end-180
print("=== 运行段 ===")
print("锚点行%d/%d: %s" % (ai+1, len(lines), lines[ai][:120]))
print("段末时间 %s, 最后3分钟窗起点 %s, 段行数%d" % (hms(t_end), hms(win_t), len(seg)))
mp=[float(x) for l in seg for x in re.findall(r'底部横带匹配度([0-9.]+)', l)]
print("MP样本%d 最大%.2f 前台(>=0.85)占比%.0f%%" % (len(mp), max(mp or [0]), 100*sum(1 for x in mp if x>=0.85)/max(1,len(mp))))

# 异常/Traceback 全文
print("\n=== 异常块 ===")
for i,l in enumerate(seg):
    if re.search(r'Traceback|Exception|Error|错误|异常:', l):
        for j in range(i, min(i+8,len(seg))):
            print(seg[j][:180])
        print('-'*40)

# 关键事件时间线(最后3分钟窗内)
kw = re.compile(r'(打怪决策|锁定|锁怪|B锁|出手|攻击|空怪|drop|换目标|移动|瞬移|巡游|roam|卡住|解卡|受阻|停滞|发呆|cross|梯|climb|爬|上梯|下跳|transit|角色跟踪|跳变拦截|周期|YOLO|光点|镜头|线程|超时|放弃|重锁|清锁)')
win=[l for l in seg if (ts(l) and ts(l)>=win_t)]
ev=[l for l in win if kw.search(l)]
print("\n=== 最后3分钟关键事件 共%d条(打印末70) ===" % len(ev))
for l in ev[-70:]:
    print(l[:170])

# 末尾原文(卡住当下)
print("\n=== 运行段末尾90行原文 ===")
for l in [x for x in seg if x.strip()][-90:]:
    print(l[:170])
