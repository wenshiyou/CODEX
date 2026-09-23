# -*- coding: utf-8 -*-
# 离线验证(只读,不import重模块):AST抽落盘真实 _ladder_mm_height_ok/_pick_ladder_minimap,
# 喂真实 route_005_ladders.json + 合成边界数据;并对到顶/下行落盘表达式做真值表断言。
import ast, io, json, textwrap, os

ROOT = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"
SRC = io.open(os.path.join(ROOT, "maple_route_ui.py"), "rb").read().decode("utf-8-sig")
tree = ast.parse(SRC)

CONST_NAMES = ["LADDER_MM_X_HALF", "LADDER_MM_Y_HALF", "LADDER_MM_END_TOL",
               "LADDER_MM_SAME_COL_X", "LADDER_MM_SAME_COL_OV", "LADDER_MM_MIN_LEN",
               "LADDER_REC_SAME_COL_X", "LADDER_TOP_ARRIVE_TOL", "BACK_TOP_LOST_MS",
               "LADDER_TOP_HOLD_MS"]
consts = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        n = node.targets[0].id
        if n in CONST_NAMES:
            consts[n] = ast.literal_eval(node.value)
print("常量:", {k: consts[k] for k in consts})

cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MinimapRouteRecorder")
def method_src(name):
    for n in cls.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(SRC, n)
    raise RuntimeError("missing " + name)

h_src = textwrap.dedent(method_src("_ladder_mm_height_ok"))
p_src = textwrap.dedent(method_src("_pick_ladder_minimap"))

ns = {}
exec("\n".join("%s=%r" % (k, v) for k, v in consts.items()), ns)
exec(h_src, ns)
height = ns["_ladder_mm_height_ok"]

class Shim:
    _ladder_mm_height_ok = staticmethod(height)
ns["MinimapRouteRecorder"] = Shim
exec(p_src, ns)
pick = ns["_pick_ladder_minimap"]

fails = []
def chk(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)

def T(x, t, b, idv=None):
    return {"id": idv if idv is not None else (x, t, b), "x": x, "y_top": t, "y_bottom": b}

# ---------- 高度门:重合±1 ----------
lad = T(100, 80, 100)  # 梯 x100 顶80 底100 长20
chk(height(lad, 100, +1) is True,  "上行光点恰在梯底y=100->重合合格")
chk(height(lad, 101, +1) is True,  "上行光点y=101(差1)->合格")
chk(height(lad, 99,  +1) is True,  "上行光点y=99(差1,在梯内)->合格")
chk(height(lad, 102, +1) is False, "上行光点y=102(差2,人低于梯底)->不合格(旧值10会误放)")
chk(height(lad, 90,  +1) is False, "上行光点y=90(悬在梯身中段,|底-光|=10)->不合格(旧值10误选悬头顶)")
chk(height(T(100,100,120), 100, -1) is True,  "下行光点恰在梯顶y=100->合格")
chk(height(T(100,100,120), 99,  -1) is True,  "下行光点y=99(差1)->合格")
chk(height(T(100,100,120), 98,  -1) is False, "下行光点y=98(差2)->不合格")
chk(height(T(100,80,82), 82, +1) is False, "梯长2<MIN_LEN=5->噪点否")

# ---------- 选梯:悬头上段必须排除(用户事故回归) ----------
# 同列上下两段:下段 x76 顶74底87;上段(悬头顶) x73 顶65底72;人在下层光点y=87
low  = T(76, 74, 87, idv="low")
high = T(73, 65, 72, idv="high")
got = pick([high, low], 76, 87, +1, None)
chk(got is not None and got["id"] == "low", "同列两段+人在下层:只选起步下段low,悬头上段high被重合门排除(得=%s)" % (got and got["id"]))

# 光点在高层 y=72 时,上段high底端72重合、下段low底端87差15->只选high
got2 = pick([high, low], 73, 72, +1, None)
chk(got2 is not None and got2["id"] == "high", "人已到高层y=72:只选high(得=%s)" % (got2 and got2["id"]))

# ---------- 并排梯(Y区间重叠)不互吞,按X最近 ----------
a = T(73, 60, 72, idv="A")   # 右
b = T(59, 60, 72, idv="B")   # 左,与A同y、X差14
chk(pick([a, b], 72, 72, +1, None)["id"] == "A", "光点x=72:并排梯选更近的A")
chk(pick([a, b], 60, 72, +1, None)["id"] == "B", "光点x=60:并排梯选更近的B")

