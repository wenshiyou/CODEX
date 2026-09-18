# -*- coding: utf-8 -*-
"""阶段一 _publish_combat_intent / _compute_locked_rect 离线冒烟(不起GUI)。
AST从maple_route_ui.py抽两个方法源码,dedent后在提供 combat_logic/常量 的命名空间exec,用fake self调用。"""
import ast, io, textwrap, types, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import combat_logic  # noqa

PATH = os.path.join(ROOT, "maple_route_ui.py")
text = io.open(PATH, encoding="utf-8-sig").read()
tree = ast.parse(text)
ns = {"combat_logic": combat_logic,
      "ATTACK_Y_UP": 60, "ATTACK_Y_DOWN": 30, "AOE_Y_UP": 120, "AOE_Y_DOWN": 100}
import time
ns["time"] = time
got = {}
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == "MinimapRouteRecorder":
        for fn in node.body:
            if isinstance(fn, ast.FunctionDef) and fn.name in ("_publish_combat_intent", "_compute_locked_rect"):
                src = textwrap.dedent(ast.get_source_segment(text, fn))
                exec(src, ns)
                got[fn.name] = ns[fn.name]
assert set(got) == {"_publish_combat_intent", "_compute_locked_rect"}, got

def box(cx, cy, w=40, h=80, s=0.9):
    return (cx - w // 2, cy - h, cx + w // 2, cy, s)

class Fake:
    def __init__(self):
        self._selected_platforms = []
        self._slope_high_blocked = False
        self._b_next_anchor = None
        self._combat_intent_packet = None
        self._locked_box_cache = None
        self._monsters = []
    def _get_monster_platform(self, *a, **k):
        return None

fc = {"atk1_distance": 150, "attack_y_up": -60, "attack_y_down": 30}
fails = []
def ck(tag, cond, extra=""):
    print(("[%s] %s %s" % ("PASS" if cond else "FAIL", tag, extra)))
    if not cond:
        fails.append(tag)

# 场景1:current=in怪,另有out怪 → next=out怪(排除current)
f = Fake(); f._combat_locked_target = (560, 500)
got["_publish_combat_intent"](f, (500, 500), [box(560, 500), box(700, 500)], None, fc)
ck("S1 next排除current选out", f._combat_intent_packet["next"] == (700, 500)
   and f._combat_intent_packet["next_tier"] == "out", str(f._combat_intent_packet["next"]))

# 场景2:无current,只有in怪 → next=in,锚点in
f = Fake()
got["_publish_combat_intent"](f, (500, 500), [box(560, 500)], None, fc)
ck("S2 无current选in", f._combat_intent_packet["next"] == (560, 500)
   and f._combat_intent_packet["next_tier"] == "in" and f._b_next_anchor[2] == "in")

# 场景3:in锚点钉身份、坐标随新框刷新(怪抖到563,502)
f = Fake(); f._b_next_anchor = (560, 500, "in")
got["_publish_combat_intent"](f, (500, 500), [box(563, 502)], None, fc)
ck("S3 in锚点钉身份刷新坐标", f._combat_intent_packet["next"] == (563, 502)
   and f._combat_intent_packet["next_tier"] == "in", str(f._combat_intent_packet["next"]))

# 场景4:in锚点怪消失、表空 → next None、锚点清空
f = Fake(); f._b_next_anchor = (560, 500, "in")
got["_publish_combat_intent"](f, (500, 500), [], None, fc)
ck("S4 in锚点脱检清空", f._combat_intent_packet is None and f._b_next_anchor is None)

# 场景5:in锚点转正成current(锚点≈current) → 弃锚,按排除current重选(另一只out)
f = Fake(); f._b_next_anchor = (560, 500, "in"); f._combat_locked_target = (560, 500)
got["_publish_combat_intent"](f, (500, 500), [box(560, 500), box(700, 500)], None, fc)
ck("S5 锚点转正后改选out", f._combat_intent_packet["next"] == (700, 500),
   str(f._combat_intent_packet["next"]))

# 场景6:ch None → 清空
f = Fake()
got["_publish_combat_intent"](f, None, [box(560, 500)], None, fc)
ck("S6 无人点清空", f._combat_intent_packet is None and f._b_next_anchor is None)

# _compute_locked_rect:在表用检测框+缓存宽高
f = Fake(); f._monsters = [box(560, 500)]
r = got["_compute_locked_rect"](f, (560, 500))
ck("R1 在表用检测框", r == (540, 420, 580, 500) and f._locked_box_cache == (40, 80), str(r))
# 脱检用缓存补位
r2 = got["_compute_locked_rect"](f, (900, 900))
ck("R2 脱检缓存补位", r2 == (880, 820, 920, 900), str(r2))
# 无锁 None
ck("R3 空锁None", got["_compute_locked_rect"](f, None) is None)

print("\n" + ("全部通过" if not fails else ("失败:%s" % fails)))
sys.exit(1 if fails else 0)
