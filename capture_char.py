# -*- coding: utf-8 -*-
"""
角色特征采集 + 人工标注工具 v2（独立、不接入主程序、不发键、零风险）
原理(不辨认身体部位)：每张动作图点十几个【长在角色身上】的小块点 + 一个【脚基点】；
  每个小块自带"它离脚多远(dx,dy)"。识别时在人物附近小窗找这些小块，每找到一个就按其
  偏移给脚投一票；正确小块的票抱成一团、误识别的票散乱被丢，≥3 票成团即可定脚，越多越稳。

【采集 CAPTURE】
  左键：跟随框跟丢时手动点回角色；空格：开始采集(10张/秒 x2秒=20张全屏)；, . 调框大小；q 退
【标注 LABEL】（不要求每张点数/顺序一致）
  左键单击            ：加一个普通特征点(绿)
  在脚上点一下再按空格：把【最后一个普通点】定为脚基点(蓝)，一张一个，可重定
  右键单击            ：删除离鼠标最近的点(普通点或基点)
  左键拖拽框选        ：把框内区域放大（可逐级放大）；R / Esc：退回上一级视图
  n 或回车：下一张    b：上一张    q：整体保存退出
建议：多点 头/脸/躯干/腰带 等相对脚不太动、且有花纹边缘的中轴点；少点挥来挥去的手脚末端；
     走/打/跳/左右转身/受击 动作都采到。
产物 data/char_capture/batch_时间戳/：frame_XX.png、labels.json、patches/、char_feature_set.json
重标：python capture_char.py --label <批次目录>
"""
import os, sys, json, time, struct, argparse, ctypes, glob
from ctypes import wintypes
import numpy as np
import cv2
import mss

user32 = ctypes.windll.user32
GAME_TITLE = "MapleStory"
ROOT = os.path.dirname(os.path.abspath(__file__))
CHAR_DIR = os.path.join(ROOT, "data", "char_templates")
CAP_ROOT = os.path.join(ROOT, "data", "char_capture")
BAND_TOP, BAND_BOT = 30, 90
CAP_HZ = 10                   # 每秒10张
INTERVAL = 1.0 / CAP_HZ       # 0.1s
DEFAULT_SEC = 2.0             # 默认采2秒=20张；动作循环慢/要覆盖技能特效可切3秒=30张
DISP_SCALE = 0.8
PATCH_R = 8
DW, DH = 1120, 660          # 标注显示画布
CLICK_PX = 6                # 按下/抬起位移小于此=单击加点,否则=框选
DEL_TOL = 14                # 右键就近删除容差(原图像素)

_enum = []
@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def _cb(hwnd, lp):
    n = user32.GetWindowTextLengthW(hwnd)
    if n:
        b = ctypes.create_unicode_buffer(n + 1); user32.GetWindowTextW(hwnd, b, n + 1)
        if GAME_TITLE in b.value: _enum.append(hwnd)
    return True

def game_rect():
    _enum.clear(); user32.EnumWindows(_cb, 0)
    if not _enum: return None, None
    hwnd = _enum[0]; rc = ctypes.create_string_buffer(16); user32.GetWindowRect(hwnd, rc)
    l, t, r, b = struct.unpack("llll", rc.raw)
    return hwnd, {"left": l, "top": t, "width": r-l, "height": b-t}

def load_templates():
    tpls, meta = [], {}
    mp = os.path.join(CHAR_DIR, "meta.json")
    if os.path.exists(mp):
        try:
            for m in json.load(open(mp, "r", encoding="utf-8")): meta[m.get("id")] = m
        except Exception: pass
    if os.path.isdir(CHAR_DIR):
        for fn in os.listdir(CHAR_DIR):
            if fn.lower().endswith(".png") and fn[5:-4].isdigit():
                im = cv2.imread(os.path.join(CHAR_DIR, fn), cv2.IMREAD_COLOR)
                if im is None: continue
                h, w = im.shape[:2]; cid = int(fn[5:-4]); mm = meta.get(cid, {})
                tpls.append((cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), w, h,
                             int(mm.get("offset_x",0)), int(mm.get("offset_y",0))))
    return tpls