# ---------- side_sign 怪侧优先 ----------
L = T(40, 80, 100, idv="L"); R = T(160, 80, 100, idv="R")
chk(pick([L, R], 100, 100, +1, +1)["id"] == "R", "怪在右(side+1):选右梯R")
chk(pick([L, R], 100, 100, +1, -1)["id"] == "L", "怪在左(side-1):选左梯L")

# ---------- X带 ----------
far = T(200, 80, 100, idv="far")
chk(pick([far], 100, 100, +1, None) is None, "梯X差100>X_HALF=60->选空")

# ---------- 单段零回归(真实数据) ----------
real = json.load(io.open(os.path.join(ROOT, "data", "route_005_ladders.json"), "r", encoding="utf-8-sig"))
if isinstance(real, dict):
    real = real.get("ladders", real)
print("真实梯数:", len(real))
for t in real:
    print("  真实梯 id=%s x=%s top=%s bot=%s len=%s" % (t.get("id"), t["x"], t["y_top"], t["y_bottom"], t["y_bottom"]-t["y_top"]))
for t in real:
    if (t["y_bottom"] - t["y_top"]) >= consts["LADDER_MM_MIN_LEN"]:
        ok = height(t, t["y_bottom"], +1)
        chk(ok is True, "真实梯id=%s 光点在其底端必合格" % t.get("id"))
        g = pick([t], float(t["x"]), float(t["y_bottom"]), +1, None)
        chk(g is not None, "真实梯id=%s 单独候选必被选中" % t.get("id"))

# 真实同列:取每列最下段,光点在最下段底端,选中必须是该最下段(不选悬头上段)
cols = {}
for t in real:
    if (t["y_bottom"] - t["y_top"]) < consts["LADDER_MM_MIN_LEN"]:
        continue
    placed = False
    for cx in list(cols):
        if abs(float(t["x"]) - cx) <= consts["LADDER_MM_SAME_COL_X"]:
            cols[cx].append(t); placed = True; break
    if not placed:
        cols[float(t["x"])] = [t]
for cx, members in cols.items():
    if len(members) < 2:
        continue
    bottom = max(members, key=lambda z: z["y_bottom"])
    g = pick(real, float(bottom["x"]), float(bottom["y_bottom"]), +1, None)
    chk(g is not None and g["id"] == bottom["id"],
        "真实同列(x~%.0f,%d把)人在最下段底端:选最下段id=%s(得=%s)" % (cx, len(members), bottom.get("id"), g and g.get("id")))

# ---------- 到顶真值表(复刻落盘表达式 6240/6253/6254) ----------
TOL = consts["LADDER_TOP_ARRIVE_TOL"]
def map_ok_up(py, end_y, bv, up=True):
    dot = bool(end_y) and abs(py - end_y) <= TOL
    return bool(up and bool(end_y) and dot and (not bv))
def map_ok_down(py, end_y, up=False):
    return bool((not up) and bool(end_y) and py >= end_y - TOL)
chk(map_ok_up(72, 72, False) is True,  "到顶:差0+后脑不可见->判到顶")
chk(map_ok_up(73, 72, False) is True,  "到顶:差1+后脑不可见->判到顶(补按150)")
chk(map_ok_up(71, 72, False) is True,  "到顶:越过1px差1+后脑不可见->判到顶")
chk(map_ok_up(72, 72, True)  is False, "重合但后脑仍可见=没翻出->不判,继续按↑")
chk(map_ok_up(74, 72, False) is False, "梯中差2+后脑不可见=漏检->不判,继续按↑")
chk(map_ok_up(67, 72, False) is False, "还差5+后脑不可见->不判")
chk(map_ok_up(72, 0,  False) is False, "坏梯end_y=0不走快判(退回纯后脑450/总超时)")
chk(map_ok_down(72, 72) is True, "下行到底:py=end_y->判")
chk(map_ok_down(80, 72) is True, "下行越过:py>end_y->判")
chk(map_ok_down(70, 72) is False,"下行差2未到底->不判")

print("\n" + ("ALL PASS" if not fails else ("%d FAIL: %s" % (len(fails), fails))))
raise SystemExit(1 if fails else 0)
