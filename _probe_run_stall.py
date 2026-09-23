# -*- coding: utf-8 -*-
# 只分析"最后一个运行段"(最后停止锚与其前最近启动锚之间, 按文件行序切, 不靠绝对时间)。
# 量化三类运行中卡顿:
#  A 纯发呆: 连续>=2s 无发键 且 人物坐标极差<12px
#  B cross绿线空转: 同交叉点"走绿线组合路径"在短时间反复刷、人物X几乎不动
#  C 跳高打空转: 连续[跳高打]簇持续>=1.5s, 期间没有一次[主攻]出手
import io, re

p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
rows = io.open(p, "rb").read().decode("utf-8", "ignore").splitlines()

ts_re = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]")
pos_re = re.compile(r"人物=\((\d+),(\d+)\)")
cross_re = re.compile(r"绿线相连交叉点\((-?\d+),(-?\d+)\)")
START_K = ("[启动] F10", "F10 已触发", "模式已启动", "运行按钮已触发", "仅启动战斗")
STOP_K = ("模式已停止", "F12 已触发", "手动模式已停止")

def tsec(l):
    m = ts_re.match(l)
    return int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)) if m else None

def is_start(l):
    return ("已启动" in l or "已触发" in l or "仅启动战斗" in l) and any(k in l for k in START_K)
def is_stop(l):
    return any(k in l for k in STOP_K)

# 行序扫描, 记录启停锚行号
start_lns, stop_lns = [], []
for i, l in enumerate(rows):
    if is_start(l):
        start_lns.append(i)
    elif is_stop(l):
        stop_lns.append(i)

if not stop_lns:
    print("文件中没有停止锚, 无法定位最后运行段"); raise SystemExit
stop_ln = stop_lns[-1]
prev_stops = [i for i in stop_lns if i < stop_ln]
# 最近启动锚(在stop_ln前)
s = [i for i in start_lns if i < stop_ln]
start_ln = s[-1] if s else (prev_stops[-1]+1 if prev_stops else 0)
seg = [(i, tsec(rows[i]), rows[i]) for i in range(start_ln, stop_ln)]
seg = [r for r in seg if r[1] is not None]

def hh(t):
    return "%02d:%02d:%02d" % ((t//3600) % 24, (t//60) % 60, t % 60)

print("最后运行段: 行%d~%d  %s~%s  共%d行" % (
    start_ln, stop_ln, hh(seg[0][1]), hh(seg[-1][1]), len(seg)))

# 相邻时间回退(跨天/乱序)处标记不连续, 用于重置窗口
def dt_ok(a, b):
    return 0 <= (b-a) <= 60

# ---- A 纯发呆(滑动2s, 双指针) ----
print("\n--- A 纯发呆(>=2s 无发键且坐标极差<12) ---")
rec = []
for i, t, l in seg:
    rec.append((t, ("发键 " in l),
               (lambda m: (int(m.group(1)), int(m.group(2))) if m else None)(pos_re.search(l)), l))
stalls = []
L = 0
for R in range(len(rec)):
    while L < R and rec[R][0]-rec[L][0] > 2.0:
        L += 1
    # 跳过时间不连续
    window = rec[L:R+1]
    if any(not dt_ok(window[k][0], window[k+1][0]) for k in range(len(window)-1)):
        continue
    if len(window) < 3 or window[-1][0]-window[0][0] < 1.5:
        continue
    if any(r[1] for r in window):
        continue
    ps = [r[2] for r in window if r[2]]
    if len(ps) < 2:
        continue
    xs = [a for a, b in ps]; ys = [b for a, b in ps]
    if (max(xs)-min(xs)) < 12 and (max(ys)-min(ys)) < 12:
        stalls.append((window[0][0], window[-1][0]))
# 合并
merged = []
for a, b in stalls:
    if merged and a - merged[-1][1] <= 1.0:
        merged[-1] = (merged[-1][0], max(merged[-1][1], b))
    else:
        merged.append((a, b))
ma = [(a, b) for a, b in merged if b-a >= 2.0]
if not ma:
    print("  无")
for a, b in ma:
    print("  %s~%s 时长%.1fs" % (hh(a), hh(b), b-a))
    for i, t, l in seg:
        if a <= t <= b and any(k in l for k in ("[打怪决策]", "[跨层]", "[爬梯", "[选梯", "[锁怪开关]", "[巡游]", "[移动] 卡住", "[监管线]")):
            print("     ", ts_re.sub("", l).strip()[:95])

# ---- B cross 绿线空转 ----
print("\n--- B cross绿线反复重算(同交叉点簇) ---")
cluster = []
for i, t, l in seg:
    m = cross_re.search(l)
    if m:
        cluster.append((t, (m.group(1), m.group(2)), i, l))
# 按时间间隔<1.5s聚类
groups = []
for t, key, i, l in cluster:
    if groups and t - groups[-1][-1][0] <= 1.5 and groups[-1][-1][1] == key:
        groups[-1].append((t, key, i, l))
    else:
        groups.append([(t, key, i, l)])
found_b = False
for g in groups:
    if len(g) < 5:
        continue
    t0, t1 = g[0][0], g[-1][0]
    # 簇内人物X位移
    lns = [x[2] for x in g]
    xs = []
    for ii in range(lns[0], min(lns[-1]+1, len(rows))):
        m = pos_re.search(rows[ii])
        if m:
            xs.append(int(m.group(1)))
    spread = (max(xs)-min(xs)) if xs else -1
    if t1-t0 >= 1.0:
        found_b = True
        print("  交叉点%s %s~%s 持续%.1fs 刷%d次, 簇内人物X极差=%s" % (
            g[0][1], hh(t0), hh(t1), t1-t0, len(g), spread))
if not found_b:
    print("  无")

# ---- C 跳高打空转簇 ----
print("\n--- C 跳高打连续簇(只跳不攻) ---")
hj = [(t, i, l) for i, t, l in seg if "[跳高打]" in l]
hg = []
for t, i, l in hj:
    if hg and t - hg[-1][-1][0] <= 1.0:
        hg[-1].append((t, i, l))
    else:
        hg.append([(t, i, l)])
found_c = False
for g in hg:
    t0, t1 = g[0][0], g[-1][0]
    if t1-t0 < 1.5:
        continue
    atk = sum(1 for ii, tt, ll in seg if t0 <= tt <= t1 and "[主攻]" in ll)
    stages = {}
    for t, i, l in g:
        st = "wait_jump" if "wait_jump" in l else ("wait_attack" if "wait_attack" in l else "其他")
        stages[st] = stages.get(st, 0)+1
    found_c = True
    print("  %s~%s 持续%.1fs 跳高打%d行 主攻出手%d次 阶段%s" % (
        hh(t0), hh(t1), t1-t0, len(g), atk, stages))
if not found_c:
    print("  无")
