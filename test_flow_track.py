# -*- coding: utf-8 -*-
"""
光流咬住跟踪 · 可行性试验（独立脚本，不接入主程序、不发键、零风险）
- 红点 T = 现有办法：每帧全图模板匹配 -> 按 offset 算脚点（会跳/会丢）
- 黄点 F = 光流咬住：模板只负责初始/就近纠偏重捕，帧间用 LK 稀疏光流咬着人物身上一批角点走
关键稳健点：
  1) 初始重捕才全图采信模板；跟踪中纠偏只采信【当前位置附近】的模板命中，远处误匹配绝不带飞
  2) 粘住同一个人物模板(sticky)，不在多套 offset 间横跳
跑满 --secs 自动存 flow_compare.png 并打印 JSON。
用法：
  python test_flow_track.py --secs 14   # headless采样(自动把游戏置前),存图+统计
  python test_flow_track.py             # 弹实时窗口肉眼对比(q退 r重捕)
"""
import os, sys, json, time, struct, argparse, ctypes
from ctypes import wintypes
import numpy as np
import cv2
import mss

user32 = ctypes.windll.user32

GAME_TITLE = "MapleStory"
CHAR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "char_templates")
BAND_TOP, BAND_BOT = 30, 90                 # 人物识别带
SEED_HALF_W, SEED_TOP, SEED_BOT = 34, 78, 4  # 以脚点为基准的人物播种框(Q版角色约70高)
LK_WIN = (15, 15)
LK_MAXLEVEL = 3
MAX_CORNERS, QUALITY, MINDIST = 70, 0.02, 4
REFRESH_SEC = 0.5
MIN_PT_KEEP, MIN_PT_LOST = 8, 4
OUTLIER_PX = 9.0
JUMP_PX = 45.0
RELOCK_MAX = 70.0        # 纠偏时模板脚点距当前光流脚点超过此值=误匹配,不采信
TPL_MIN, TPL_GOOD = 0.55, 0.62
FRAME_MS = 35

_enum_hits = []
@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def _cb(hwnd, lparam):
    n = user32.GetWindowTextLengthW(hwnd)
    if n:
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if GAME_TITLE in buf.value:
            _enum_hits.append(hwnd)
    return True

def get_game_hwnd_rect():
    _enum_hits.clear()
    user32.EnumWindows(_cb, 0)
    if not _enum_hits:
        return None, None
    hwnd = _enum_hits[0]
    rect = ctypes.create_string_buffer(16)
    user32.GetWindowRect(hwnd, rect)
    l, t, r, b = struct.unpack("llll", rect.raw)
    return hwnd, {"left": l, "top": t, "width": r - l, "height": b - t}

def bring_front(hwnd):
    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False

def load_char_templates():
    out, meta = [], {}
    mp = os.path.join(CHAR_DIR, "meta.json")
    if os.path.exists(mp):
        try:
            for m in json.load(open(mp, "r", encoding="utf-8")):
                meta[m.get("id")] = m
        except Exception as e:
            print("meta读取失败:", e)
    if not os.path.isdir(CHAR_DIR):
        return out
    for fn in os.listdir(CHAR_DIR):
        if not fn.lower().endswith(".png"):
            continue
        base = fn[:-4]
        cid = None
        if base.startswith("char_") and base[5:].isdigit():
            cid = int(base[5:])
        img = cv2.imread(os.path.join(CHAR_DIR, fn), cv2.IMREAD_COLOR)
        if img is None:
            continue
        h, w = img.shape[:2]
        mm = meta.get(cid, {})
        out.append((cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), w, h,
                    int(mm.get("offset_x", 0)), int(mm.get("offset_y", 0)), cid))
    return out

def match_candidates(gray, tpls):
    """返回全部模板命中[(score,footx,footy,cid)]，按分降序"""
    H = gray.shape[0]
    band = gray[BAND_TOP:H - BAND_BOT, :]
    res = []
    for tg, w, h, ox, oy, cid in tpls:
        if band.shape[0] < h or band.shape[1] < w:
            continue
        r = cv2.matchTemplate(band, tg, cv2.TM_CCOEFF_NORMED)
        _, mx, _, mloc = cv2.minMaxLoc(r)
        fx = mloc[0] + w / 2.0 + ox
        fy = mloc[1] + h / 2.0 + BAND_TOP + oy
        res.append((float(mx), fx, fy, cid))
    res.sort(key=lambda z: -z[0])
    return res

