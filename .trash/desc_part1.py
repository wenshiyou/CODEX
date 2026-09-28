# -*- coding: utf-8 -*-
# 影子法下行状态机(由拼接脚本合入主文件,拼完即删)
    def _dot_moving_state(self):
        """影子光点运动状态(用户2026-09-28影子法定稿):返回'down'/'up'/'left'/'right'/'still'/'unknown'。
        以光点最近一拍(DOT_SHADOW_LAG_MS净位移)为准——向下跳成功时光点Y增大=down;落地静止=still。
        光点或影子无效='unknown'(挂起不判)。"""
        _sh = getattr(self, '_dot_shadow_pos', None)
        _dot = getattr(self, '_player_map_pos', None)
        if _sh is None or _dot is None:
            return 'unknown'
        _dx = float(_dot[0]) - float(_sh[0])
        _dy = float(_dot[1]) - float(_sh[1])
        _dead = DOT_SHADOW_DEAD_PX
        if abs(_dx) < _dead and abs(_dy) < _dead:
            return 'still'
        if abs(_dy) >= abs(_dx):
            return 'down' if _dy > 0 else 'up'
        return 'right' if _dx > 0 else 'left'

    def _desc_ladder_side_blocked(self, px, py, side):
        """下行避梯选位(用户2026-09-28):side侧(1=右/-1=左)距光点X在DESC_AVOID_LADDER_MM内、
        且梯身竖向覆盖光点Y附近(梯顶<=py+6<=梯底或接近)=该侧有梯,横跳/下跳落位会巴梯。
        返回True=该侧有梯要避开。"""
        for _ld in (getattr(self, 'ladders', None) or []):
            try:
                _lx = float(_ld.get('x', 0))
                _t = float(_ld.get('y_top', 0))
                _b = float(_ld.get('y_bottom', 0))
            except (TypeError, ValueError):
                continue
            if _lx == 0 and _t == 0 and _b == 0:
                continue
            _dxl = (_lx - float(px)) * side   # 正=该侧方向上的距离
            if 0 < _dxl <= DESC_AVOID_LADDER_MM and (_t - 8) <= py <= (_b + 8):
                return True   # 该侧半径内有梯且梯身覆盖人物高度
        return False

    def _pick_desc_side(self, px=None, py=None):
        """下行横跳方向(用户2026-09-28影子法定稿重写):避开有梯子的一侧——右有梯选左,左有梯选右,
        两侧都有梯或都没有=随机(两侧都有时横跳本身会解挂,由后续后脑检测兜底)。"""
        _r = self._desc_ladder_side_blocked(px, py, 1)
        _l = self._desc_ladder_side_blocked(px, py, -1)
        if _r and not _l:
            _d = -1
        elif _l and not _r:
            _d = 1
        else:
            _d = random.choice([-1, 1])
        _debug_log('[下行] 横跳侧选择:右梯=%s 左梯=%s → 向%s' % (
            '有' if _r else '无', '有' if _l else '无', '右' if _d > 0 else '左'))
        return _d
