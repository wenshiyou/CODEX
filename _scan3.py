# -*- coding: utf-8 -*-
# 临时：提取关键字符串上下文与Python模块组织，只读不运行
import os, re
NB = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\_nb_tmp"
wt = open(os.path.join(NB,"wt.exe"),"rb").read()
uc = open(os.path.join(NB,"usercl.exe"),"rb").read()

def astrs(data):
    return [m.group(0) for m in re.finditer(rb"[\x20-\x7e]{4,}", data)]
def u16strs(data):
    out=[]
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){4,}", data):
        out.append(m.group(0).replace(b"\x00",b""))
    return out

# 1) usercl 里 grap/nProtect/VirtualProtect/进程/端口 上下文
print("===== usercl.exe 关键串上下文 =====")
ucs = astrs(uc)+u16strs(uc)
pat = re.compile(rb"grap|nprotect|protect|inject|hook|process|\.exe|127\.0\.0\.1|localhost|port|debug|privilege|client", re.I)
seen=set()
for s in ucs:
    if pat.search(s):
        t=s.decode(errors="replace")
        if t not in seen and len(t)<120:
            seen.add(t); print("  ", t)
        if len(seen)>=60: break

# 2) wt 的 python 模块/脚本名（PyInstaller TOC 明文）与架构相关串
print("\n===== wt.exe 模块/架构相关字符串 =====")
wts = astrs(wt)
modpat = re.compile(rb"\.py$|site-packages|foothold|ladder|nav|route|mob|monster|player|character|capture|screen|vision|minimap|memory|read_proc|127\.0\.0\.1|socket|port|usercl|snapshot|move_cand", re.I)
seen=set(); cnt=0
for s in wts:
    if modpat.search(s):
        t=s.decode(errors="replace")
        if t not in seen and len(t)<110:
            seen.add(t); print("  ", t); cnt+=1
        if cnt>=80: break

# 3) PyInstaller cookie / pyd 依赖
print("\n===== 打包判定 =====")
for sig,n in [(b"MEI\x0c\x0b\x0a\x0b\x0e","PyInstaller-cookie"),(b"python3","python3x"),(b".pyd",".pyd")]:
    i=wt.find(sig); print(" ",n,"first@",i)
pyds=sorted(set(m.group(0).decode(errors='replace') for m in re.finditer(rb"[A-Za-z0-9_]{2,30}\.pyd", wt)))
print("  PYD modules:", ", ".join(pyds[:60]))
# 本地端口/通信
for kw in [b"127.0.0.1", b"localhost", b"ws://", b"http://127", b":7", b"namedpipe", b"\\\\.\\pipe"]:
    idxs=[m.start() for m in re.finditer(re.escape(kw), wt, re.I)][:3]
    for i in idxs:
        print("  conn",kw, wt[max(0,i-30):i+40].decode(errors='replace'))
