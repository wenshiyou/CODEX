# -*- coding: utf-8 -*-
# 临时：尝试解 usercl.pkg(UCLPKG01) 内部块，找取数方式铁证；只读
import os, re, zlib
P = r"C:\Users\wenwen\Desktop\nb\nb\usercl.pkg"
d = open(P,"rb").read()
print("size", len(d), "head", d[:32].hex(" "))
print("magic ascii", d[:8])

# 1) 明文段里直接找关键证据
kw = [b"foothold", b"ReadProcess", b"OpenProcess", b"kernel32", b"memory", b"process",
      b".py", b"import ", b"def ", b"mss", b"cv2", b"numpy", b"win32", b"pymem", b"offset",
      b"base_addr", b"grap", b"nProtect", b"client", b"screenshot", b"grab", b"BitBlt"]
low=d.lower()
print("\n[明文命中]")
for k in kw:
    c=low.count(k.lower())
    if c: print("  %-14s %d"%(k.decode(),c))

# 2) 扫 zlib 块尝试解压
print("\n[尝试 zlib 块]")
found=0
for magic in [b"\x78\x9c", b"\x78\xda", b"\x78\x01"]:
    start=0
    while True:
        i=d.find(magic,start)
        if i<0 or found>=12: break
        start=i+1
        try:
            out=zlib.decompressobj().decompress(d[i:i+5_000_000])
            if len(out)>200:
                found+=1
                fn=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\_nb_tmp\blk_%d_%d.bin"%(found,i)
                open(fn,"wb").write(out)
                hits=[k.decode() for k in [b"foothold",b"ReadProcess",b"OpenProcess",b"mss",b"cv2",b"def ",b"import",b"memory",b"process",b"move_cand",b"body_x",b"input_flags"] if k.lower() in out.lower()]
                print("  block@%d out=%d bytes -> %s hits=%s"%(i,len(out),os.path.basename(fn),hits))
        except Exception:
            pass
print("zlib blocks decoded:",found)
