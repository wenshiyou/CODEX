# -*- coding: utf-8 -*-
# 验证两段式首捕:光点粗位带误差(近似人物中心、X抖动)时,coarse大窗投票能否精定到真脚
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
rng=np.random.RandomState(0)
def trial(coarse, off_fn, reps=8):
    ok=0;tot=0;errs=[];t0=time.time()
    for img,gt in data:
        for _ in range(reps):
            ox,oy=off_fn(); seed=(gt[0]+ox,gt[1]+oy)
            obj._vote_full_next=0
            rr=R._vote_match_character(obj,img,seed,coarse=coarse)
            tot+=1
            if rr:
                ok+=1; errs.append(int(np.hypot(rr[0]-gt[0],rr[1]-gt[1])))
    dt=(time.time()-t0)/tot*1000
    a=np.array(errs) if errs else np.array([-1])
    print("%s 定到%d/%d(%.0f%%) %5.1fms 定到点误差中位%.0f 最大%d"%(
        "粗位大窗" if coarse else "跟踪小窗",ok,tot,100*ok/tot,dt,np.median(a) if errs else -1,a.max() if errs else -1))
# 跟踪:中心=真脚(理想)
trial(False, lambda:(rng.randint(-3,4),rng.randint(-3,4)))
# 粗位:光点近似人物中心(脚上方70)+X/抖动误差±50
trial(True, lambda:(rng.randint(-50,51), -70+rng.randint(-30,31)))
# 粗位:更大误差±90
trial(True, lambda:(rng.randint(-90,91), -50+rng.randint(-50,51)))
print("COARSE_DONE")
