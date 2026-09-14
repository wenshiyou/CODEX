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
allt=R._load_char_vote_set(obj)
bd=sorted(d for d in glob.glob("data/char_capture/batch_*") if os.path.exists(os.path.join(d,"char_feature_set.json")))[-1]
lab={r["frame"]:r["anchor"] for r in json.load(open(os.path.join(bd,"labels.json"),encoding="utf-8"))}
data=[(cv2.imread(p),lab[os.path.basename(p)]) for p in sorted(glob.glob(os.path.join(bd,"frame_*.png"))) if lab.get(os.path.basename(p))]
def spaced(t,n):
    if len(t)<=n: return t
    idx=np.linspace(0,len(t)-1,n).round().astype(int); return [t[i] for i in sorted(set(idx))]
def run(n,hw,up,dn):
    tpls=spaced(allt,n); obj._load_char_vote_set=lambda:tpls
    obj.VOTE_THR_WIN=0.62; obj.VOTE_MIN=3
    obj.VOTE_HALF_W=hw; obj.VOTE_UP=up; obj.VOTE_DOWN=dn
    errs=[];t0=time.time()
    for img,gt in data:
        obj._vote_full_next=0
        rr=R._vote_match_character(obj,img,(gt[0],gt[1]),False)
        if rr: errs.append(int(np.hypot(rr[0]-gt[0],rr[1]-gt[1])))
    dt=(time.time()-t0)/len(data)*1000
    a=np.array(errs) if errs else np.array([-1])
    print("块%2d 窗%d×%d 定到%2d/%d %5.1fms 中位%.0f 最大%d"%(
        n,hw*2,up+dn,len(errs),len(data),dt,np.median(a) if errs else -1,a.max() if errs else -1))
run(80,80,130,70)
run(48,55,95,55)
run(36,55,95,55)
run(36,45,80,45)
print("PERF_DONE")
