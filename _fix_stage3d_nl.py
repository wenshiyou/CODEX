# -*- coding: utf-8 -*-
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s = open(P, "rb").read().decode("utf-8-sig")
def rep(old, new, tag):
    global s
    c = s.count(old)
    assert c == 1, "[%s] 命中%d" % (tag, c)
    s = s.replace(old, new); print("OK", tag)

rep("_stage = '未锁·相位%s' % _ap                            else:",
    "_stage = '未锁·相位%s' % _ap\n                            else:", "拆rep2尾")
rep("_stage = '回pick重稳'                             if _now_lm - getattr(self, '_snap_dbg_t', 0) >= 300:",
    "_stage = '回pick重稳'\n                            if _now_lm - getattr(self, '_snap_dbg_t', 0) >= 300:", "拆rep3尾")

open(P, "wb").write(s.encode("utf-8-sig"))
import py_compile
py_compile.compile(P, doraise=True)
print("修复并编译通过")
