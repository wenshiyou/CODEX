# -*- coding: utf-8 -*-
# 对【真实】debug.log 调用源码里同一个 _maint_trim_debug_log(60)，立即清跨天污染(幂等首裁)。
import ast, io, os, re, textwrap

SRC = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
REAL = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"

src = io.open(SRC, "rb").read().decode("utf-8-sig")
tree = ast.parse(src)
fs = None
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        for st in node.body:
            if isinstance(st, ast.FunctionDef) and st.name == "_maint_trim_debug_log":
                fs = ast.get_source_segment(src, st)
assert fs
g = {"io": io, "os": os, "re": re, "DEBUG_LOG": REAL}
exec(textwrap.dedent(fs), g)
trim = g["_maint_trim_debug_log"]

def stat(tag):
    L = io.open(REAL, "rb").read().decode("utf-8", "ignore").splitlines()
    ts = re.compile(r"^\[(\d\d:\d\d:\d\d)\]")
    st = [ts.match(x).group(1) for x in L if ts.match(x)]
    print(tag, "行数", len(L), "首", st[:2], "末", st[-2:],
          "含[22:", sum(x.startswith("[22:") for x in L),
          "含[23:", sum(x.startswith("[23:") for x in L))
    return L

stat("裁剪前")
trim(object(), 60)
stat("裁剪后")
