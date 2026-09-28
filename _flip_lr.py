# -*- coding: utf-8 -*-
import io
T=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
d=io.open(T,"r",encoding="utf-8",newline="").read()
crlf="\r\n" in d; c=c=d.replace("\r\n","\n")
old="                    _lab = ('向下..' if _d > 0 else '向上..') if _axis == 'y' else ('向右..' if _d > 0 else '向左..')"
new="                    _lab = ('向下..' if _d > 0 else '向上..') if _axis == 'y' else ('向左..' if _d > 0 else '向右..')"
assert c.count(old)==1, c.count(old)
c=c.replace(old,new)
if crlf: c=c.replace("\n","\r\n")
io.open(T,"w",encoding="utf-8",newline="").write(c)
print("done")
