# -*- coding: utf-8 -*-
# 诊断:复刻 _detect_minimap 三模板定位,连测24次,看裁剪框map_area_rect是否帧间跳变
import win32gui, mss, numpy as np, cv2, time, os

DATA = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\data\templates"
tpl_m = cv2.imread(os.path.join(DATA, "minimap_title.png"))
tpl_b = cv2.imread(os.path.join(DATA, "bigmap_title.png"))
tpl_btm = cv2.imread(os.path.join(DATA, "minimap_bottom.png"))
mh, mw = tpl_m.shape[:2]; bh, bw = tpl_b.shape[:2]; btm_h, btm_w = tpl_btm.shape[:2]

_hw = []
win32gui.EnumWindows(lambda h, _: _hw.append(h) if 'MapleStory' in win32gui.GetWindowText(h) else None, None)
h = _hw[0]; l, t, r, b = win32gui.GetWindowRect(h)
mon = {'left': l, 'top': t, 'width': r - l, 'height': b - t}
sct = mss.mss()

LEFT_OFFSET, TOP_OFFSET, BOTTOM_OFFSET, TITLE_PAD = -6, 24, -8, 45
def detect(frame):
    roi_m = frame[0:120, 0:300]
    _, vm, _, loc_m = cv2.minMaxLoc(cv2.matchTemplate(roi_m, tpl_m, cv2.TM_CCOEFF_NORMED))
    if vm < 0.55: return None
    mini_x, mini_y = loc_m
    roi_b = frame[0:120, 100:400]
    _, vb, _, loc_b = cv2.minMaxLoc(cv2.matchTemplate(roi_b, tpl_b, cv2.TM_CCOEFF_NORMED))
    big_x = 100 + loc_b[0]
    left = mini_x + LEFT_OFFSET; right = big_x + bw + 3; top = mini_y + mh + TOP_OFFSET
    sy1, sy2 = top, min(frame.shape[0], top + 350)
    sx1, sx2 = max(0, left - 20), min(frame.shape[1], right + 20)
    roi_btm = frame[sy1:sy2, sx1:sx2]
    if roi_btm.shape[0] < btm_h or roi_btm.shape[1] < btm_w: return None
    _, vbtm, _, loc_btm = cv2.minMaxLoc(cv2.matchTemplate(roi_btm, tpl_btm, cv2.TM_CCOEFF_NORMED))
    if vbtm < 0.55: return None
    bottom = sy1 + loc_btm[1] + btm_h // 2 + BOTTOM_OFFSET
    return (left, top + TITLE_PAD, right - left, bottom - top - TITLE_PAD)

rows = []
for i in range(24):
    fr = np.array(sct.grab(mon))[:, :, :3]
    r_ = detect(fr)
    if r_: rows.append(r_); print("f%02d left=%d top=%d w=%d h=%d" % (i, *r_))
    time.sleep(0.12)
arr = np.array(rows)
for j, nm in enumerate(["left", "top", "w", "h"]):
    print("%s: min=%d max=%d 极差=%d 取值=%s" % (nm, arr[:, j].min(), arr[:, j].max(), arr[:, j].max() - arr[:, j].min(),
                                              sorted(set(arr[:, j].tolist()))))
