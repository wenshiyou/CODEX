# -*- coding: utf-8 -*-
# 仿YOLO可行性:在【真机全屏帧】上做多块颜色(0.7)+形状(0.3)几何投票,看最强峰是否落在真人身上
# 不依赖光点/小窗,全屏找;速度不管,先看精度。结果画框存 out_full/ 供肉眼判定。
import sys; sys.argv=["x"]
import numpy as np, cv2, glob, os, time
from types import SimpleNamespace
import maple_route_ui as M
R=M.MinimapRouteRecorder
obj=SimpleNamespace()
for k in dir(R):
    if k.startswith("VOTE_"): setattr(obj,k,getattr(R,k))
tpls=R._load_char_vote_set(SimpleNamespace(_vote_sig=None,_vote_tpls=None)) if False else None
obj._vote_sig=None;obj._vote_tpls=None
tpls=R._load_char_vote_set(obj)
print("tpls",len(tpls))
SC=0.5; Q=4; wc,wsh=0.7,0.3
TOPM,BOTM=M.DETECT_TOP_MARGIN,M.DETECT_BOTTOM_MARGIN
dirs=sorted(glob.glob("data/real_capture/real_*"))
if not dirs:
    print("还没有真机帧 data/real_capture/real_*"); sys.exit()
bd=dirs[-1]; print("用目录",bd)
imgs=sorted(glob.glob(os.path.join(bd,"real_*.png")))
outdir=os.path.join(bd,"out_full"); os.makedirs(outdir,exist_ok=True)
THS=[0.35,0.40,0.45,0.50,0.55]

def full_vote(frame, thr, draw_pts=None):
    fh,fw=frame.shape[:2]
    y1,y2=TOPM, fh-BOTM
    src=frame[y1:y2,:]
    g=cv2.resize(cv2.cvtColor(src,cv2.COLOR_BGR2GRAY),(0,0),fx=SC,fy=SC)
    hsv=cv2.cvtColor(src,cv2.COLOR_BGR2HSV); col=cv2.merge([hsv[:,:,0],hsv[:,:,1]])
    c=cv2.resize(col,(0,0),fx=SC,fy=SC)
    Hs,Ws=src.shape[:2]; gW,gH=int(np.ceil(Ws/Q))+1,int(np.ceil(Hs/Q))+1
    acc=np.zeros(gW*gH,np.int32); peakpts={}
    for gf,ghalf,cf,chalf,dx,dy in tpls:
        tg,tc=ghalf,chalf; th,tw=tg.shape[:2]
        if th>g.shape[0] or tw>g.shape[1]: continue
        rs=cv2.matchTemplate(g,tg,cv2.TM_CCOEFF_NORMED)
        rc=cv2.matchTemplate(c,tc,cv2.TM_CCOEFF_NORMED)
        r=wc*rc+wsh*rs
        ys,xs=np.where(r>=thr)
        if xs.size==0: continue
        flx=(xs.astype(float)+tw/2)/SC-dx; fly=(ys.astype(float)+th/2)/SC-dy
        gx=np.floor(flx/Q).astype(int); gy=np.floor(fly/Q).astype(int)
        ok=(gx>=0)&(gx<gW)&(gy>=0)&(gy<gH)
        ubi=np.unique(gx[ok]*gH+gy[ok])
        np.add.at(acc,ubi,1)
        if draw_pts is not None:
            for ux,uy in zip(xs,ys): draw_pts.append(((ux+tw//2)/SC,(uy+th//2)/SC))
    if acc.size==0: return None,0,0,acc
    order=np.argsort(acc)[::-1]
    best=order[0]; sup=int(acc[best])
    gy0,gx0=best%gH,best//gH
    hide=np.ones(acc.shape,bool)
    for di in(-1,0,1):
        for dj in(-1,0,1):
            xx,yy=gx0+di,gy0+dj
            if 0<=xx<gW and 0<=yy<gH: hide[xx*gH+yy]=False
    second=int(acc[hide].max()) if hide.any() else 0
    bx=int(round((gx0+0.5)*Q)); by=int(round((gy0+0.5)*Q))+y1
    return (bx,by),sup,second,acc

summ={th:[0,0] for th in THS}  # [达到MIN3帧数,总]
t0=time.time()
for ip in imgs:
    frame=cv2.imread(ip)
    line=os.path.basename(ip)
    canv=frame.copy(); pts=[]
    for th in THS:
        pos,sup,sec,_=full_vote(frame,th, pts if th==0.40 else None)
        ok = sup>=3; summ[th][1]+=1; summ[th][0]+= 1 if ok else 0
        line+=" | th%.2f峰%d/次%d"%(th,sup,sec)
    # 用0.40画结果图:最强峰红点+所有达标匹配点小黄点
    pos,sup,sec,_=full_vote(frame,0.40,pts)
    for px,py in pts: cv2.circle(canv,(int(px),int(py+TOPM)),1,(0,255,255),-1)
    if pos:
        cv2.drawMarker(canv,pos,(0,0,255),cv2.MARKER_CROSS,34,3)
        cv2.putText(canv,"peak%d sec%d"%(sup,sec),(pos[0]+18,pos[1]),cv2.FONT_HERSHEY_SIMPLEX,0.7,(0,0,255),2)
    cv2.imwrite(os.path.join(outdir,os.path.basename(ip)),canv)
    print(line)
print("=== 各阈值下 最强峰>=3块 的帧数 ===")
for th in THS:
    a,b=summ[th]; print("th%.2f: %d/%d"%(th,a,b))
print("均耗时(全屏0.40) %.0fms  结果图在 %s"%((time.time()-t0)/max(1,len(imgs))*1000,outdir))
print("FULLREAL_DONE")
