# -*- coding-utf -*-
# 只读诊断:空打/判死链路。聚合 debug.log 最近运行段,只回数字与关键原文。
import io, re, sys, time, os

LOG = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0

lines = io.open(LOG, encoding="utf-8", errors="replace").read().splitlines()
def hms(s):
    m = re.match(r"^(\d{2}):(\d{2}):(\d{2})", s)
    if not m: return None
    h, mi, se = (int(x) for x in m.groups())
    return h*3600+mi*60+se

# 取最后一条时间戳作为"现在"
last_t = None
for l in reversed(lines):
    m = re.search(r"\[(\d{2}):(\d{2}):(\d{2})\]", l)
    if m:
        h, mi, se = (int(x) for x in m.groups()); last_t = h*3600+mi*60+se; break
cut = (last_t - MIN*60) if last_t is not None else -1

atk_t, aoe_t = [], []
probe_true, probe_false = 0, 0
false_reason = {}
probe_rows = []
summaries = []
bd_rows = []
run_rows = []
lock_rows = []
for l in lines:
    m = re.search(r"\[(\d{2}):(\d{2}):(\d{2})\]", l)
    if not m: continue
    h, mi, se = (int(x) for x in m.groups()); t = h*3600+mi*60+se
    if t < cut: continue
    ts = "%02d:%02d:%02d" % (h, mi, se)
    if "[主攻]" in l and "释放" in l: atk_t.append(ts)
    if "[群攻]" in l and "释放" in l: aoe_t.append(ts)
    if "[伤害探针]" in l:
        hitT = "探针见字=True" in l
        if hitT: probe_true += 1
        else: probe_false += 1
        rm = re.search(r"原因=(\S+)", l)
        if rm and not hitT: false_reason[rm.group(1)] = false_reason.get(rm.group(1),0)+1
        probe_rows.append((ts, l))
    if "[判活汇总]" in l: summaries.append((ts, l))
    if ("[B决策]" in l) or ("drop" in l) or ("空怪" in l) or ("判死" in l) or ("无血无伤" in l) or ("放弃" in l and "怪" in l):
        bd_rows.append((ts, l))
    if ("锁定" in l) or ("换锁" in l) or ("换目标" in l) or ("重选" in l):
        lock_rows.append((ts, l))
    if ("运行=" in l) or ("F10" in l) or ("F12" in l) or ("开始运行" in l) or ("停止" in l) or ("MP界面" in l) or ("底部横带" in l):
        run_rows.append((ts, l))

print("=== 范围 最后%.0f分钟 (截至%s) 总行%d ===" % (MIN, ("%02d:%02d:%02d"%(last_t//3600,last_t%3600//60,last_t%60)) if last_t else "?", len(lines)))
print("主攻释放=%d 群攻释放=%d" % (len(atk_t), len(aoe_t)))
if atk_t: print("主攻时间(末30):", ",".join(atk_t[-30:]))
if aoe_t: print("群攻时间(末20):", ",".join(aoe_t[-20:]))
print("伤害探针: 见字True=%d 无False=%d  False原因分布=%s" % (probe_true, probe_false, false_reason))
print("\n--- 判活汇总(末12) ---")
for ts,l in summaries[-12:]: print(l[:240])
print("\n--- 伤害探针原文(末22) ---")
for ts,l in probe_rows[-22:]: print(l[:260])
print("\n--- B决策/drop/空怪/放弃(末22) ---")
for ts,l in bd_rows[-22:]: print(l[:240])
print("\n--- 锁定/换锁/重选(末20) ---")
for ts,l in lock_rows[-20:]: print(l[:200])
print("\n--- 运行/前后台(末15) ---")
for ts,l in run_rows[-15:]: print(l[:180])
