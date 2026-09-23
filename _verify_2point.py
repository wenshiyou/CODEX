# -*- coding: utf-8 -*-
# 复验(不提交git): 二点式 extract_ladder + 同列整条覆盖, 全部基于落盘真实代码/真实录制数据
import ast, io, os, json, textwrap
from types import SimpleNamespace

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
src = io.open(P, 'rb').read().decode('utf-8-sig')
tree = ast.parse(src)

# 抽常量
const = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id == 'LADDER_REC_SAME_COL_X':
            const['REC_X'] = ast.literal_eval(node.value)
print("常量 LADDER_REC_SAME_COL_X =", const.get('REC_X'))
assert const.get('REC_X') == 8

# 抽 extract_ladder
extr_src = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'extract_ladder':
        extr_src = textwrap.dedent(ast.get_source_segment(src, node)); break
assert extr_src and 'p0, p1 = points[0], points[-1]' in extr_src, "落盘extract不是二点式"
ns = {'_debug_log': lambda *a, **k: None}
exec(extr_src, ns)
extract_ladder = ns['extract_ladder']
self0 = SimpleNamespace(ladders=[])

res = []
def chk(ok, msg):
    res.append(ok); print("[%s] %s" % ('PASS' if ok else 'FAIL', msg))

# 1) 两点式: 首尾(70,104)底/(76,65)顶, 中间塞大量离群晃动点, 结果必须只由首尾决定
pts = [(70,104),(95,99),(48,96),(120,90),(30,84),(200,80),(5,75),(88,70),(76,65)]
r = extract_ladder(self0, pts)
chk(len(r)==1 and r[0]['x']==73.0 and r[0]['y_top']==65.0 and r[0]['y_bottom']==104.0,
    "含中间晃动点: x=%.1f(期望73=首尾均值) top=%.1f(65) bot=%.1f(104), 中间点不影响" % (
        r[0]['x'], r[0]['y_top'], r[0]['y_bottom']))
# 2) 只有首尾两点(正常二点式)
r2 = extract_ladder(self0, [(70,104),(76,65)])
chk(r2[0]['x']==73.0 and r2[0]['y_top']==65.0 and r2[0]['y_bottom']==104.0, "恰好两点正常")
# 3) 反向顺序(先顶后底)结果一致
r3 = extract_ladder(self0, [(76,65),(70,104)])
chk(r3[0]['y_top']==65.0 and r3[0]['y_bottom']==104.0, "先顶后底 min/max 仍正确")
# 4) 点数不足
chk(extract_ladder(self0, []) == [] and extract_ladder(self0, [(70,104)]) == [], "0/1点返回空")

# 5) 同列整条覆盖(复刻落盘判定式 abs(old.x-new.x)<REC_X), 用 route_005 真实碎段
base = os.path.dirname(os.path.abspath(__file__))
lds = json.load(io.open(os.path.join(base,'data','route_005_ladders.json'), encoding='utf-8-sig'))['ladders']
RX = const['REC_X']
def same_ids(lst, newx):
    return sorted(old['id'] for old in lst if abs(float(old['x'])-newx) < RX)

chk(same_ids(lds,74)==[2,3,4,5], "录右列x=74 命中同列碎段 %s(期望[2,3,4,5])" % same_ids(lds,74))
chk(same_ids(lds,150)==[1,8], "录右二列x=150 命中 %s(期望[1,8])" % same_ids(lds,150))
chk(same_ids(lds,59)==[6], "录左列x=59 只命中id6 %s(不吞x68的id2,差9)" % same_ids(lds,59))
chk(same_ids(lds,102)==[0], "x=102 只命中id0 %s" % same_ids(lds,102))
chk(same_ids(lds,200)==[], "全新列x=200 无同列->新增 %s" % same_ids(lds,200))

# 6) 完整重录序列: 右列端到端 -> 右二列端到端, 断言碎段合并、并排不吞
work = [dict(t) for t in lds]
def record(newx, top, bot):
    idx = [i for i,o in enumerate(work) if abs(float(o['x'])-newx) < RX]
    if idx:
        keep = min(work[i].get('id',len(work)) for i in idx)
        first = min(idx)
        for i in sorted(idx, reverse=True):
            work.pop(i)
        work.insert(first, {'id':keep,'x':float(newx),'y_top':float(top),'y_bottom':float(bot)})
    else:
        work.append({'id':len(work),'x':float(newx),'y_top':float(top),'y_bottom':float(bot)})
record(74,65,104)   # 右列整梯(覆盖id2/3/4/5)
record(150,72,96)   # 右二列整梯(覆盖id1/8)
ids = [t['id'] for t in work]   # 物理顺序(非排序), 验证insert保持列表位置
chk(ids==[0,1,2,6], "重录两列后物理顺序 %s(期望[0,1,2,6],新梯插回原列位置); 并排id6(x59)保留" % ids)
x59 = [t for t in work if abs(float(t['x'])-59)<RX]
chk(len(x59)==1, "并排左梯x59仍在且唯一(未被右列覆盖)")
right = [t for t in work if t['id']==2][0]
chk(right['y_top']==65 and right['y_bottom']==104, "右列合并为端到端一条 top65/bot104")

print("\n==== %s ====" % ("ALL PASS (二点式+同列覆盖)" if all(res) else "HAS FAILURE"))
