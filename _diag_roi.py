# -*- coding: utf-8 -*-
# 验证: 梯子扫描ROI的Y范围(停止态默认150 vs 配置350)是否裁掉了人物上方的绳梯
import json, base64
import numpy as np, cv2, mss, win32gui
import os
os.chdir(r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2")

cands = []
def _enum(h, _):
    if win32gui.IsWindowVisible(h):
        try:
            l, t, r, b = win32gui.GetWindowRect(h)
            if (r-l) == 1280 and (b-t) == 800 and win32gui.GetWindowText(h) == 'MapleStory Worlds-克罗诺斯托里':
                cands.append((l, t, r, b))
        except Exception:
            pass
win32gui.EnumWindows(_enum, None)
L, T, R, B = cands[0]
with mss.mss() as sct:
    frame = np.array(sct.grab({"left": L, "top": T, "width": R-L, "height": B-T}))[:, :, :3]
fh, fw = frame.shape[:2]

d = json.load(open("data/route_009_ladder_tpl.json", encoding="utf-8"))
tpls = [cv2.imdecode(np.frombuffer(base64.b64decode(it["img_b64"]), np.uint8), cv2.IMREAD_COLOR)
        for it in d["templates"]]
sim = 0.70; ker = np.ones((5,5), np.uint8)
rx = 500  # far_range_x
# 人物基点候选: 脚 y≈585, 名字 y≈475 (诊断图估), x≈955
for ppx, ppy, tag in [(955, 585, '脚基点'), (955, 475, '名字基点')]:
    print("==== 人物%s (%d,%d) ====" % (tag, ppx, ppy))
    for yu in (150, 350):
        yd = yu
        x1, x2 = max(0, ppx-rx), min(fw, ppx+rx)
        y1, y2 = max(30, ppy-yu), min(fh-90, ppy+yd)
        crop = frame[y1:y2, x1:x2]
        ch, cw = crop.shape[:2]
        line = "  Y±%d ROI[y%d..%d]: " % (yu, y1, y2)
        for ti in (5, 6):  # #6 10x78, #7 4x78 (新绳)
            t = tpls[ti]; th, tw = t.shape[:2]
            if th > ch or tw > cw:
                line += "#%d(模板比ROI大) " % (ti+1); continue
            res = cv2.matchTemplate(crop, t, cv2.TM_CCOEFF_NORMED)
            pool = cv2.dilate(res, ker)
            ys, xs = np.where((res >= sim) & (res == pool))
            mx = float(res.max())
            line += "#%d max=%.2f 过阈峰=%d  " % (ti+1, mx, len(xs))
        # #1 木架块
        t = tpls[0]; th, tw = t.shape[:2]
        res = cv2.matchTemplate(crop, t, cv2.TM_CCOEFF_NORMED)
        line += "#1木架 max=%.2f" % float(res.max())
        print(line)
