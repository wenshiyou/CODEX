# -*- coding: utf-8 -*-
# 阶段1逻辑验证(不依赖游戏): metric几何通路/兜底等价/cross新阈值/开关关=idle
import sys
sys.path.insert(0, r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2")
import combat_logic as cl

PX, PY = 500, 500
SKILL = 200

def box(cx, cy, w=40, h=40, score=0.9):
    return (cx - w // 2, cy - h, cx + w // 2, cy, score)

def metric_for(mons, px=PX, py=PY):
    # 复刻B线程: key=四角, value=(cx,cy,x_gap,dy)
    d = {}
    for (x1, y1, x2, y2, s) in mons:
        cx, cy = (x1 + x2) // 2, y2
        d[(x1, y1, x2, y2)] = (cx, cy, abs(cx - px), cy - py)
    return d

def sel(mons, metric=None, allow_cross=True, lock=None):
    return cl.select_combat_target(
        PX, PY, mons, [], SKILL, 500,
        (lock[0] if lock else None), (lock[1] if lock else None), False,
        lambda *a: True, lambda *a: None,
        1, False, None, 60, 30, allow_cross,
        0, 0, False, None, False, 0,
        None, None, False, same_platform_fn=None, metric=metric)

def show(tag, r):
    print("%-28s state=%-7s target=%s dist=%s tier=%s" % (
        tag, r['state'], r['target'], r['dist'], r.get('tier')))

A = box(550, 520)          # 同层近身  x_gap50 dy20   -> cast
B = box(600, 250)          # 上层跨层  x_gap100 dy-250 -> cross
C = box(900, 300)          # 又远又高  x_gap400 dy-200 -> cand/pursue(先走近)
D = box(520, 320)          # 上层但Y差180(<200) x20   -> cand(跳高/走近,不cross)

print("=== 1) metric通路 vs 兜底现算 必须同结果 ===")
for name, mons in [("仅同层A", [A]), ("仅跨层B", [B]), ("仅远怪C", [C]),
                   ("Y差180怪D", [D]), ("同层+跨层A+B", [A, B]), ("跨层+远怪B+C", [B, C])]:
    r_none = sel(mons, metric=None)            # 主线程兜底现算
    r_met = sel(mons, metric=metric_for(mons)) # B线程metric
    ok = (r_none['state'] == r_met['state'] and r_none['target'] == r_met['target'])
    show(name + " [兜底]", r_none)
    show(name + " [B-metric]", r_met)
    print("    --> %s" % ("一致 OK" if ok else "!!! 不一致 FAIL"))
    assert ok, "metric与兜底结果不一致: " + name

print("=== 2) cross新阈值断言 ===")
assert sel([B], metric=metric_for([B]))['state'] == 'cross', "B(Y250/X100)必须cross"
assert sel([C], metric=metric_for([C]))['state'] == 'pursue', "C(X400)必须先走近不cross"
rD = sel([D], metric=metric_for([D]))
assert rD['state'] != 'cross', "D(Y180<200)不许cross"
# 同层有怪时绝不上梯
assert sel([A, B], metric=metric_for([A, B]))['state'] == 'cast', "身边同层A在,必须先打A不cross"
print("cross阈值全部符合(200/300、同层优先) OK")

print("=== 3) 开关关=packet空=idle(不打不巡) ===")
r_empty = sel([], metric={})
assert r_empty['state'] == 'idle', "空怪必须idle"
show("空怪列表", r_empty)
print("开关关(空packet) -> idle OK")

print("=== 4) allow_cross=False(上梯期间) 跨层怪不进cross ===")
r_no = sel([B], metric=metric_for([B]), allow_cross=False)
print("allow_cross=False 时 B -> state=%s (不应为cross)" % r_no['state'])
assert r_no['state'] != 'cross'

print("\nALL_STAGE1_TESTS_PASS")
