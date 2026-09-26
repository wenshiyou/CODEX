# -*- coding: utf-8 -*-
import ast
from collections import Counter
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
t = ast.parse(open(P, encoding="utf-8-sig").read())
dups = []
for c in ast.walk(t):
    if isinstance(c, ast.ClassDef):
        names = [n.name for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for k, v in Counter(names).items():
            if v > 1:
                dups.append((c.name, k, v))
top = [n.name for n in t.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
for k, v in Counter(top).items():
    if v > 1:
        dups.append(("TOP", k, v))
# 关键方法定义数
want = ["_manual_tp_leaves_platform", "_combat_at_locked_edge", "_roam_tick", "_locked_platform_x_range"]
cnt = {w: 0 for w in want}
for c in ast.walk(t):
    if isinstance(c, ast.ClassDef):
        for n in c.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in cnt:
                cnt[n.name] += 1
print("DUP_TOTAL=%d %s" % (len(dups), dups))
print("DEFS=", cnt)
