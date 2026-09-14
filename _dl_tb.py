# -*- coding: utf-8 -*-
# 临时：下载淘宝某辅助详情原图到本地研读（研究完即弃，不入库）
import os, ssl, urllib.request
OUT = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\data\_tb\tuling"
os.makedirs(OUT, exist_ok=True)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
       "Referer": "https://item.taobao.com/"}
base = "https://img.alicdn.com/imgextra/"
urls = [
 "i3/2215952264/O1CN01M13WAE1Saxi7LupbX_!!2215952264.jpg",
 "i4/2215952264/O1CN01Eoclr81SaxhbQx4gm_!!2215952264.jpg",
 "i3/2215952264/O1CN01KxJg2O1SaxhfwkF6O_!!2215952264.jpg",
 "i1/2215952264/O1CN01raalgz1Saxi65XMqX_!!2215952264.png",
 "i3/2215952264/O1CN01VgupHE1SaxpPmFBcf_!!2215952264.jpg",
 "i3/2215952264/O1CN01X1RgFW1SaxpPjDKf0_!!2215952264.jpg",
 "i2/2215952264/O1CN01H18gH31SaxpQ5CjiN_!!2215952264.jpg",
 "i1/2215952264/O1CN01QHQyHn1SaxpQD8aU8_!!2215952264.jpg",
 "i1/2215952264/O1CN018he0381SaxpPb6D0V_!!2215952264.png",
 "i4/2215952264/O1CN01PCmdfV1SaxpPVD5qy_!!2215952264.jpg",
 "i4/2215952264/O1CN016hHuw01SaxpQ5GGsZ_!!2215952264.jpg",
 "i4/2215952264/O1CN01BKcK2r1SaxpPryBQ0_!!2215952264.jpg",
 "i3/O1CN01XU1Y2d1Sk7fIMOkeU_!!6000000002284-2-tps-1125-1446.png",
 "i3/O1CN015p1A6k243wgydz2Hn_!!6000000007336-2-tps-2605-1228.png",
 "i3/O1CN01Dc9PxV1XzlCMO1boO_!!6000000002995-2-tps-3456-864.png",
]
import cv2, numpy as np
for i, u in enumerate(urls):
    url = base + u
    ext = u.split(".")[-1]
    dst = os.path.join(OUT, "d%02d.%s" % (i, ext))
    try:
        req = urllib.request.Request(url, headers=HDR)
        raw = urllib.request.urlopen(req, timeout=20, context=ctx).read()
        with open(dst, "wb") as f: f.write(raw)
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        print("d%02d OK %s %s bytes=%d" % (i, ("%dx%d" % (im.shape[1], im.shape[0])) if im is not None else "?", ext, len(raw)))
    except Exception as e:
        print("d%02d FAIL %s %s" % (i, u[:50], e))
