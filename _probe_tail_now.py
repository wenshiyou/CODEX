# -*- coding: utf-8 -*-
# 物理行228563(最后停止锚,昨晚22:14)之后=今天追加段。按物理行序看当前真实状态。
import io, re
p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
rows = io.open(p, "rb").read().decode("utf-8", "ignore").splitlines()
ts = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\]")
def t(l):
    m = ts.match(l); return (int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3))) if m else None
def hh(x): return "%02d:%02d:%02d" % ((x//3600)%24,(x//60)%60,x%60)

seg = rows[228564:]
tt = [(i,t(l)) for i,l in enumerate(seg) if t(l) is not None]
print("今天段行数:", len(seg), " 时间范围(物理序):", hh(tt[0][1]), "~", hh(tt[-1][1]))
# 物理序时间是否单调
bad = sum(1 for k in range(1,len(tt)) if tt[k][1] < tt[k-1][1])
print("物理序时间回退点数:", bad)

cnt = {"发键":0,"打怪决策":0,"主攻":0,"田字诊断":0,"怪分类":0,"随机/启停":0,"跨层":0,"爬梯":0,"跳高打":0,"瞬移":0,"巡游":0,"移动卡住":0}
last = {k:None for k in cnt}
for l in seg:
    x = t(l)
    def mark(k,key):
        if key in l:
            cnt[k]+=1; last[k]=x
    mark("发键","发键 "); mark("打怪决策","[打怪决策]"); mark("主攻","[主攻]"); mark("田字诊断","[田字诊断]")
    mark("怪分类","[怪分类]"); mark("跨层","[跨层]"); mark("爬梯","[爬梯"); mark("跳高打","[跳高打]")
    mark("瞬移","[瞬移"); mark("巡游","[巡游]"); mark("移动卡住","[移动] 卡住")
    if ("模式已停止" in l or "已启动" in l or "已触发" in l or "仅启动战斗" in l):
        cnt["随机/启停"]+=1; last["随机/启停"]=x
end = tt[-1][1]
print("\n事件计数 / 最后出现距末尾秒:")
for k in cnt:
    print("  %-8s 次数=%-6d 最后=%s (距今%ss)" % (k, cnt[k], hh(last[k]) if last[k] else "无", (end-last[k]) if last[k] is not None else -1))

print("\n--- 物理末尾 60 条关键行为(滤田字/怪分类/MP) ---")
out=[]
for l in seg:
    if any(z in l for z in ("[田字诊断]","[怪分类]","MP 底部横带","YOLO 推理","截图","光标点=")):
        continue
    out.append(l)
for l in out[-60:]:
    print(l[:120])
