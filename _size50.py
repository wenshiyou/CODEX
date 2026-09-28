# -*- coding: utf-8 -*-
import io
T=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
d=io.open(T,"r",encoding="utf-8",newline="").read()
crlf="\r\n" in d; c=d.replace("\r\n","\n")
o="        FLOW_BOX, FLOW_TAIL_GAP, FLOW_MARGIN = 15, 40, 4   # 检测框=显示框15;框中心离光点40;块内边距4"
n="        FLOW_BOX, FLOW_TAIL_GAP, FLOW_MARGIN = 50, 40, 4   # 检测框=显示框50;框中心离光点40;块内边距4"
assert c.count(o)==1; c=c.replace(o,n)
if crlf: c=c.replace("\n","\r\n")
io.open(T,"w",encoding="utf-8",newline="").write(c)
print("done")
