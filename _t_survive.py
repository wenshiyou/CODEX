# -*- coding: utf-8 -*-
# 验证用户"每张动作帧都在的块才是角色"=跨帧存活率筛选:统计存活率分布,并测只用高存活块时的定到率/耗时
import sys; sys.argv = ["x"]
import numpy as np, cv2, glob, os, json, time
from types import SimpleNamespace
import maple_route_ui as M
R = M.MinimapRouteRecorder
obj = SimpleNamespace()
for k in dir(R):
    if k.startswith("VOTE_"): setattr(obj, k, getattr(R, k))
bd = sorted(d for d in glob.glob("data/char_capture/batch_*") if os.path.exists(os.path.join(d,"char_feature_set.json")))[-1]
fs = json.load(open(os.path.join(bd,"char_feature_set.json"),encoding="utf-8"))
labs = json.load(open(os.path.join(bd,"labels.json"),encoding="utf-8"))
anc = {r["frame"]: r["anchor"] for r in labs}
frames = sorted(glob.glob(os.path.join(bd,"frame_*.png")))
fimg = {os.path.basename(p): cv2.imread(p) for p in frames}
def prep(im):
    g = cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
    hsv=cv2.cvtColor(im,cv2.COLOR_BGR2HSV); col=cv2.merge([hsv[:,:,0],hsv[:,:,1]])
    return g,col
sc=0.5; wc,wsh=0.7,0.3
raw=[]
for e in fs["entries"]:
    im=cv2.imread(os.path.join(bd,e["patch"]))
    if im is None: continue
    g,col=prep(im)
    gh=cv2.resize(g,(max(1,int(g.shape[1]*sc)),max(1,int(g.shape[0]*sc))))
    ch=cv2.resize(col,(max(1,int(col.shape[1]*sc)),max(1,int(col.shape[0]*sc))))
    raw.append([g,gh,col,ch,int(e["dx"]),int(e["dy"]),int(e["frame"])])
# 相对脚网格去重(同格留最清晰)
cells={}
for z in raw:
    g=z[0]; sharp=float(cv2.Laplacian(g,cv2.CV_64F).var()); z.append(sharp)
    k=(z[4]//10,z[5]//10)
    if k not in cells or sharp>cells[k][7]: cells[k]=z
cand=list(cells.values())
print("网格去重后候选块",len(cand))
fnames=[os.path.basename(p) for p in frames]
def best_rate(z, RR=10, thr=0.45):
    tg,tc,dx,dy,src=z[0],z[2],z[4],z[5],z[6]
    th,tw=tg.shape[:2]; alive=0; tot=0
    for fn in fnames:
        fi=int(fn[6:8])
        if fi==src: continue
        a=anc.get(fn)
        if not a: continue
        tot+=1
        img=fimg[fn]; H,W=img.shape[:2]
        cx,cy=a[0]+dx,a[1]+dy
        x1,y1=cx-tw//2-RR,cy-th//2-RR; x2,y2=x1+tw+2*RR,y1+th+2*RR
        if x1<0 or y1<0 or x2>W or y2>H: continue
        ng,nc=prep(img[y1:y2,x1:x2])
        if ng.shape[0]<th or ng.shape[1]<tw: continue
        rs=cv2.matchTemplate(ng,tg,cv2.TM_CCOEFF_NORMED)
        rc=cv2.matchTemplate(nc,tc,cv2.TM_CCOEFF_NORMED)
        if float((wc*rc+wsh*rs).max())>=thr: alive+=1
    return alive/max(1,tot)
rates=np.array([best_rate(z) for z in cand])
for t in [0.4,0.55,0.7,0.85]:
    print("存活率>=%.2f: %d块"%(t,int((rates>=t).sum())))
# 用不同存活率门限的块跑小窗投票
data=[(fimg[os.path.basename(p)],anc[os.path.basename(p)]) for p in frames if anc.get(os.path.basename(p))]
for t in [0.4,0.55,0.7]:
    sel=[(z[0],z[1],z[2],z[3],z[4],z[5]) for z,r in zip(cand,rates) if r>=t]
    obj._load_char_vote_set=lambda sel=sel: sel
    obj.VOTE_THR_WIN=0.62; obj.VOTE_MIN=3
    errs=[];t0=time.time()
    for img,gt in data:
        obj._vote_full_next=0
        rr=R._vote_match_character(obj,img,(gt[0],gt[1]),False)
        if rr: errs.append(int(np.hypot(rr[0]-gt[0],rr[1]-gt[1])))
    dt=(time.time()-t0)/len(data)*1000
    a=np.array(errs) if errs else np.array([-1])
    print("门限%.2f 块%2d 小窗定到%2d/%d %5.1fms 误差中位%.0f 最大%d"%(
        t,len(sel),len(errs),len(data),dt,np.median(a) if errs else -1,a.max() if errs else -1))
print("SURV_DONE")
