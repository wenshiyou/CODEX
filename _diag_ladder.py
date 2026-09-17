# -*- coding: utf-8 -*-
# 离线诊断: 当前游戏画面上 route_009 每套梯子模板的真实匹配分与位置
import json, base64, glob, os
import numpy as np, cv2, mss, win32gui

os.chdir(r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2")

# 1) 找 1280x800 的可见窗口(游戏)
cands = []
def _enum(h, _):
    if win32gui.IsWindowVisible(h):
        try:
            l, t, r, b = win32gui.GetWindowRect(h)
            w, hh = r - l, b - t
            ttl = win32gui.GetWindowText(h)
            if w == 1280 and hh == 800 and ttl:
                cands.append((h, ttl, (l, t, r, b)))
        except Exception:
            pass
win32gui.EnumWindows(_enum, None)
print("1280x800可见窗口:")
for c in cands:
    print("  hwnd=%s title=%r rect=%s" % (c[0], c[1], c[2]))
if not cands:
    raise SystemExit("没找到1280x800游戏窗口,游戏是否最小化/尺寸不对")
hwnd, title, (L, T, R, B) = cands[0]
with mss.mss() as sct:
    frame = np.array(sct.grab({"left": L, "top": T, "width": R - L, "height": B - T}))[:, :, :3]
print("截图尺寸:", frame.shape)

# 2) 加载 route_009 模板
d = json.load(open("data/route_009_ladder_tpl.json", encoding="utf-8"))
sim = float(d.get("sim", 0.7))
tpls = []
for it in d["templates"]:
    img = cv2.imdecode(np.frombuffer(base64.b64decode(it["img_b64"]), np.uint8), cv2.IMREAD_COLOR)
    tpls.append(img)
print("模板套数=%d 阈值sim=%.2f" % (len(tpls), sim))

# 3) 拼图看每套模板长啥样
pad = 6
cellw, cellh = 80, 130
sheet = np.full((cellh, len(tpls) * (cellw + pad) + pad, 3), 235, np.uint8)
for i, t in enumerate(tpls):
    th, tw = t.shape[:2]
    z = t.copy()
    scale = min((cellw - 10) / tw, (cellh - 28) / th, 1.0) if tw and th else 1.0
    if scale != 1.0:
        z = cv2.resize(z, (max(1, int(tw * scale)), max(1, int(th * scale))), interpolation=cv2.INTER_NEAREST)
    zh, zw = z.shape[:2]
    x0 = pad + i * (cellw + pad)
    sheet[4:4 + zh, x0:x0 + zw] = z
    cv2.putText(sheet, "#%d %dx%d" % (i + 1, tw, th), (x0, cellh - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
cv2.imwrite("_ladder_tpl_sheet.png", sheet)

# 4) 每套全图匹配 + 与实时相同的 dilate 局部极大 + NMS
ker = np.ones((5, 5), np.uint8)
colors = [(0, 0, 255), (0, 128, 255), (0, 200, 200), (0, 200, 0),
          (255, 0, 0), (255, 0, 200), (128, 0, 255), (0, 0, 0)]
diag = frame.copy()
for i, t in enumerate(tpls):
    th, tw = t.shape[:2]
    if th > frame.shape[0] or tw > frame.shape[1]:
        print("#%d %dx%d 模板比画面大,跳过" % (i + 1, tw, th)); continue
    res = cv2.matchTemplate(frame, t, cv2.TM_CCOEFF_NORMED)
    _, mx, _, ml = cv2.minMaxLoc(res)
    pool = cv2.dilate(res, ker)
    ys, xs = np.where((res >= sim) & (res == pool))
    pts = sorted([(float(res[y, x]), x, y) for y, x in zip(ys, xs)], reverse=True)
    kept = []
    for s, x, y in pts:
        cx, cy = x + tw // 2, y + th // 2
        if all(abs(cx - qx) > 28 for _, qx, qy in kept):
            kept.append((s, cx, cy))
    col = colors[i % len(colors)]
    print("#%d %dx%d 最高分=%.3f@(x%d,y%d) 过阈峰(去重后)=%d %s" % (
        i + 1, tw, th, mx, ml[0] + tw // 2, ml[1] + th // 2, len(kept),
        ("  <== 新模板若在这" if i == len(tpls) - 1 else "")))
    for s, cx, cy in kept[:8]:
        cv2.rectangle(diag, (cx - tw // 2, cy - th // 2), (cx - tw // 2 + tw, cy - th // 2 + th), col, 2)
        cv2.putText(diag, "#%d %.2f" % (i + 1, s), (cx - tw // 2, cy - th // 2 - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1)
cv2.imwrite("_ladder_diag.png", diag)
print("已写出 _ladder_tpl_sheet.png / _ladder_diag.png")
