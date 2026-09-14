# -*- coding: utf-8 -*-
"""多点投票定脚 —— 离线"留一帧"验证脚本(不启动游戏/主程序)。
原理:每个特征小块自带相对脚的(dx,dy);在画面里 matchTemplate 找到小块中心后反算脚=中心-(dx,dy),
多块投票,正确票抱团/误票散乱,取最大一致簇(>=MIN_VOTES)的中位数定脚。
留一法:定第k帧时排除第k帧自己产出的patch(用其它动作帧的块),最能反映跨动作泛化能力。
用法: python test_vote_match.py [batch目录名(可空=最新)]
"""
import cv2, os, json, glob, sys
import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "char_capture")
THR = 0.60          # 单块匹配分阈值(TM_CCOEFF_NORMED)
CLUSTER_R = 24      # 脚候选同簇半径(px)
MIN_VOTES = 3       # 一簇至少几票才采信


def load_batch(name=None):
    if name:
        bd = os.path.join(ROOT, name)
    else:
        cands = [d for d in sorted(glob.glob(os.path.join(ROOT, "batch_*")))
                 if os.path.exists(os.path.join(d, "char_feature_set.json"))]
        if not cands:
            raise RuntimeError("没有含 char_feature_set.json 的完整批次")
        bd = cands[-1]
    fs = json.load(open(os.path.join(bd, "char_feature_set.json"), encoding="utf-8"))
    lab = {r["frame"]: r for r in json.load(open(os.path.join(bd, "labels.json"), encoding="utf-8"))}
    tpls = []
    for e in fs["entries"]:
        img = cv2.imread(os.path.join(bd, e["patch"]))
        if img is not None:
            tpls.append((img, int(e["dx"]), int(e["dy"]), int(e.get("frame", -1))))
    frames = sorted(glob.glob(os.path.join(bd, "frame_*.png")))
    return bd, tpls, lab, frames


def vote(canvas, tpls, thr=THR, cluster_r=CLUSTER_R, min_votes=MIN_VOTES, exclude_frame=None):
    """返回 (脚(x,y)或None, 采纳簇票数, 全部票[(fx,fy,score)...], 各块最高分)。"""
    H, W = canvas.shape[:2]
    votes = []
    for img, dx, dy, fr in tpls:
        if exclude_frame is not None and fr == exclude_frame:
            continue
        th, tw = img.shape[:2]
        if th > H or tw > W:
            continue
        r = cv2.matchTemplate(canvas, img, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(r)
        if mv >= thr:
            votes.append((ml[0]+tw//2-dx, ml[1]+th//2-dy, float(mv)))
    if not votes:
        return None, 0, votes
    arr = np.array([(v[0], v[1]) for v in votes], dtype=np.float64)
    best = None
    for i in range(len(arr)):
        m = arr[np.hypot(arr[:, 0]-arr[i, 0], arr[:, 1]-arr[i, 1]) <= cluster_r]
        if best is None or len(m) > len(best):
            best = m
    if best is None or len(best) < min_votes:
        return None, (0 if best is None else len(best)), votes
    return (int(np.median(best[:, 0])), int(np.median(best[:, 1]))), len(best), votes


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else None
    bd, tpls, lab, frames = load_batch(name)
    print("批次:", os.path.basename(bd), " 块数:", len(tpls), " 帧数:", len(frames))
    tiles, errs, n_fail = [], [], 0
    for p in frames:
        fn = os.path.basename(p)
        fi = int(fn[6:8])
        canvas = cv2.imread(p)
        foot, nv, votes = vote(canvas, tpls, exclude_frame=fi)  # 留一:排除本帧块
        gt = lab.get(fn, {}).get("anchor")
        vis = canvas.copy()
        for vx, vy, sc in votes:
            cv2.circle(vis, (int(vx), int(vy)), 2, (90, 90, 90), -1)
        tag = "FAIL"
        if foot is not None:
            cv2.circle(vis, foot, 9, (0, 0, 255), 2)
            tag = "vote=%d" % nv
            if gt is not None:
                e = int(np.hypot(foot[0]-gt[0], foot[1]-gt[1])); errs.append(e); tag += " err=%d" % e
        else:
            n_fail += 1
        if gt is not None:
            cv2.circle(vis, (int(gt[0]), int(gt[1])), 7, (255, 120, 0), -1)
        cv2.putText(vis, "%s votes=%d" % (tag, len(votes)), (6, 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        tiles.append(cv2.resize(vis, (475, 130)))
    if errs:
        a = np.array(errs)
        print("定到脚的帧=%d  失败帧=%d" % (len(errs), n_fail))
        print("误差px  中位=%.0f  均值=%.1f  P90=%.0f  最大=%d" % (
            np.median(a), a.mean(), np.percentile(a, 90), a.max()))
        print("误差<=10px占比=%.0f%%  <=20px占比=%.0f%%" % (
            100*(a <= 10).mean(), 100*(a <= 20).mean()))
    else:
        print("没有任何帧定到脚,阈值可能过高")
    cols = 4; rows = (len(tiles)+cols-1)//cols
    canvas = np.full((rows*130, cols*475, 3), 30, np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols); canvas[r*130:(r+1)*130, c*475:(c+1)*475] = t
    out = os.path.join(bd, "_vote_test.png")
    cv2.imwrite(out, canvas)
    print("回显图:", out)


if __name__ == "__main__":
    main()
