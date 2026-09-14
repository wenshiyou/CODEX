# -*- coding: utf-8 -*-
"""F4特征集 -> 小窗多点投票定脚 算法离线原型(不依赖主程序,纯cv2)。
原理:每个特征小块自带相对脚的(dx,dy);在搜索窗内对每块模板匹配,命中块按(dx,dy)给"脚"投一票;
正确票抱团、误配票散乱,取最大一致簇(>=min_votes)的中位数定脚,散票丢弃,凑不够判丢。
验证:留一帧(用其它帧块匹配目标帧,避免自匹配过拟合)对比人工标注anchor,统计误差;输出可视化。
用法: python test_char_vote.py [batch目录] [阈值thr]
"""
import cv2, os, json, glob, sys
import numpy as np

BATCH = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("data/char_capture/batch_*"))[-1]
THR = float(sys.argv[2]) if len(sys.argv) > 2 else 0.60
CLUSTER_TOL = 16     # 同一簇: 投票脚点x/y都在±16px内
MIN_VOTES = 3        # 一致簇至少3票才定脚,否则判丢


def load(batch):
    fs = json.load(open(os.path.join(batch, "char_feature_set.json"), encoding="utf-8"))
    lab = json.load(open(os.path.join(batch, "labels.json"), encoding="utf-8"))
    frames, anchors = {}, {}
    for r in lab:
        fn = os.path.basename(r["frame"])
        im = cv2.imread(os.path.join(batch, r["frame"]))
        if im is not None:
            frames[fn] = im; anchors[fn] = r.get("anchor")
    tpls = []
    for e in fs["entries"]:
        im = cv2.imread(os.path.join(batch, e["patch"]), cv2.IMREAD_GRAYSCALE)
        if im is not None:
            tpls.append((im, int(e["dx"]), int(e["dy"]), int(e.get("frame", -1))))
    return frames, anchors, tpls


def locate(img, tpls, thr=THR, tol=CLUSTER_TOL, minv=MIN_VOTES, exclude_frame=None):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); H, W = g.shape
    votes = []
    for t, dx, dy, fr in tpls:
        if exclude_frame is not None and fr == exclude_frame:
            continue
        th, tw = t.shape[:2]
        if th > H or tw > W:
            continue
        res = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(res)
        if mv >= thr:
            hx, hy = ml[0]+tw/2.0, ml[1]+th/2.0
            votes.append((hx-dx, hy-dy, float(mv)))   # 该块给脚投一票
    if len(votes) < minv:
        return None, len(votes)
    best = []
    for (x, y, s) in votes:   # 找票数最多的矩形邻域簇
        cl = [v for v in votes if abs(v[0]-x) <= tol and abs(v[1]-y) <= tol]
        if len(cl) > len(best):
            best = cl
    if len(best) < minv:
        return None, len(votes)
    fx = float(np.median([v[0] for v in best])); fy = float(np.median([v[1] for v in best]))
    return (fx, fy, float(np.mean([v[2] for v in best]))), len(votes)


def main():
    frames, anchors, tpls = load(BATCH)
    names = sorted(frames.keys())
    print("批次:", BATCH, "帧:", len(names), "模板块:", len(tpls), "阈值:", THR)
    errs, lost = [], []
    tiles = []
    for k, fn in enumerate(names):
        fi = int(fn.split("_")[1].split(".")[0])
        img = frames[fn]
        # 留一帧: 排除本帧自己的块,模拟"用其它动作帧的特征在当前帧找脚"
        foot, nv = locate(img, tpls, exclude_frame=fi)
        anc = anchors.get(fn)
        vis = img.copy()
        if anc:
            cv2.circle(vis, (int(anc[0]), int(anc[1])), 9, (255, 120, 0), 2)   # 蓝=人工基点
        if foot:
            cv2.circle(vis, (int(foot[0]), int(foot[1])), 7, (0, 230, 0), 2)    # 绿=投票定脚
            e = float(np.hypot(foot[0]-anc[0], foot[1]-anc[1])) if anc else -1
            errs.append(e)
            print("%s 票%d 定脚(%.0f,%.0f) 基点%s 误差%.1fpx 均配%.2f" %
                  (fn, nv, foot[0], foot[1], anc, e, foot[2]))
        else:
            lost.append(fn)
            print("%s 判丢(有效票%d<%d)" % (fn, nv, MIN_VOTES))
        t = cv2.resize(vis, (475, 130)); tiles.append((k, t))
    if errs:
        ea = np.array(errs)
        print("\n=== 留一帧结果 ===")
        print("定到脚帧%d 判丢%d  误差 中位%.1f 均值%.1f p90%.1f 最大%.1f  <=10px占比%.0f%%" % (
            len(errs), len(lost), np.median(ea), ea.mean(), np.percentile(ea, 90), ea.max(),
            100.0*(ea <= 10).mean()))
    cols = 4; cw, ch = 475, 130
    rows = (len(tiles)+cols-1)//cols
    canvas = np.full((rows*ch, cols*cw, 3), 30, np.uint8)
    for k, t in tiles:
        r, c = divmod(k, cols); canvas[r*ch:(r+1)*ch, c*cw:(c+1)*cw] = t
    out = os.path.join(BATCH, "_vote_test.png")
    cv2.imwrite(out, canvas)
    print("可视化:", os.path.abspath(out))


if __name__ == "__main__":
    main()
