# -*- coding: utf-8 -*-
# AST 命名遮蔽扫描:类内/顶层重复函数名(复制粘贴产生的覆盖),及本次新增名是否重复定义
import ast, io, sys
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
tree = ast.parse(io.open(P, encoding="utf-8-sig").read())
dup = 0
def scan_body(body, scope):
    global dup
    names = {}
    for n in body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.setdefault(n.name, []).append(n.lineno)
    for name, lines in names.items():
        if len(lines) > 1:
            dup += 1
            print("DUP %s.%s lines=%s" % (scope, name, lines))
for n in tree.body:
    if isinstance(n, ast.ClassDef):
        scan_body(n.body, "class:" + n.name)
scan_body([n for n in tree.body if isinstance(n, ast.FunctionDef)], "top")
# 本次新增/改动关键符号应各只有1处定义
src = io.open(P, encoding="utf-8-sig").read()
for tok in ["def _finish_platform_retreat", "def _platform_retreat_tick",
            "def _set_b_lock_enabled", "def _start_runtime_detection"]:
    print("DEFCOUNT %s = %d" % (tok, src.count(tok)))
print("DUP_TOTAL=%d" % dup)
sys.exit(1 if dup else 0)
