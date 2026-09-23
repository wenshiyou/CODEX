# -*- coding: utf-8 -*-
# 探针(不提交git):用真实录制梯子数据离线验证 _pick_ladder_minimap 选段规则
# 旧=过门后只按X最近; 新=先X最近定列->同列上下段并入(Y不重叠)->上行取底端最靠下/下行取顶端最靠上
import json, io, os

X_HALF=60; END_TOL=10; MIN_LEN=5; SAME_COL_X=15; SAME_COL_OV=2

def hok(t, dy, cdir):
    tt,tb,dy=float(t['y_top']),float(t['y_bottom']),float(dy)
    if (tb-tt)<MIN_LEN: return False
    if cdir is not None and cdir<0:
        return abs(tt-dy)<=END_TOL and tb>=dy+END_TOL
    return abs(tb-dy)<=END_TOL and tt<=dy

def _cand(ladders,dx,dy,cdir,side_sign,bad=None):
    c=[]
    for t in ladders:
        if abs(float(t['x'])-dx)>X_HALF: continue
        if bad and t.get('id') in bad: continue
        if hok(t,dy,cdir): c.append(t)
    if side_sign:
        s=[t for t in c if (float(t['x'])-dx)*float(side_sign)>0]
        if s: c=s
    return c

def pick_old(ladders,dx,dy,cdir=1,side_sign=None,bad=None):
    c=_cand(ladders,dx,dy,cdir,side_sign,bad)
    if not c: return None
    return min(c,key=lambda t:abs(float(t['x'])-dx))

def pick_new(ladders,dx,dy,cdir=1,side_sign=None,bad=None):
    c=_cand(ladders,dx,dy,cdir,side_sign,bad)
    if not c: return None
    best=min(c,key=lambda t:abs(float(t['x'])-dx)); bx=float(best['x'])
    def same(t):
        if t is best: return True   # 定列基准自身必在同列(单段自身重叠=梯长,不能被重叠条件误排)
        if abs(float(t['x'])-bx)>SAME_COL_X: return False
        ov=min(float(t['y_bottom']),float(best['y_bottom']))-max(float(t['y_top']),float(best['y_top']))
        return ov<=SAME_COL_OV
    col=[t for t in c if same(t)] or [best]
    if cdir is not None and cdir<0:
        return min(col,key=lambda t:(float(t['y_top']),abs(float(t['x'])-dx)))
    return max(col,key=lambda t:(float(t['y_bottom']),-abs(float(t['x'])-dx)))

base=os.path.dirname(os.path.abspath(__file__))
lds=json.load(io.open(os.path.join(base,'data','route_005_ladders.json'),encoding='utf-8-sig'))['ladders']
def L(i): return next(t for t in lds if t['id']==i)

results=[]
def case(name, dx,dy,cdir,side,expect_id,note):
    o=pick_old(lds,dx,dy,cdir,side); n=pick_new(lds,dx,dy,cdir,side)
    oi=o['id'] if o else None; ni=n['id'] if n else None
    ok=(ni==expect_id)
    results.append(ok)
    print("[%s] %s | 光点(%g,%g) cdir=%d side=%s | 旧选id=%s 新选id=%s 期望=%s %s" % (
        'PASS' if ok else 'FAIL',note,dx,dy,cdir,side,oi,ni,expect_id,'' if ok else '<<< 不符'))

print("=== route_005 同列上下段(核心bug: id3中74-87 / id5上65-72, X差3) ===")
# 人在中段高度dy=80, 光点x=73: id3与id5同时过门, 旧按X选id5(上段,错), 新应选id3(底端最靠下起步段)
case("mid",73,80,+1,None,3,"dy80 同列id3/id5同时过门,应选靠下起步段id3")
case("mid",76,78,+1,None,3,"dy78 光点x76,同列应选id3")
# 人到上段衔接dy=74: 只剩id5过门
case("up",73,74,+1,None,5,"dy74 应选上段id5")
case("up",73,72,+1,None,5,"dy72 应选id5")

