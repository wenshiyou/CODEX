# -*- coding: utf-8 -*-
# 临时：验证“扣名字”——颜色/描边分割 vs 整块模板，只读样图、输出对比
import cv2, numpy as np, os
SRC = r"C:\Users\wenwen\AppData\Local\Doubao\User Data\ClipboardTemp\43b26d58-ea7a-44fe-bcf8-ffe48062551e.png"
OUT = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\data\_ui_look"
os.makedirs(OUT, exist_ok=True)
im = cv2.imdecode(np.fromfile(SRC, np.uint8), cv2.IMREAD_COLOR)
print("size", im.shape)
# 只取顶部游戏画面（说明书上半），下面放大示意不要
crop = im[:340, :].copy()
hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
H, S, V = cv2.split(hsv)

# 1) 名字“亮色填充”：低饱和 + 高亮（白/浅色字芯），背景被滤掉
white = ((S < 80) & (V > 165)).astype(np.uint8) * 255
# 2) 描边结构：亮字芯周围一圈暗描边 => 文字像素（抗背景）
dark = (V < 95).astype(np.uint8)
kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
dark_nb = cv2.dilate(dark, kd)
stroke = ((white > 0) & (dark_nb > 0)).astype(np.uint8) * 255
# 3) 横向闭运算把同一行笔画连成名字条
closed = cv2.morphologyEx(white, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5)))
n, lab, stats, cent = cv2.connectedComponentsWithStats(closed)
res = crop.copy()
hits = []
for i in range(1, n):
    x, y, w, h, a = stats[i]
    if 10 <= w <= 220 and 8 <= h <= 70 and a >= 14 and w / max(h, 1) >= 0.8:
        cv2.rectangle(res, (x, y), (x + w, y + h), (0, 0, 255), 2)
        cx, cy = int(cent[i][0]), int(cent[i][1])
        cv2.circle(res, (cx, cy), 3, (0, 255, 0), -1)
        hits.append((x, y, w, h, a))
print("文字条候选数:", len(hits))
for t in hits: print("  box x,y,w,h,area =", t)

def up3(b):
    b = cv2.cvtColor(b, cv2.COLOR_GRAY2BGR) if b.ndim == 2 else b
    return b
pad = np.full((crop.shape[0], 8, 3), 40, np.uint8)
row = np.hstack([crop, pad, up3(white), pad, up3(stroke), pad, res])
# 缩到可看宽度
sc = 1400 / row.shape[1]
row = cv2.resize(row, None, fx=sc, fy=sc, interpolation=cv2.INTER_NEAREST)
dst = os.path.join(OUT, "name_seg_compare.png")
cv2.imencode(".png", row)[1].tofile(dst)
print("saved", dst, row.shape)
