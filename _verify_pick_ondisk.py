# -*- coding: utf-8 -*-
# 复验(不提交git): 从落盘后的 maple_route_ui.py 用AST抽出真实 _pick_ladder_minimap/_ladder_mm_height_ok,
# 喂真实录制梯子数据,确认落盘版本=离线验证版本,且单段格相对旧规则零回归。
import ast, io, os, json, textwrap

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
src = io.open(P, 'rb').read().decode('utf-8-sig')
tree = ast.parse(src)

need = {'LADDER_MM_X_HALF','LADDER_MM_END_TOL','LADDER_MM_MIN_LEN',
        'LADDER_MM_SAME_COL_X','LADDER_MM_SAME_COL_OV'}
ns = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0], ast.Name):
        nm = node.targets[0].id
        if nm in need:
            ns[nm] = ast.literal_eval(node.value)
print("抽到常量:", {k: ns[k] for k in sorted(need)})
assert need <= set(ns), "缺常量: %s" % (need-set(ns))

funcs = {}
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in ('_ladder_mm_height_ok','_pick_ladder_minimap'):
        funcs[node.name] = textwrap.dedent(ast.get_source_segment(src, node))
assert len(funcs)==2, funcs.keys()
exec(funcs['_ladder_mm_height_ok'], ns)
# _pick 内类名调用替换为同ns函数
exec(funcs['_pick_ladder_minimap'].replace('MinimapRouteRecorder.', ''), ns)
pick_new = ns['_pick_ladder_minimap']
hok = ns['_ladder_mm_height_ok']
X_HALF=ns['LADDER_MM_X_HALF']; END_TOL=ns['LADDER_MM_END_TOL']; MIN_LEN=ns['LADDER_MM_MIN_LEN']
SCX=ns['LADDER_MM_SAME_COL_X']; SCOV=ns['LADDER_MM_SAME_COL_OV']

# 旧基线(过门后只按X最近)
def pick_old(ladders,dx,dy,cdir=1,side=None,bad=None):
    c=[]
    for t in ladders:
        if abs(float(t['x'])-dx)>X_HALF: continue
        if hok(t,dy,cdir): c.append(t)
    if side:
        s=[t for t in c if (float(t['x'])-dx)*float(side)>0]
        if s: c=s
    return min(c,key=lambda t:abs(float(t['x'])-dx)) if c else None

base=os.path.dirname(os.path.abspath(__file__))
lds=json.load(io.open(os.path.join(base,'data','route_005_ladders.json'),encoding='utf-8-sig'))['ladders']
res=[]
def case(name,dx,dy,cdir,side,exp):
    n=pick_new(lds,dx,dy,cdir,side); ni=n['id'] if n else None
    ok=ni==exp; res.append(ok)
    print("[%s] %s 光点(%g,%g) cdir=%d side=%s -> id=%s 期望%s"%('PASS' if ok else 'FAIL',name,dx,dy,cdir,side,ni,exp))

case("dy80同列选靠下id3",73,80,1,None,3)
case("dy78选id3",76,78,1,None,3)
case("dy74选id5",73,74,1,None,5)
case("dy72选id5",73,72,1,None,5)
case("右列id1",150,97,1,None,1)
case("怪右side id1",150,97,1,1,1)
case("id0列不被id2拉走",102,97,1,None,0)
case("左列id2",68,104,1,None,2)
case("dy82选id8",150,82,1,None,8)
case("dy90同列选靠下id1",150,90,1,None,1)
n=pick_new(lds,81,73,1,None); res.append(n['id']!=4); print("[%s] 废点id4不选 -> %s"%('PASS' if n['id']!=4 else 'FAIL',n['id']))
res.append(pick_new(lds,300,300,1,None) is None); print("[%s] 无梯=None"%'PASS')
for dx,dy,nm in [(76,72,'下行id3'),(150,82,'下行id1'),(102,72,'下行id0')]:
    o=pick_old(lds,dx,dy,-1,None); nw=pick_new(lds,dx,dy,-1,None)
    oi=o['id'] if o else None; ni=nw['id'] if nw else None
    ok=oi==ni; res.append(ok); print("[%s] %s 旧%s 新%s"%('PASS' if ok else 'FAIL',nm,oi,ni))

# 全格: 不含同列上下多段的格子, 新旧必须一致
def cand(dx,dy,cdir,side):
    c=[t for t in lds if abs(float(t['x'])-dx)<=X_HALF and hok(t,dy,cdir)]
    if side:
        s=[t for t in c if (float(t['x'])-dx)*float(side)>0]
        if s: c=s
    return c
mism=0; tot=0
for x in range(20,170,4):
    for y in range(60,110,2):
        for side in (None,-1,1):
            cc=cand(float(x),float(y),1,side); tot+=1; multi=False
            for a in range(len(cc)):
                for b in range(a+1,len(cc)):
                    A,B=cc[a],cc[b]
                    if abs(float(A['x'])-float(B['x']))<=SCX:
                        ov=min(float(A['y_bottom']),float(B['y_bottom']))-max(float(A['y_top']),float(B['y_top']))
                        if ov<=SCOV: multi=True
            o=pick_old(lds,float(x),float(y),1,side); nw=pick_new(lds,float(x),float(y),1,side)
            oi=o['id'] if o else None; ni=nw['id'] if nw else None
            if not multi and oi!=ni: mism+=1; print("  单段格不一致 x%d y%d side%s 旧%s 新%s"%(x,y,side,oi,ni))
res.append(mism==0)
print("[%s] 全格%d 单段格不一致=%d"%('PASS' if mism==0 else 'FAIL',tot,mism))
print("\n==== %s ===="%("ALL PASS (落盘版本)" if all(res) else "HAS FAILURE"))
