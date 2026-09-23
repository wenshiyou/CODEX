# -*- coding: utf-8 -*-
# 精准定位"不动": 战斗动作时间线何时断 + 每秒CPU账 + 退避/拦截 + 光点是否恒定
import io, re, collections
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines = io.open(P,'rb').read().decode('utf-8','replace').replace('\r\n','\n').split('\n')
def ts(l):
    m=re.match(r'\[(\d{2}):(\d{2}):(\d{2})\]',l)
    return int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)) if m else None
def hm(t):return "%02d:%02d:%02d"%(t//3600,(t%3600)//60,t%60)
anch=[i for i,l in enumerate(lines) if re.search(r'(\[初始化\]|开始运行|运行=True|F10|启动战斗)',l)]
ai=anch[-1]; seg=lines[ai:]

ACT=re.compile(r'(战斗诊断|打怪决策|出手|攻击|发键|按键|方向|移动|瞬移|cross|上梯|下跳|爬梯|climb|transit|卡住|解卡|发呆|停滞|巡游|roam|drop|空怪|重锁|清锁|relock|保护|跳变拦截|忙帧|退避|到顶|后脑|锁怪|锁定=|B锁|换目标|走近|走位|转身)')
acts=[(ts(l),l) for l in seg if ts(l) and ACT.search(l)]
print("=== 战斗/控制类动作 最后55条 ===")
for t,l in acts[-55:]:
    print(hm(t), l[:160])

# 每秒: 帧率/绘制/人物匹配/截图/YOLO + 战斗动作条数
per=collections.defaultdict(lambda:{'fps':None,'draw':0,'person':0,'cap':0,'yolo':0,'act':0,'back':0,'block':0})
for l in seg:
    t=ts(l)
    if not t: continue
    m=re.search(r'帧率=([0-9.]+).*?绘制=([0-9]+)ms',l)
    if m: per[t]['fps']=float(m.group(1)); per[t]['draw']=int(m.group(2))
    m=re.search(r'人物匹配([0-9]+) \(ms/秒\)',l) or re.search(r'人物匹配([0-9]+)ms',l)
    if m: per[t]['person']=int(m.group(1))
    m=re.search(r'周期忙 截图([0-9]+)',l)
    if m: per[t]['cap']=int(m.group(1))
    m=re.search(r'YOLO([0-9]+) ',l)
    if m: per[t]['yolo']=int(m.group(1))
    if '退避' in l: per[t]['back']+=1
    if '跳变拦截' in l: per[t]['block']+=1
    if ACT.search(l): per[t]['act']+=1
print("\n=== 每秒账(最后25秒) 秒: fps/绘制/人物/截图/YOLO ms/秒, 动作条数, 退避, 拦截 ===")
for t in sorted(per)[-25:]:
    d=per[t]
    print("%s fps=%s draw=%d person=%d cap=%d yolo=%d 动作=%d 退避=%d 拦截=%d"%(
        hm(t),d['fps'],d['draw'],d['person'],d['cap'],d['yolo'],d['act'],d['back'],d['block']))

# 退避/拦截 全段统计
back=[(ts(l),l) for l in seg if '退避' in l or '忙帧' in l]
blk=[(ts(l),l) for l in seg if '跳变拦截' in l]
print("\n退避/忙帧 %d条, 跳变拦截 %d条"%(len(back),len(blk)))
for t,l in back[-8:]: print(" 退避",hm(t),l[:130])
for t,l in blk[-8:]: print(" 拦截",hm(t),l[:130])

# 光点是否钉死
dots=re.findall(r'光点\] 中心=\(([-\d]+),([-\d]+)\) 候选团=\d+ 面积=\[(\d+)\]', '\n'.join(seg))
if dots:
    uniq=set((x,y) for x,y,_ in dots)
    print("\n光点样本%d 唯一位置%d个, 末10:%s"%(len(dots),len(uniq),dots[-10:]))
# 最后一条战斗动作 vs 段末时间
if acts:
    print("\n最后战斗动作 %s, 段末 %s, 静默%.0f秒"%(hm(acts[-1][0]),hm(max(ts(l) for l in seg if ts(l))),
          max(ts(l) for l in seg if ts(l))-acts[-1][0]))