class FlowTracker:
    def __init__(self):
        self.prev_gray = None
        self.pts = None
        self.anchor = None
        self.foot = None
        self.state = "LOST"
        self.last_seed = 0.0
        self.lock_cid = None     # sticky：粘住同一套模板/offset

    def _pick(self, cands, prefer_lock, near_foot, thresh):
        """按sticky+就近挑一个可信模板命中,返回(footx,footy,score,cid)或None"""
        if not cands:
            return None
        if prefer_lock is not None:
            for c in cands:
                if c[3] == self.lock_cid and c[0] >= thresh:
                    if near_foot is None or abs(complex(c[1]-near_foot[0], c[2]-near_foot[1])) < RELOCK_MAX:
                        return c
        pool = [c for c in cands if c[0] >= thresh]
        if near_foot is not None:   # 跟踪中纠偏:只认附近
            pool = [c for c in pool if abs(complex(c[1]-near_foot[0], c[2]-near_foot[1])) < RELOCK_MAX]
        return pool[0] if pool else None

    def _seed(self, gray, foot, cid):
        H, W = gray.shape
        fx, fy = int(round(foot[0])), int(round(foot[1]))
        x1, x2 = max(0, fx - SEED_HALF_W), min(W, fx + SEED_HALF_W)
        y1, y2 = max(0, fy - SEED_TOP), min(H, fy + SEED_BOT)
        if x2 - x1 < 8 or y2 - y1 < 8:
            return False
        mask = np.zeros(gray.shape, np.uint8)
        mask[y1:y2, x1:x2] = 255
        corners = cv2.goodFeaturesToTrack(gray, MAX_CORNERS, QUALITY, MINDIST, mask=mask)
        if corners is None or len(corners) < MIN_PT_LOST:
            return False
        self.pts = corners.reshape(-1, 2)
        center = np.median(self.pts, axis=0)
        self.anchor = center - np.array([fx, fy], dtype=np.float64)
        self.foot = (float(fx), float(fy))
        if cid is not None:
            self.lock_cid = cid
        self.prev_gray = gray
        self.last_seed = time.time()
        self.state = "TRACK"
        return True

    def update(self, gray, cands, now):
        suspect = relock = False
        # 无有效点 -> 全图重捕(才允许全图采信模板)
        if self.pts is None or len(self.pts) < MIN_PT_LOST:
            self.state = "LOST"
            pick = self._pick(cands, True, None, TPL_MIN)
            if pick is not None:
                self._seed(gray, (pick[1], pick[2]), pick[3])
                relock = True
            return self.foot, self.state, 0, suspect, relock
        p1, st, err = cv2.calcOpticalFlowPyrLK(
            self.prev_gray, gray, self.pts.reshape(-1, 1, 2), None,
            winSize=LK_WIN, maxLevel=LK_MAXLEVEL,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.03))
        if p1 is None:
            self.pts = None
            return self.foot, "LOST", 0, suspect, relock
        st = st.reshape(-1)
        new = p1.reshape(-1, 2)[st == 1]
        old = self.pts[st == 1]
        n_alive = len(new)
        if n_alive >= MIN_PT_LOST:
            disp = new - old
            med = np.median(disp, axis=0)
            keep = np.linalg.norm(disp - med, axis=1) < OUTLIER_PX
            new = new[keep]
        if len(new) < MIN_PT_LOST:
            self.pts = None
            self.state = "LOST"
            return self.foot, self.state, n_alive, suspect, relock
        center = np.median(new, axis=0)
        new_foot = center - self.anchor
        d = float(np.linalg.norm(new_foot - np.array(self.foot)))
        if d > JUMP_PX:
            suspect = True
        self.foot = (float(new_foot[0]), float(new_foot[1]))
        self.pts = new
        self.prev_gray = gray
        self.state = "TRACK"
        need = (now - self.last_seed > REFRESH_SEC) or (len(new) < MIN_PT_KEEP)
        if need:
            # 就近纠偏:只认附近高置信模板;否则按当前光流位置自续,绝不跳走
            pick = self._pick(cands, True, self.foot, TPL_GOOD)
            if pick is not None:
                self._seed(gray, (pick[1], pick[2]), pick[3])
                relock = True
            else:
                self._seed(gray, self.foot, None)
        return self.foot, self.state, len(new), suspect, relock

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=0.0)
    args = ap.parse_args()
    headless = args.secs > 0

    hwnd, rect = get_game_hwnd_rect()
    if rect is None:
        print("RESULT_JSON=" + json.dumps({"error": "找不到 MapleStory 游戏窗口"}, ensure_ascii=False))
        sys.exit(2)
    tpls = load_char_templates()
    print("窗口:", rect, " 人物模板:", [(t[1], t[2], t[3], t[4], t[5]) for t in tpls])
    if not tpls:
        print("RESULT_JSON=" + json.dumps({"error": "data/char_templates 无人物模板"}, ensure_ascii=False))
        sys.exit(2)
    if headless:
        bring_front(hwnd)
        time.sleep(0.8)

    sct = mss.mss()
    ft = FlowTracker()
    t_end = time.time() + args.secs if headless else None
    prev_t = prev_f = None
    dT, dF, diff = [], [], []
    t_lost = f_lost = sus_n = relock_n = frames = 0
    last_vis = None
    win = "FLOW TEST  T=red template / F=yellow flow  (q quit r relock)"
    if not headless:
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    while True:
        t0 = time.time()
        raw = np.array(sct.grab(rect))[:, :, :3]
        gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
        cands = match_candidates(gray, tpls)
        top = cands[0] if cands else None
        now = time.time()
        T = (top[1], top[2]) if (top and top[0] >= TPL_MIN) else None
        F, state, npt, suspect, relock = ft.update(gray, cands, now)
        frames += 1
        if T is None: t_lost += 1
        if state == "LOST": f_lost += 1
        if suspect: sus_n += 1
        if relock: relock_n += 1
        if T is not None:
            if prev_t is not None:
                dT.append(float(np.hypot(T[0]-prev_t[0], T[1]-prev_t[1])))
            prev_t = T
        else:
            prev_t = None
        if F is not None and state == "TRACK":
            if prev_f is not None:
                dF.append(float(np.hypot(F[0]-prev_f[0], F[1]-prev_f[1])))
            prev_f = F
        else:
            prev_f = None
        if T is not None and F is not None:
            diff.append(float(np.hypot(T[0]-F[0], T[1]-F[1])))

        vis = raw.copy()
        if ft.pts is not None:
            for p in ft.pts:
                cv2.circle(vis, (int(p[0]), int(p[1])), 1, (0, 220, 0), -1)
        if T is not None:
            cv2.circle(vis, (int(T[0]), int(T[1])), 9, (0, 0, 255), 2)
            cv2.putText(vis, "T", (int(T[0])+10, int(T[1])-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        if F is not None:
            cv2.circle(vis, (int(F[0]), int(F[1])), 11, (0, 230, 255), 3)
        if T is not None and F is not None:
            cv2.line(vis, (int(T[0]), int(T[1])), (int(F[0]), int(F[1])), (255, 220, 0), 1)
        head = "st=%s pts=%d tpl=%s dTF=%.0f relock=%d" % (
            state, npt, ("%.2f" % top[0]) if top else "none", diff[-1] if diff else -1, relock_n)
        cv2.rectangle(vis, (0, 0), (560, 26), (0, 0, 0), -1)
        cv2.putText(vis, head, (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                    (0, 255, 255) if state == "TRACK" else (120, 120, 255), 2)
        last_vis = vis

        if not headless:
            cv2.imshow(win, cv2.resize(vis, (int(vis.shape[1]*0.72), int(vis.shape[0]*0.72))))
            k = cv2.waitKey(1) & 0xFF
            if k == ord('q'): break
            if k == ord('r'):
                ft.pts = None; ft.state = "LOST"
        elif time.time() >= t_end:
            break
        cost = (time.time() - t0) * 1000
        if cost < FRAME_MS:
            time.sleep((FRAME_MS - cost) / 1000.0)

    def stat(a):
        return ({"mean": round(float(np.mean(a)), 2), "max": round(float(np.max(a)), 2), "n": len(a)}
                if a else {"mean": -1, "max": -1, "n": 0})
    summary = {"frames": frames,
               "模板T_相邻帧跳变px": stat(dT), "模板T_丢失帧": t_lost,
               "光流F_相邻帧跳变px": stat(dF), "光流F_丢失帧": f_lost,
               "T-F偏差px": stat(diff), "光流可疑大跳帧": sus_n, "重捕次数": relock_n}
    out_png = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flow_compare.png")
    if last_vis is not None:
        cv2.imwrite(out_png, last_vis)
        summary["对比图"] = out_png
    print("RESULT_JSON=" + json.dumps(summary, ensure_ascii=False))
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
