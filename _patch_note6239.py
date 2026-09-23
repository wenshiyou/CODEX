# -*- coding: utf-8 -*-
import io, sys
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s = io.open(P, "rb").read().decode("utf-8-sig").replace("\r\n", "\n")
old = "            # === 到顶判据(用户2026-09-22定稿:后脑为主、光点在梯子上的距离为辅;下行仍只认光点对梯底;总超时录制duration+2s保命)==="
new = "            # === 到顶判据(用户2026-09-23定稿:好梯=光点与梯顶重合±1且当下后脑不可见即到顶补按150ms;坏梯=纯后脑连续450;下行只认光点对梯底;总超时duration+2s保命)==="
assert s.count(old) == 1, "note anchor count=%d" % s.count(old)
s = s.replace(old, new)
io.open(P, "w", encoding="utf-8-sig", newline="").write(s.replace("\n", "\r\n"))
print("note6239 updated")