def tpl_foot(gray, tpls):
    H = gray.shape[0]; band = gray[BAND_TOP:H-BAND_BOT, :]; best = None
    for tg,w,h,ox,oy in tpls:
        if band.shape[0]<h or band.shape[1]<w: continue
        r = cv2.matchTemplate(band, tg, cv2.TM_CCOEFF_NORMED)
        _,mx,_,loc = cv2.minMaxLoc(r)
        if best is None or mx>best[0]: best=(mx,loc[0]+w/2.0+ox, loc[1]+h/2.0+BAND_TOP+oy)
    if best and best[0]>=0.5: return (best[1],best[2])
    return None

# ============================ 标注 ============================
class Labeler:
    def __init__(self, batch_dir, frames):
        self.dir=batch_dir; self.frames=frames; self.idx=0
        self.points=[[] for _ in frames]      # 普通点
        self.anchors=[None]*len(frames)       # 脚基点(每帧一个)
        self.view=None; self.stack=[]; self._map=None
        self.drag0=None

    def reset_view(self, h, w):
        self.view=(0,0,w,h); self.stack=[]

    def disp_to_orig(self, xd, yd):
        if not self._map: return None
        s,ox,oy,a,b = self._map
        return (a+(xd-ox)/s, b+(yd-oy)/s)

def lab_mouse(event, x, y, flags, lab):
    if event==cv2.EVENT_LBUTTONDOWN:
        lab.drag0=(x,y)
    elif event==cv2.EVENT_LBUTTONUP:
        p0=lab.drag0; lab.drag0=None
        if p0 is None: return
        moved=abs(x-p0[0])+abs(y-p0[1])
        o1=lab.disp_to_orig(*p0); o2=lab.disp_to_orig(x,y)
        if None in (o1,o2): return
        if moved < CLICK_PX:
            # 单击=加点
            lab.points[lab.idx].append((int(round(o2[0])), int(round(o2[1]))))
        else:
            # 框选=放大
            ax1,ax2=sorted([o1[0],o2[0]]); ay1,ay2=sorted([o1[1],o2[1]])
            img=cv2.imread(lab.frames[lab.idx],cv2.IMREAD_COLOR); H,W=img.shape[:2]
            ax1=int(max(0,ax1)); ay1=int(max(0,ay1)); ax2=int(min(W,ax2)); ay2=int(min(H,ay2))
            if ax2-ax1>=12 and ay2-ay1>=12:
                lab.stack.append(lab.view); lab.view=(ax1,ay1,ax2,ay2)
    elif event==cv2.EVENT_RBUTTONDOWN:
        o=lab.disp_to_orig(x,y)
        if o is None: return
        ox,oy=o; best=None; bd=DEL_TOL
        pts=lab.points[lab.idx]
        for i,(px,py) in enumerate(pts):
            d=abs(px-ox)+abs(py-oy)
            if d<bd: bd=d; best=("p",i)
        anc=lab.anchors[lab.idx]
        if anc is not None and abs(anc[0]-ox)+abs(anc[1]-oy)<bd:
            best=("a",-1)
        if best is None: return
        if best[0]=="p": pts.pop(best[1])
        else: lab.anchors[lab.idx]=None

