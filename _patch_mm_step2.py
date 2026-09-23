# -*- coding: utf-8 -*-
"""施工补丁Step2: 新增小地图选梯纯函数 + 对位分带纯函数(staticmethod,纯新增不接调用链)。
保持 BOM(utf-8-sig)/CRLF(newline=''),锚点唯一断言。"""
import io

P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(P, 'r', encoding='utf-8-sig', newline='') as f:
    text = f.read()

anchor = '    def _pin_ladder_by_player_dot(self, dot_x, dot_y):'
assert text.count(anchor) == 1, 'anchor count=%d' % text.count(anchor)
assert '_pick_ladder_minimap' not in text, '选梯函数已存在,勿重复打补丁'

methods = '''    @staticmethod
    def _pick_ladder_minimap(ladders, dot_x, dot_y, cdir, side_sign):
        """小地图光点+录制梯选梯(用户2026-09-21最终定稿,取代游戏窗口白框特征选梯)。坐标全为小地图块像素
        (与find_player_dot/self.ladders同空间)。ladders=[{x,y_top,y_bottom}],dot=光点,cdir=+1上行/-1下行,
        side_sign=怪相对人水平侧(-1怪在左优先梯x<光点/+1怪在右优先梯x>光点/None无怪参照不卡侧)。
        规则:X带|梯x-光点x|<=LADDER_MM_X_HALF;高度门 上行|y_bottom-光点Y|<=END_TOL且梯身上通(y_top<=光点Y-END_TOL),
        下行|y_top-光点Y|<=END_TOL且梯身下通(y_bottom>=光点Y+END_TOL);怪侧优先、怪侧空再放宽;最终取|x-光点|最小。返回dict或None。"""
        if not ladders or dot_x is None or dot_y is None:
            return None
        dx, dy = float(dot_x), float(dot_y)

        def _ok(t):
            tx, tt, tb = float(t['x']), float(t['y_top']), float(t['y_bottom'])
            if abs(tx - dx) > LADDER_MM_X_HALF:
                return False
            if cdir is not None and cdir < 0:
                return abs(tt - dy) <= LADDER_MM_END_TOL and tb >= dy + LADDER_MM_END_TOL
            return abs(tb - dy) <= LADDER_MM_END_TOL and tt <= dy - LADDER_MM_END_TOL

        cand = [t for t in ladders if _ok(t)]
        if not cand:
            return None
        if side_sign:
            side = [t for t in cand if (float(t['x']) - dx) * float(side_sign) > 0]
            if side:
                cand = side
        return min(cand, key=lambda t: abs(float(t['x']) - dx))

    @staticmethod
    def _ladder_mm_band(ad, rj, vl):
        """小地图对位分带(ad=|梯x-光点x|小地图单位;rj=面板跑跳距离默认7;vl=面板直跳距离默认1)。
        'far'=ad>rj按住走;'run'=rj-1<=ad<=rj带速跑跳;'vert'=ad<=vl原地直跳;'fine'=vl<ad<=FINE_DX微调点动;'near'=其余按住走。"""
        if ad > rj:
            return 'far'
        if ad >= rj - 1:
            return 'run'
        if ad <= vl:
            return 'vert'
        if ad <= LADDER_MM_FINE_DX:
            return 'fine'
        return 'near'

'''
methods = methods.replace('\r\n', '\n').replace('\n', '\r\n')
text = text.replace(anchor, methods + anchor, 1)

with io.open(P, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(text)
print('STEP2 OK: minimap pick + band staticmethods inserted')
