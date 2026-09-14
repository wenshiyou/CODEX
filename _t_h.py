# -*- coding: utf-8 -*-
import sys; sys.argv = ["x"]
import numpy as np, cv2, glob, os, json, time
from types import SimpleNamespace
import maple_route_ui as M
R = M.MinimapRouteRecorder
obj = SimpleNamespace()
for k in dir(R):
    if k.startswith("VOTE_"):
        setattr(obj, k, getattr(R, k))
obj._vote_sig=None; obj._vote_tpls=None
tpls = R._load_char_vote_set(obj); obj._load_char_vote_set=lambda:tpls
bd = sorted(d for d in glob.glob("data/char_capture/batch_*") if os.path.exists(os.path.join(d,"char_feature_set.json")))[-1]
lab = {r["frame"]: r for r in json.load(open(os.path.join(bd,"labels.json"),encoding="utf-8"))}
data = [(cv2.imread(p), lab[os.path.basename(p)]["anchor"]) for p in sorted(glob.glob(os.path.join(bd,"frame_*.png")))]
print("帧数%d 去重后块%d"%(len(data),len(tpls)))

def win_scan(thr, minv):
    obj.VOTE_THR_WIN=thr; obj.VOTE_MIN=minv
    errs=[]; sups=[]; t0=time.time()
    for img,gt in data:
        obj._vote_full_next=0
        r_=R._vote_match_character(obj,img,(gt[0],gt[1]),False)
        if r_: errs.append(int(np.hypot(r_[0]-gt[0],r_[1]-gt[1])))
    dt=(time.time()-t0)/len(data)*1000
    a=np.array(errs) if errs else np.array([-1])
    print("小窗 thr%.2f MIN%d 定到%2d/%d %5.1fms 误差中位%.0f 最大%3d"%(
        thr,minv,len(errs),len(data),dt,np.median(a) if errs else -1,a.max() if errs else -1))
for thr in [0.55,0.60,0.65,0.70]:
    win_scan(thr,3)

def full_scan(thr,minv):
    obj.VOTE_THR_FULL=thr; obj.VOTE_MIN_FULL=minv; ok=0; errs=[]
    for img,gt in data:
        obj._vote_full_next=0
        r_=R._vote_match_character(obj,img,None,False)
        if r_: ok+=1; errs.append(int(np.hypot(r_[0]-gt[0],r_[1]-gt[1])))
    a=np.array(errs) if errs else np.array([-1])
    print("全图(950小图) thr%.2f MIN%d 定到%2d/%d 误差中位%.0f 最大%d"%(thr,minv,ok,len(data),np.median(a) if errs else -1,a.max() if errs else -1))
for thr in [0.50,0.55,0.60]:
    full_scan(thr,5)
print("SCAN_DONE")