def draw_label(lab):
    fn=lab.frames[lab.idx]; img=cv2.imread(fn,cv2.IMREAD_COLOR); H,W=img.shape[:2]
    if lab.view is None: lab.reset_view(H,W)
    a,b,c,d=lab.view; sub=img[b:d,a:c]
    s=min(DW/float(c-a), DH/float(d-b)); rw,rh=int((c-a)*s),int((d-b)*s)
    ox,oy=(DW-rw)//2,(DH-rh)//2
    canvas=np.zeros((DH,DW,3),np.uint8)
    canvas[oy:oy+rh, ox:ox+rw]=cv2.resize(sub,(rw,rh),interpolation=cv2.INTER_NEAREST)
    lab._map=(s,ox,oy,a,b)
    def to_d(px,py): return (int(ox+(px-a)*s), int(oy+(py-b)*s))
    # 普通点
    for i,(px,py) in enumerate(lab.points[lab.idx]):
        xd,yd=to_d(px,py); cv2.circle(canvas,(xd,yd),6,(0,230,0),2)
    # 基点
    anc=lab.anchors[lab.idx]
    if anc is not None:
        xd,yd=to_d(*anc); cv2.circle(canvas,(xd,yd),9,(255,120,0),-1); cv2.circle(canvas,(xd,yd),10,(255,255,255),1)
    # 右下导航缩略
    th=150; tw=int(W*th/H); thb=cv2.resize(img,(tw,th))
    cv2.rectangle(thb,(int(a/W*tw),int(b/H*th)),(int(c/W*tw),int(d/H*th)),(0,255,255),2)
    canvas[DH-th-8:DH-8, DW-tw-8:DW-8]=thb
    # 顶部提示
    npt=len(lab.points[lab.idx]); has="有基点" if anc is not None else "无基点"
    tip=("%d/%d张 普通点%d %s | 左键加点,脚上点后[空格]定基点,右键删点,拖拽放大,R退回,n下一张,b上一张,q保存"
         %(lab.idx+1,len(lab.frames),npt,has))
    cv2.rectangle(canvas,(0,0),(DW,28),(0,0,0),-1)
    cv2.putText(canvas,tip,(8,20),cv2.FONT_HERSHEY_SIMPLEX,0.58,(0,255,255),1)
    zoom=(c-a)/W
    cv2.putText(canvas,"zoom %.1fx"%(1/zoom),(8,DH-14),cv2.FONT_HERSHEY_SIMPLEX,0.55,(200,200,200),1)
    return canvas

