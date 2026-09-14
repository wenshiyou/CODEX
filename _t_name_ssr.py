# -*- coding: utf-8 -*-
# 临时验证3:名字"自动抠图"(零手调阈值)。结构=深色半透明底板+白色像素字。
# 原理:名字ROI内灰度直方图天然"暗底板/亮白字"两峰,OTSU自动找谷底分出白字;再去碎点。
#  A)对sssr特写直接OTSU  B)对带背景整图自动找"深色底板"再在底板内OTSU取字
import cv2, numpy as np, os
OUT = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\data\_ui_look"
os.makedirs(OUT, exist_ok=True)

def clean_small(mask, min_area=3):
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    out = np.zeros_like(mask)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            out[lab == i] = 255
    return out

def auto_text_in_roi(roi_bgr, min_area=3):
    """在一小块名字图里自动抠白字(OTSU,无阈值参数),返回字掩膜(字白其余黑)"""
    v = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)[:, :, 2]
    _, bw = cv2.threshold(v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)  # 亮=白字→255
    bw = clean_small(bw, min_area)
    return v, bw

# ---------- A) sssr 特写 ----------
A = r"C:\Users\wenwen\AppData\Local\Doubao\User Data\ClipboardTemp\5bda80a2-db31-44b6-8da7-dadff5d05179.png"
im = cv2.imdecode(np.fromfile(A, np.uint8), cv2.IMREAD_COLOR)
print("closeup", im.shape)
v, bw = auto_text_in_roi(im, min_area=2)
overlay = im.copy(); overlay[bw > 0] = (0, 0, 255)  # 抠出的字叠红验证
def u3(b): return cv2.cvtColor(b, cv2.COLOR_GRAY2BGR) if b.ndim == 2 else b
rowA = np.hstack([im, np.full((im.shape[0], 4, 3), 40, np.uint8), u3(v),
                  np.full((im.shape[0], 4, 3), 40, np.uint8), u3(bw),
                  np.full((im.shape[0], 4, 3), 40, np.uint8), overlay])
rowA = cv2.resize(rowA, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
pA = os.path.join(OUT, "name_ssr_auto.png"); cv2.imencode(".png", rowA)[1].tofile(pA)
print("saved", pA, rowA.shape, "text white px=", int((bw > 0).sum()))

# ---------- B) 整图自动找深色底板再抠字 ----------
B = r"C:\Users\wenwen\AppData\Local\Doubao\User Data\ClipboardTemp\962d45c4-dbcd-4b1e-bfd4-c96c5393b0cd.png"
full = cv2.imdecode(np.fromfile(B, np.uint8), cv2.IMREAD_COLOR)
H, W = full.shape[:2]
vfull = cv2.cvtColor(full, cv2.COLOR_BGR2HSV)[:, :, 2]
_, darkall = cv2.threshold(vfull, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)  # 暗类
n, lab, stats, cent = cv2.connectedComponentsWithStats(darkall)
cand = []
for i in range(1, n):
    x, y, w, h, a = stats[i]
    ar = w / max(h, 1)
    fill = a / max(1.0, w * h)
    if 14 <= w <= 130 and 7 <= h <= 42 and 1.1 <= ar <= 9 and fill >= 0.45:  # 实心横条=深色底板
        cand.append((int(x), int(y), int(w), int(h), int(a)))
print("dark plate candidates:", cand)
res = full.copy(); got = None
if cand:
    got = max(cand, key=lambda t: t[2] * t[3])  # 最像底板的实心横条
    x, y, w, h, _ = got
    cv2.rectangle(res, (x, y), (x + w, y + h), (0, 0, 255), 1)
    roi = full[y:y + h, x:x + w]
    _, tbw = auto_text_in_roi(roi, min_area=2)
    big = cv2.resize(tbw, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
    pB = os.path.join(OUT, "name_ssr_fullplate.png")
    pad = np.full((res.shape[0], 4, 3), 40, np.uint8)
    combo = np.hstack([res, pad, u3(vfull), pad, cv2.resize(u3(darkall), (W, H))])
    cv2.imencode(".png", combo)[1].tofile(pB)
    pC = os.path.join(OUT, "name_ssr_fulltext.png"); cv2.imencode(".png", big)[1].tofile(pC)
    print("plate", got, "saved", pB, "and text", pC, big.shape)
