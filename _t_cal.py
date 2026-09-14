# -*- coding: utf-8 -*-
import sys; sys.argv=["x"]
import numpy as np, cv2, glob, os, json, time
from types import SimpleNamespace
import maple_route_ui as M
R=M.MinimapRouteRecorder
obj=SimpleNamespace()
for k in dir(R):
    if k.startswith("VOTE_"): setattr(obj,k,getattr(R,k))
obj._vote_sig=None;obj._vote_tpls=None
tpls=R._load_char_vote_set(obj); obj._load_char_vote_set=lambda:tpls
bd=sorted(d for d in glob.glob("data/char_capture/batch_*") if os.path.exists(os.path.join(d,"char_feature_set.json")))[-1]
lab={r["frame"]:r["anchor"] for r in json.load(open(os.path.join(bd,"labels.json"),encoding="utf-8"))}
data=[(cv2.imread(p),lab[os.path.basename(p)]) for p in sorted(glob.glob(os.path.join(bd,"frame_*.png"))) if lab.get(os.path.basename(p))]
def run(thr,minv):
    obj.VOTE_THR_WIN=thr;obj.VOTE_MIN=minv
    errs=[];miss=[];t0=time.time()
    for i,(img,gt) in enumerate(data):
        obj._vote_full_next=0
        rr=R._vote_match_character(obj,img,(gt[0],gt[1]),False)
        if rr: errs.append(int(np.hypot(rr[0]-gt[0],rr[1]-gt[1])))
        else: miss.append(i)
    dt=(time.time()-t0)/len(data)*1000
    a=np.array(errs) if errs else np.array([-1])
    print("thr%.2f MIN%d 定到%2d/%d %5.1fms 中位%.0f 最大%3d 丢帧%s"%(
        thr,minv,len(errs),len(data),dt,np.median(a) if errs else -1,a.max() if errs else -1,miss))
for thr in [0.45,0.50,0.55,0.60]:
    run(thr,1); run(thr,3)
print("CAL_DONE")
