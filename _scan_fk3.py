# -*- coding: utf-8 -*-
# 临时：从VMP壳残留符号还原 FK/MSC 视觉管线，只读
import os, re
D = r"C:\Users\wenwen\Desktop\FK_Taiwan_0911\MSC_Taiwan"
def load(n): return open(os.path.join(D,n),"rb").read()
core, cli = load("Core.dll"), load("Client.exe")

def clean(b):
    return "".join(chr(x) if 32<=x<127 else "." for x in b)

def ctx(data, kw, n=3, win=70):
    print("\n--- '%s' in %s ---" % (kw, "Core" if data is core else "Client"))
    c=0
    for m in re.finditer(re.escape(kw), data, re.I):
        i=m.start(); seg=data[max(0,i-win):i+win]
        print("   @%d  %s"%(i, clean(seg)))
        c+=1
        if c>=n: break

# PE 段表
print("===== PE 段名 =====")
for tag,d in [("Core",core),("Client",cli)]:
    secs=re.findall(rb"\.(?:text|rdata|data|vmp[01]?|pdata|reloc|rsrc|tls|bss)\x00", d)
    print(tag, sorted(set(s.rstrip(b"\x00").decode(errors='replace') for s in secs)))

for kw in [b"onnx", b"onnxruntime", b"Dml", b"mss", b"cv2", b"opencv", b"matchTemplate",
           b"cvtColor", b"inRange", b"findContour", b"DXGI", b"OutputDupl", b"DuplicateOutput",
           b"BitBlt", b"PrintWindow", b"GetDC", b"tesseract", b"paddle", b"GDI32",
           b"CreateDXGIFactory", b"ID3D11Device", b"Desktop"]:
    ctx(core, kw, n=2)
