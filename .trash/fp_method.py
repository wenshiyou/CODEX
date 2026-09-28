# -*- coding: utf-8 -*-
# 融合预测器(替换_dot_predict_pos+_predict_char_pos两方法,由拼接脚本合入)
    def _fused_predict_pos(self, now_ms):
        """【融合预测器·用户2026-09-28白黄合一】一个持续预测位,锚点只校准不接管,不依赖黑框绝对映射。
        预测位=校准点(锚点新鲜时每帧刷=贴人,不超前)+自校准以来光点位移×k(事实通道,一次减法不累积
        噪声;瞬移跳变光点自己会跳,天然捕获不重复注入);k没学到且丢失中→回退意图通道(按键×学习速度/
        瞬移注入,旧白框逻辑);垂直不学比率(用户定),climbing中Y用意图vy外推。返回(x,y,半径,状态)或None。"""
        tr = getattr(self, '_role_track', None)
        if not tr or not tr.get('last'):
            self._fp = None
            return None
        ax, ay = tr['last']
        _dot = getattr(self, '_player_map_pos', None)
        _fresh = (now_ms - tr.get('last_t', 0.0)) <= FP_ANCHOR_FRESH_MS
        fp = self._fp
        if fp is None:
            self._fp = fp = {}
        # 1) 锚点新鲜→重校准(校准点=锚点位置+当时光点位置);预测位贴回人身上
        if _fresh or fp.get('cal_x') is None:
            fp['cal_x'] = float(ax); fp['cal_y'] = float(ay); fp['cal_t'] = now_ms
            fp['cal_mx'] = float(_dot[0]) if _dot else None
            fp['cal_my'] = float(_dot[1]) if _dot else None
        _px, _py = fp['cal_x'], fp['cal_y']
        _status = '校准' if _fresh else '回退'
        # 2) 事实通道:自校准以来光点位移×k(走路/斜坡/瞬移跳变全在光点位移里,一次减法)
        _scene = self._kal_scene_now(now_ms)
        _k = self._kal_k.get(_scene)
        if _k is None:
            _k = self._kal_k.get('jump') if _scene == 'walk' else self._kal_k.get('walk')
        if _dot is not None and fp.get('cal_mx') is not None and _k is not None:
            _px += (float(_dot[0]) - fp['cal_mx']) * _k
            _status = '光点+校准' if _fresh else '光点'
        elif not _fresh:
            # 3) 意图回退(仅丢失中且k不可用):瞬移后摇→按键×学习速度(旧白框逻辑)
            _dt = max(0.0, (now_ms - fp['cal_t']) / 1000.0)
            _kl = bool(key_pressed(VK_LEFT)); _kr = bool(key_pressed(VK_RIGHT))
            if now_ms < getattr(self, '_combat_tp_post_until', 0):
                _td = int(getattr(self, '_pred_learn_tp', 250) or 250)
                _tdir = getattr(self, '_combat_last_tp_dir', 0)
                if _tdir != 0:
                    _px += _tdir * _td
                    _status = '瞬移注入'
                else:
                    _status = '瞬移待向'
            else:
                _vx = getattr(self, '_pred_learn_vx', 400.0)
                if _kl and not _kr:
                    _px -= _vx * _dt; _status = '意图左'
                elif _kr and not _kl:
                    _px += _vx * _dt; _status = '意图右'
                else:
                    _status = '静止回退'
        # 4) 垂直:不学比率(用户定),仅climbing中按意图vy外推Y
        if getattr(self, '_climb_state', 'none') in ('climbing', 'post_jump'):
            _dt2 = max(0.0, (now_ms - fp['cal_t']) / 1000.0)
            _vy = getattr(self, '_pred_learn_vy', 120.0)
            if key_pressed(VK_UP):
                _py -= _vy * _dt2; _status += '上梯'
            elif key_pressed(VK_DOWN):
                _py += _vy * _dt2; _status += '下梯'
        # 5) 半径:刚校准收窄/丢失>2s放大/常态基础
        _since = now_ms - fp['cal_t']
        _rad = FP_RAD_TIGHT if _since <= 300 else (FP_RAD_WIDE if _since > 2000 else FP_RAD_BASE)
        return (int(_px), int(_py), _rad, _status)
