# -*- coding: utf-8 -*-
"""离线单测: 小地图选梯 _pick_ladder_minimap 与对位分带 _ladder_mm_band(用户2026-09-21定稿规则)。
不实例化UI、不起线程,只调staticmethod喂构造数据断言。"""
import maple_route_ui as M
C = M.MinimapRouteRecorder

def ld(x, yt, yb):
    return {'id': 0, 'x': float(x), 'y_top': float(yt), 'y_bottom': float(yb)}

fails = []
def ck(name, cond, extra=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + extra if extra else ''))
    if not cond:
        fails.append(name)

# ---------- 选梯:光点(100,100),上行 ----------
L = [
    ld(105, 50, 105),    # A 右5, 底105差5<=10, 上通 -> 合格(右)
    ld(90, 40, 108),     # B 左10, 底108差8<=10, 上通 -> 合格(左)
    ld(108, 20, 60),     # C 底60差40>10 够不到 -> 排除
    ld(103, 95, 130),    # D 向下梯(底130差30,不上通) -> 排除
    ld(200, 40, 105),    # E X差100>60 -> 排除
]
a = C._pick_ladder_minimap(L, 100, 100, +1, +1)   # 怪在右 -> 选右A
ck('上行怪在右选A', a is not None and abs(a['x'] - 105) < 1e-6, str(a and a['x']))
a = C._pick_ladder_minimap(L, 100, 100, +1, -1)   # 怪在左 -> 选左B
ck('上行怪在左选B', a is not None and abs(a['x'] - 90) < 1e-6, str(a and a['x']))
a = C._pick_ladder_minimap(L, 100, 100, +1, None)  # 无怪侧 -> X最近=A(差5)
ck('上行无怪侧选X最近A', a is not None and abs(a['x'] - 105) < 1e-6, str(a and a['x']))

# ---------- 选梯:下行 ----------
Ld = [
    ld(95, 102, 160),    # 顶102差2<=10, 下通到160 -> 合格
    ld(105, 50, 105),    # 上梯,顶50差50 -> 排除
]
a = C._pick_ladder_minimap(Ld, 100, 100, -1, None)
ck('下行只选顶在光点附近且下通的梯', a is not None and abs(a['x'] - 95) < 1e-6, str(a and a['x']))

# ---------- 怪侧为空时放宽(右侧无合格梯,只有左侧一把) ----------
Lleft = [ld(80, 40, 105)]    # 左20,合格上行
a = C._pick_ladder_minimap(Lleft, 100, 100, +1, +1)  # 怪在右但右侧空 -> 放宽选左
ck('怪侧空放宽到对侧唯一合格梯', a is not None and abs(a['x'] - 80) < 1e-6, str(a and a['x']))

# ---------- 边界:空数据/None ----------
ck('空梯表返回None', C._pick_ladder_minimap([], 100, 100, +1, None) is None)
ck('光点None返回None', C._pick_ladder_minimap(L, None, 100, +1, None) is None)

# ---------- 高度门边界:底差恰好10合格、11排除 ----------
ck('底差=10合格', C._pick_ladder_minimap([ld(100, 40, 110)], 100, 100, +1, None) is not None)
ck('底差=11排除', C._pick_ladder_minimap([ld(100, 40, 111)], 100, 100, +1, None) is None)
# ---------- X带边界:差60合格、61排除(底差设0) ----------
ck('X差60在带内', C._pick_ladder_minimap([ld(160, 40, 100)], 100, 100, +1, None) is not None)
ck('X差61出带排除', C._pick_ladder_minimap([ld(161, 40, 100)], 100, 100, +1, None) is None)

# ---------- 分带 rj=7 vl=1 (新三档:vert/fine/walk;带速跑跳不再由band判,移到goto跨线下降沿,见_test_mm_goto) ----------
expect = {0: 'vert', 1: 'vert', 2: 'fine', 3: 'fine', 4: 'walk', 5: 'walk',
          6: 'walk', 7: 'walk', 8: 'walk', 12: 'walk'}
for ad, want in expect.items():
    got = C._ladder_mm_band(ad, 7, 1)
    ck('分带ad=%d->%s' % (ad, want), got == want, 'got=%s' % got)

print()
if fails:
    print('==== %d CASES FAILED: %s' % (len(fails), fails))
    raise SystemExit(1)
print('==== ALL MINIMAP LADDER TESTS PASSED ====')