print("=== 同层不同列(必须仍按X最近列,不能被别列更大bot拉走) ===")
# 右侧id1列 dy97: id0(102,b98)/id1(156,b96)/id2(68,b104)都过门, 人在x150
case("r",150,97,+1,None,1,"右侧id1列,无side按X最近=id1")
case("rside",150,97,+1,+1,1,"怪在右,side=+1必选id1")
# 人在中间id0列x102: id2 bot104更大但在x68不同列, 不能被拉走, 选id0
case("midcol",102,97,+1,None,0,"人在id0列,id2底端更低但不同列,仍选id0")
# 人在左id2列x68 dy104: 选id2
case("l",68,104,+1,None,2,"左列id2(x68,bot104贴光点)选id2")

print("=== id8(144,72-82)/id1(156,82-96) 同列两段X差12、Y首尾相接 ===")
# dy=82 上行: id8 bot82差0 top72<=82过门; id1 bot96差14不过门 -> id8
case("c8",150,82,+1,None,8,"dy82 选下段id8")
# dy=90: id1 bot96差6过门; id8 bot82差8过门 top72<=90 -> 同列(X差12,重叠0), 上行取bot大=id1
case("c1",150,90,+1,None,1,"dy90 id8/id1同列过门,取靠下id1")

print("=== 废点 id4(长2px) 永不选 ===")
n=pick_new(lds,81,73,+1,None)
results.append(n is not None and n['id']!=4)
print("[%s] 光点正对id4(81,73): 新选id=%s(不得为废点4)" % ('PASS' if n and n['id']!=4 else 'FAIL', n['id'] if n else None))

print("=== 无合格梯 ===")
n=pick_new(lds,300,300,+1,None)
results.append(n is None)
print("[%s] 远处光点选梯=%s(应None)" % ('PASS' if n is None else 'FAIL', n['id'] if n else None))

print("=== 下行 cdir=-1 单段场景不回归(应与旧规则一致) ===")
def parity(dx,dy,note):
    o=pick_old(lds,dx,dy,-1,None); n=pick_new(lds,dx,dy,-1,None)
    oi=o['id'] if o else None; ni=n['id'] if n else None
    # 单段列: 新旧必须一致
    ok=(oi==ni); results.append(ok)
    print("[%s] %s 光点(%g,%g) 旧=%s 新=%s" % ('PASS' if ok else 'FAIL',note,dx,dy,oi,ni))
parity(76,72,"下行 人在上层id3列dy72")
parity(150,82,"下行 id1列dy82")
parity(102,72,"下行 id0列dy72")
# 下行同列多段: 取顶端最靠上(y_top最小)
# 构造: id8(72-82)与id1(82-96)同列, 人在dy=83往下: 下行过门 top贴83且bot>=93 -> id1(top82,bot96)
o=pick_old(lds,150,83,-1,None); n=pick_new(lds,150,83,-1,None)
oi=o['id'] if o else None; ni=n['id'] if n else None
print("[info] 下行dy83 id8/id1列: 旧=%s 新=%s (下行应接顶端最靠上可下通段)"%(oi,ni))

print("=== 单段列 新旧一致性(全数据扫描, 多光点) ===")
mism=0; tot=0
for x in range(20,170,6):
    for y in range(60,110,3):
        for cs in (None,-1,+1):
            o=pick_old(lds,float(x),float(y),+1,cs); n=pick_new(lds,float(x),float(y),+1,cs)
            oi=o['id'] if o else None; ni=n['id'] if n else None
            tot+=1
            # 仅统计"候选里不存在同列上下段"的格子, 这些新旧必须一致
            cc=_cand(lds,float(x),float(y),+1,cs)
            # 判该格候选是否含同列多段(重叠<=2且X差<=15的两个不同段)
            multi=False
            for a in range(len(cc)):
                for b in range(a+1,len(cc)):
                    A,B=cc[a],cc[b]
                    if abs(float(A['x'])-float(B['x']))<=SAME_COL_X:
                        ov=min(float(A['y_bottom']),float(B['y_bottom']))-max(float(A['y_top']),float(B['y_top']))
                        if ov<=SAME_COL_OV: multi=True
            if not multi and oi!=ni:
                mism+=1; print("  单段格不一致! x=%d y=%d side=%s 旧=%s 新=%s"%(x,y,cs,oi,ni))
results.append(mism==0)
print("[%s] 单段格扫描共%d格, 新旧不一致=%d" % ('PASS' if mism==0 else 'FAIL',tot,mism))

print("\n==== %s ====" % ("ALL PASS" if all(results) else "HAS FAILURE") )
