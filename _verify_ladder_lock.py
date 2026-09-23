# -*- coding: utf-8 -*-
import io,json,ast,importlib.util,sys
base=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"
src_p=base+r"\maple_route_ui.py"

# ---------- 1) AST 命名遮蔽扫描: def方法名 ∩ self.x= 属性名 必须为空 ----------
tree=ast.parse(io.open(src_p,'rb').read().decode('utf-8-sig'))
methods=set(); attrs=set()
for node in ast.walk(tree):
    if isinstance(node,ast.ClassDef):
        for b in node.body:
            if isinstance(b,(ast.FunctionDef,ast.AsyncFunctionDef)):
                methods.add(b.name)
    if isinstance(node,ast.Assign):
        for t in node.targets:
            if isinstance(t,ast.Attribute) and isinstance(t.value,ast.Name) and t.value.id=='self':
                attrs.add(t.attr)
shadow=methods & attrs
print("AST遮蔽交集(应为空):", shadow if shadow else "空 OK")
assert not shadow, "存在命名遮蔽!"
for newf in ['_ladder_mm_height_ok']:
    assert newf in methods, "缺方法 "+newf
assert '_ladder_mm_bad' in attrs, "缺字段 _ladder_mm_bad"
print("新增方法/字段就位 OK")

# ---------- 2) import 真实模块取静态方法/常量 ----------
spec=importlib.util.spec_from_file_location("mru",src_p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
R=m.MinimapRouteRecorder
H=R._ladder_mm_height_ok
P=R._pick_ladder_minimap
END=m.LADDER_MM_END_TOL; MINLEN=m.LADDER_MM_MIN_LEN; XH=m.LADDER_MM_X_HALF
print("常量 END_TOL=%s MIN_LEN=%s X_HALF=%s BAD_MS=%s"%(END,MINLEN,XH,m.LADDER_MM_BAD_COOLDOWN_MS))
assert (END,MINLEN,XH)==(10,5,60)
assert not hasattr(m,'LADDER_MM_GOTO_END_TOL'), "旧常量未删干净"

# ---------- 3) route_004 真实数据 + 现场光点(133,84) ----------
d=json.load(io.open(base+r"\data\route_004_ladders.json",'r',encoding='utf-8-sig'))
lds=d if isinstance(d,list) else d.get('ladders',d)
by={t['id']:t for t in lds}
px,py=133,84
def tid(t): return t.get('id',(t['x'],t['y_top'],t['y_bottom']))
# 废梯 id4 len2 必须 height_ok=False
assert H(by[4],py,+1) is False, "废梯id4应判否"
# 真实短梯 id3(len13)/id8(len10) 合格
assert H(by[3],py,+1) is True,  "id3应合格"
assert H(by[8],py,+1) is True,  "id8应合格"
# 选梯:X带内Y合格取|x-光点|最小 => id8(x144差11)
picked=P(lds,px,py,+1,None)
assert tid(picked)==8, "应选id8, 实际%r"%(tid(picked),)
# 拉黑 id8 => 改选 id3; 都拉黑 => None(走NOPICK回主线)
assert tid(P(lds,px,py,+1,None,bad_ids={8}))==3
assert P(lds,px,py,+1,None,bad_ids={8,3}) is None
print("现场光点(133,84): 废梯id4排除, 选梯=id8, 拉黑降级=id3, 全拉黑=None  OK")

# ---------- 4) 选梯Y门 与 锁后复核 必须永远一致(同函数); 并复现旧逻辑不一致 ----------
def old_pick(tb,tt,dy): return abs(tb-dy)<=10 and tt<=dy-10
def old_goto(tb,tt,dy): return abs(tb-dy)<=14 and tt<=dy-14
mismatch_old=0
for t in lds:
    tt,tb=float(t['y_top']),float(t['y_bottom'])
    for dy in range(55,115):
        # 新逻辑:选梯Y门(height_ok) 与 锁后复核(height_ok) 同一结果
        a=H(t,dy,+1)
        # 旧逻辑只对"非废梯"统计不一致(废梯旧逻辑也无len门,这里仅证明阈值错配)
        if (tb-tt)>=MINLEN and old_pick(tb,tt,dy)!=old_goto(tb,tt,dy):
            mismatch_old+=1
print("旧逻辑(选10/锁14)在真实梯+dy55~114上 选锁不一致样本数:",mismatch_old,"(>0即旧永振根因)")
assert mismatch_old>0

# ---------- 5) 下行:废梯排除、真梯下通 ----------
assert H(by[4],72,-1) is False, "下行废梯id4应否"
assert H(by[0],72,-1) is True, "下行id0(tt72贴光点/tb98下通)应合格"
# 下行选梯不接受bad参数也能跑(默认None)
assert P(lds,102,72,-1,None) is not None
print("下行门 OK")

# ---------- 6) 边界:整把梯在人下方的不能当上行梯 ----------
# tb=dy+10,len5 => tt=dy+5 >dy => 上行否
assert H({'y_top':89,'y_bottom':94},84,+1) is False
# tb=dy-10,len5 => tt=dy-15<=dy => 上行合格(梯在人上方)
assert H({'y_top':69,'y_bottom':74},84,+1) is True
print("上行方向边界 OK")
print("\n全部断言通过")
