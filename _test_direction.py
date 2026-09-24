# -*- coding: utf-8 -*-
"""离线验证 _platform_cross_direction(提取真实源码 exec,不启动GUI),用真实 route_007 两台数据。"""
import ast, io, json, textwrap
src = io.open('maple_route_ui.py', encoding='utf-8-sig').read()
src = src.replace('\r\r\n', '\n').replace('\r\n', '\n').replace('\r', '\n')
tree = ast.parse(src)
TOL = None
want = {'_platform_cross_direction', '_platform_y_avg', '_platform_points'}
got = {}
for n in tree.body:
    if isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name) and t.id == 'AUTO_TOP_LAYER_TOL':
                TOL = ast.literal_eval(n.value)
    if isinstance(n, ast.ClassDef) and n.name == 'MinimapRouteRecorder':
        for x in n.body:
            if isinstance(x, ast.FunctionDef) and x.name in want:
                got[x.name] = textwrap.dedent(ast.get_source_segment(src, x))
assert len(got) == 3, got.keys()
ns = {}
for name, code in got.items():
    exec(code, {'AUTO_TOP_LAYER_TOL': TOL}, ns)

real = json.load(io.open('data/route_007_platforms.json', encoding='utf-8'))['platforms']
def yavg(pf):
    pts = pf['points']; return sum(float(p[1]) for p in pts) / len(pts)
print('AUTO_TOP_LAYER_TOL=%s  真实两台yavg=%s' % (TOL, [round(yavg(p), 2) for p in real]))

class O: pass
o = O()
o.platforms = real
o._platform_points = lambda pf: ns['_platform_points'](o, pf)
o._platform_y_avg = lambda pf: ns['_platform_y_avg'](o, pf)
fn = ns['_platform_cross_direction']
def cfg(mode, sel, mp, edit=False):
    o.route_mode = mode; o._selected_platforms = sel; o._player_map_pos = mp; o._bound_edit = edit
P = F_ = 0
def chk(name, gotv, wantv):
    global P, F_
    if gotv == wantv: P += 1; print('[PASS]', name, gotv)
    else: F_ += 1; print('[FAIL]', name, 'got=', gotv, 'want=', wantv)

cfg('手动', [1], [50, 88], edit=True); chk('编辑态=random', fn(o), ('random', True, True))
cfg('随机', [], None);                 chk('随机=random', fn(o), ('random', True, True))
cfg('手动', [], None);                 chk('手动零勾选=random', fn(o), ('random', True, True))
cfg('手动', [9], [50, 88]);             chk('勾选台全失效=random', fn(o), ('random', True, True))
cfg('手动', [1], [50, 88]);             chk('单台=single不跨层', fn(o), ('single', False, False))
cfg('手动', [1, 2], [50, 74]);          chk('多台站顶层=只放行向下', fn(o), ('multi', False, True))
cfg('手动', [1, 2], [50, 88]);          chk('多台站底层=只放行向上', fn(o), ('multi', True, False))
cfg('手动', [1, 2], [50, 81]);          chk('多台在两层间=上下都放行', fn(o), ('multi', True, True))
cfg('手动', [1, 2], None);              chk('光点丢失=保守全放行', fn(o), ('multi', True, True))
print('\n==== 方向门控: PASS=%d FAIL=%d ====' % (P, F_))
import sys; sys.exit(1 if F_ else 0)
