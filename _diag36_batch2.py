# -*- coding: utf-8 -*-
"""第二批删旧·只读侦察：钉死看门狗/硬重置/横跳拉回/_move_to 的当前边界、调用点、线程启动与牵连，不写盘。"""
import ast, io
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
src = io.open(P, encoding="utf-8-sig").read()
tree = ast.parse(src)
lines = src.split("\n")

func_map = {}
class MapVisitor(ast.NodeVisitor):
    def __init__(self): self.stack = []
    def _fd(self, node):
        self.stack.append(node.name)
        for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
            func_map[ln] = ".".join(self.stack)
        self.generic_visit(node)
        self.stack.pop()
    visit_FunctionDef = _fd
    visit_AsyncFunctionDef = _fd
MapVisitor().visit(tree)

def enc(ln): return func_map.get(ln, "<module>")

methods = {}
for n in ast.walk(tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        methods.setdefault(n.name, []).append(n)

def self_calls(name):
    out = []
    for c in ast.walk(tree):
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == name \
           and isinstance(c.func.value, ast.Name) and c.func.value.id == "self":
            out.append((c.lineno, enc(c.lineno)))
    return out

print("================ 1) 目标方法边界与调用点 ================")
want = ["_request_hard_reset", "_mark_hard_reset_locked", "_consume_hard_reset",
        "_hard_reset_state", "_consume_anti_jitter", "_wd_immediate_release",
        "_global_stall_watchdog", "_global_stall_reset", "_move_to",
        "_start_runtime_detection", "_stop_runtime_detection",
        "_start_detection_thread", "_stop_detection_thread"]
for name in want:
    ns = methods.get(name)
    if not ns:
        print("### %s : <不是方法/不存在>" % name)
    else:
        for n in ns:
            print("### DEF %s  %d-%d (%d行) 装饰器%d" %
                  (name, n.lineno, n.end_lineno, n.end_lineno - n.lineno + 1, len(n.decorator_list)))
    for ln, f in self_calls(name):
        print("    CALL @%-6d in %s" % (ln, f))

print("================ 2) 线程启动 (Thread target) ================")
for c in ast.walk(tree):
    if isinstance(c, ast.Call):
        fn = c.func
        fnname = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else None)
        if fnname and "Thread" in fnname:
            tgt = ""
            for kw in c.keywords:
                if kw.arg == "target":
                    try: tgt = ast.unparse(kw.value)
                    except Exception: tgt = "?"
            print("Thread @%-6d in %s  target=%s" % (c.lineno, enc(c.lineno), tgt))

print("================ 3) 关键标识符全部引用 ================")
def id_refs(names):
    hits = {n2: [] for n2 in names}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in names and isinstance(node.value, ast.Name) and node.value.id == "self":
            hits[node.attr].append(node.lineno)
        if isinstance(node, ast.Name) and node.id in names:
            hits[node.id].append(node.lineno)
    for nm in names:
        print("-- %s : %s" % (nm, hits.get(nm, [])))
id_refs(["_hard_reset_done", "_hard_reset_state", "_hard_reset_lock",
         "ENABLE_GLOBAL_STALL_FALLBACK", "_global_stall_fallback",
         "_aux_busy", "_unblocking", "_anti_jitter"])

print("================ 4) _move_to 内部调用的 self 方法（识别越权脑子）===============")
if "_move_to" in methods:
    n = methods["_move_to"][0]
    s, e = n.lineno, n.end_lineno
    print("_move_to 范围 %d-%d (%d行)" % (s, e, e - s + 1))
    seen = {}
    for c in ast.walk(n):
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name) and c.func.value.id == "self":
            seen.setdefault(c.func.attr, []).append(c.lineno)
    for m, lns in sorted(seen.items()):
        print("    调 %-28s 行 %s" % (m, lns))