def finish_save(lab):
    os.makedirs(os.path.join(lab.dir,"patches"),exist_ok=True)
    rec=[]; entries=[]; no_anc=0; idx_e=0
    for fi,fn in enumerate(lab.frames):
        img=cv2.imread(fn,cv2.IMREAD_COLOR); H,W=img.shape[:2]
        pts=lab.points[fi]; anc=lab.anchors[fi]
        rec.append({"frame":os.path.basename(fn),"anchor":anc,"points":pts})
        if anc is None:
            if pts: no_anc+=1
            continue
        for (px,py) in pts:
            x1,x2=px-PATCH_R,px+PATCH_R+1; y1,y2=py-PATCH_R,py+PATCH_R+1
            if x1<0 or y1<0 or x2>W or y2>H: continue   # 贴边小块不入库
            patch=img[y1:y2,x1:x2]
            if patch.shape[0]!=PATCH_R*2+1 or patch.shape[1]!=PATCH_R*2+1: continue
            pf="patches/p_%02d_%02d.png"%(fi,idx_e); idx_e+=1
            cv2.imwrite(os.path.join(lab.dir,pf),patch)
            entries.append({"patch":pf,"dx":int(px-anc[0]),"dy":int(py-anc[1]),"frame":fi})
    json.dump(rec,open(os.path.join(lab.dir,"labels.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=1)
    fset={"patch_r":PATCH_R,"n_frames":len(lab.frames),"n_patches":len(entries),
           "frames_without_anchor":no_anc,"entries":entries}
    json.dump(fset,open(os.path.join(lab.dir,"char_feature_set.json"),"w",encoding="utf-8"),
              ensure_ascii=False,indent=1)
    print("SAVED:",lab.dir)
    print("小块数:%d  缺基点帧:%d / %d"%(len(entries),no_anc,len(lab.frames)))

def run_label(batch_dir):
    frames=sorted(glob.glob(os.path.join(batch_dir,"frame_*.png")))
    if not frames: print("该批次没有 frame_*.png:",batch_dir); return
    lab=Labeler(batch_dir,frames); win="LABEL 角色特征标注"
    cv2.namedWindow(win,cv2.WINDOW_NORMAL); cv2.resizeWindow(win,DW,DH)
    cv2.setMouseCallback(win,lab_mouse,lab)
    while True:
        cv2.imshow(win,draw_label(lab))
        k=cv2.waitKey(20)&0xFF
        if k==ord('q'):
            finish_save(lab); break
        elif k==ord(' '):
            pts=lab.points[lab.idx]
            if pts: lab.anchors[lab.idx]=pts.pop()   # 最后一点转基点
        elif k in (ord('n'),13):
            if lab.idx<len(frames)-1: lab.idx+=1; lab.view=None
            else: finish_save(lab); break
        elif k==ord('b'):
            lab.idx=max(0,lab.idx-1); lab.view=None
        elif k in (ord('r'),27):
            if lab.stack: lab.view=lab.stack.pop()
            else: lab.view=None
    cv2.destroyAllWindows()

# ============================ 采集 ============================
def run_capture():
    hwnd,rect=game_rect()
    if rect is None: print("找不到 MapleStory 窗口"); return
    try: user32.ShowWindow(hwnd,9); user32.SetForegroundWindow(hwnd)
    except Exception: pass
    time.sleep(0.6)
    tpls=load_templates(); sct=mss.mss()
    win="CAPTURE 角色采集(空格开始2秒 左键定框 ,.调大小 q退出)"
    cv2.namedWindow(win,cv2.WINDOW_NORMAL)
    box={"w":96,"h":116,"cx":None,"cy":None}
    st={"cap":False,"saved":0,"frames":[],"batch":None,"secs":DEFAULT_SEC,
        "total":int(round(DEFAULT_SEC*CAP_HZ))}
    def cap_mouse(e,x,y,fl,ud):
        if e==cv2.EVENT_LBUTTONDOWN:
            box["cx"],box["cy"]=int(x/DISP_SCALE),int(y/DISP_SCALE)
    cv2.setMouseCallback(win,cap_mouse,None)
    next_save=0
    while True:
        raw=np.array(sct.grab(rect))[:,:,:3]; gray=cv2.cvtColor(raw,cv2.COLOR_BGR2GRAY); now=time.time()
        f=tpl_foot(gray,tpls)
        if f is not None and not st["cap"]:
            box["cx"],box["cy"]=int(f[0]),int(f[1]-box["h"]//2)
        if st["cap"]:
            if st["saved"]==0:
                st["batch"]=os.path.join(CAP_ROOT,"batch_"+time.strftime("%Y%m%d_%H%M%S"))
                os.makedirs(st["batch"],exist_ok=True); next_save=now
            if now>=next_save and st["saved"]<st["total"]:
                fp=os.path.join(st["batch"],"frame_%02d.png"%st["saved"])
                cv2.imwrite(fp,raw); st["frames"].append(fp); st["saved"]+=1; next_save+=INTERVAL
            if st["saved"]>=st["total"]:
                print("采集完成%d张 -> %s，进入标注"%(st["total"],st["batch"]))
                cv2.destroyWindow(win); run_label(st["batch"]); return
        vis=raw.copy(); cx,cy=box["cx"],box["cy"]
        if cx is not None:
            cv2.rectangle(vis,(cx-box["w"]//2,cy-box["h"]//2),(cx+box["w"]//2,cy+box["h"]//2),
                          (0,0,255) if st["cap"] else (0,200,255),2)
        tag=("采集中 %d/%d [请持续做动作/放技能]"%(st["saved"],st["total"])) if st["cap"] else \
            ("空格采集 %.0f秒=%d张 | 按2/3切时长 | 采集时主动放技能让特效盖人的帧也入镜"%(st["secs"],st["total"]))
        cv2.rectangle(vis,(0,0),(vis.shape[1],28),(0,0,0),-1)
        cv2.putText(vis,tag,(8,20),cv2.FONT_HERSHEY_SIMPLEX,0.65,(0,255,255),2)
        cv2.imshow(win,cv2.resize(vis,(int(vis.shape[1]*DISP_SCALE),int(vis.shape[0]*DISP_SCALE))))
        k=cv2.waitKey(15)&0xFF
        if k==ord('q'): break
        elif k==ord(' ') and not st["cap"]:
            st.update(cap=True,saved=0,frames=[],total=int(round(st["secs"]*CAP_HZ)))
        elif k in (ord('2'),ord('3')) and not st["cap"]:
            st["secs"]=2.0 if k==ord('2') else 3.0
            st["total"]=int(round(st["secs"]*CAP_HZ))
        elif k==ord(','): box["w"]=max(40,box["w"]-8); box["h"]=max(48,box["h"]-8)
        elif k==ord('.'): box["w"]=min(220,box["w"]+8); box["h"]=min(260,box["h"]+8)
    cv2.destroyAllWindows()

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--label",default=""); a=ap.parse_args()
    if a.label: run_label(a.label)
    else: run_capture()
