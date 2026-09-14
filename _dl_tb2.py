# -*- coding: utf-8 -*-
import os, ssl, urllib.request, cv2, numpy as np
OUT = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\data\_tb\tuse"
os.makedirs(OUT, exist_ok=True)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
HDR={"User-Agent":"Mozilla/5.0 Chrome/120 Safari/537.36","Referer":"https://item.taobao.com/"}
b="https://img.alicdn.com/imgextra/"
urls=[
 "i1/91705576/O1CN01Uapswg1r3rcDFBdTh_!!91705576.png",
 "i1/91705576/O1CN01mcqxS41r3rcDX432O_!!91705576.jpg",
 "i1/91705576/O1CN01pyXed71r3rcDNbVMC_!!91705576.jpg",
 "i1/91705576/O1CN01siG9wX1r3rcF02rwF_!!91705576.png",
 "i1/91705576/O1CN011E7aIp1r3rcDHRkB8_!!91705576.jpg",
]
for i,u in enumerate(urls):
    ext=u.split(".")[-1]; dst=os.path.join(OUT,"t%02d.%s"%(i,ext))
    try:
        raw=urllib.request.urlopen(urllib.request.Request(b+u,headers=HDR),timeout=20,context=ctx).read()
        open(dst,"wb").write(raw)
        im=cv2.imdecode(np.frombuffer(raw,np.uint8),1)
        print("t%02d"%i, None if im is None else "%dx%d"%(im.shape[1],im.shape[0]), len(raw))
    except Exception as e:
        print("t%02d FAIL"%i,e)
