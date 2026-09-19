# -*- coding: utf-8 -*-
"""田字诊断 v2:只增强诊断器自身(不碰任何业务判定)。
匹配采集区120->160、中央模板60->48、位移搜索半径30->56(吃低帧大位移);
加纹理std(区分纯色/UI假0)、phaseCorrelate整体平移对照(不受半径限)。显示田字仍120。"""
import codecs, py_compile
P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
text = open(P, 'rb').read().decode('utf-8-sig')

old = '''    def _flow_match(self, prev, roi, axis, d):
        """相邻两帧田字ROI(都是SxS灰度、锚人物随动)。返回(dd,score,halfhit):
        dd=沿轴图像位移带号(正=内容下移/右移);score=prev中央子块在curr里的全局匹配峰值;
        halfhit=顺按键方向的半区迁移相关——人向下背景上移=prev下半与curr上半相关;向右=prev右半与curr左半相关。"""
        _S = roi.shape[0]; _h = _S // 2
        _tpl = prev[_h // 2:_h // 2 + _h, _h // 2:_h // 2 + _h]
        _res = cv2.matchTemplate(roi, _tpl, cv2.TM_CCOEFF_NORMED)
        _, _mv, _, _ml = cv2.minMaxLoc(_res)
        _dx = _ml[0] - _h // 2; _dy = _ml[1] - _h // 2
        if axis == 'y':
            _half = self._flow_corr(prev[_h:_S, :], roi[0:_h, :]) if d > 0 else self._flow_corr(prev[0:_h, :], roi[_h:_S, :])
            return _dy, float(_mv), _half
        _half = self._flow_corr(prev[:, _h:_S], roi[:, 0:_h]) if d > 0 else self._flow_corr(prev[:, 0:_h], roi[:, _h:_S])
        return _dx, float(_mv), _half

    def _flow_loop(self):
        """田字背景迁移检测线程(常开层):只在有移动意图时算按住的那条轴,田字框吊在运动反方向(身后)500px。
        诊断版只发布 self._flow_state/self._flow_boxes 并打日志,绝不参与任何动作判定。全程try自保护不崩。"""
        FLOW_BOX, FLOW_TAIL_GAP, FLOW_MIN_GAP, FLOW_MARGIN = 120, 500, 160, 24
        FLOW_WIN_MS, FLOW_MIN_ROUNDS, FLOW_MATCH_THR, FLOW_MIN_D = 300, 3, 0.5, 1.0
        _last_seq = -1
        _prev = {}    # axis -> (gray_roi, cx, cy)
        _hist = []    # (t_ms, axis, d, eff, score, half)
        _last_frame_ms = 0
        _last_log = 0
        while getattr(self, '_detect_running', False):
            try:
                _frame = self._latest_frame
                _seq = getattr(self, '_latest_frame_seq', 0)
                if _frame is None or _seq == _last_seq:
                    time.sleep(0.008); continue
                _last_seq = _seq
                _now_ms = int(time.time() * 1000)
                _frame_dt = _now_ms - _last_frame_ms if _last_frame_ms else 0
                _last_frame_ms = _now_ms
                _ch = getattr(self, '_raw_char_pos', None)
                with self._wd_lock:
                    _intents = {a: dict(v) for a, v in self._mv_intent.items()}
                # 轴向门控:无人物点或没按任何移动键(原地打怪)→整帧不算、清历史防跨动作串,零开销
                if _ch is None or not _intents:
                    _prev.clear(); _hist = []
                    with self._flow_lock:
                        self._flow_boxes = []; self._flow_state = {}
                    time.sleep(0.012); continue
                _fh, _fw = _frame.shape[:2]
                _px, _py = int(_ch[0]), int(_ch[1])
                # 选轴:有垂直意图(下跳/爬梯)优先垂直,否则水平;田字吊在运动反方向(身后)
                if 'y' in _intents:
                    _axis = 'y'; _d = int(_intents['y'].get('dir', 1) or 1)
                    _cx = _px; _cy = (_py - FLOW_TAIL_GAP) if _d > 0 else (_py + FLOW_TAIL_GAP)
                else:
                    _axis = 'x'; _d = int(_intents['x'].get('dir', 1) or 1)
                    _cx = (_px - FLOW_TAIL_GAP) if _d > 0 else (_px + FLOW_TAIL_GAP); _cy = _py
                _half = FLOW_BOX // 2
                _cx = max(FLOW_MARGIN + _half, min(_cx, _fw - FLOW_MARGIN - _half))
                _cy = max(FLOW_MARGIN + _half, min(_cy, _fh - FLOW_MARGIN - _half))
                _gap = abs(_cx - _px) if _axis == 'x' else abs(_cy - _py)
                _edge = _gap < FLOW_MIN_GAP
                _x1, _y1, _x2, _y2 = _cx - _half, _cy - _half, _cx + _half, _cy + _half
                _dd = _score = _halfhit = 0.0
                _n_rounds = _n_rev = 0; _sum_eff = 0.0
                if (not _edge) and _x1 >= 0 and _y1 >= 0 and _x2 <= _fw and _y2 <= _fh:
                    _roi = cv2.cvtColor(_frame[_y1:_y2, _x1:_x2], cv2.COLOR_BGR2GRAY).astype(np.float32)
                    if _axis in _prev:
                        # 换向/换轴清窗;只留同窗同方向300ms内样本
                        if _hist and (_hist[-1][1] != _axis or _hist[-1][2] != _d):
                            _hist = []
                        _hist = [e for e in _hist if _now_ms - e[0] <= FLOW_WIN_MS]
                        _dd, _score, _halfhit = self._flow_match(_prev[_axis][0], _roi, _axis, _d)
                        _eff = -(_d * _dd)  # 朝按键期望方向迁移为正
                        _hist.append((_now_ms, _axis, _d, _eff, _score, _halfhit))
                        _n_rounds = sum(1 for e in _hist if e[3] >= FLOW_MIN_D and e[4] >= FLOW_MATCH_THR)
                        _n_rev = sum(1 for e in _hist if e[3] <= -FLOW_MIN_D and e[4] >= FLOW_MATCH_THR)
                        _sum_eff = sum(e[3] for e in _hist)
                    _prev[_axis] = (_roi, _cx, _cy)
                else:
                    _edge = True  # ROI不完整也按贴边弃权
                _dn = ('下' if _d > 0 else '上') if _axis == 'y' else ('右' if _d > 0 else '左')
                _real = (_n_rounds >= FLOW_MIN_ROUNDS)
                _clr = 0x00FFFF if _edge else (0x00FF00 if _real else 0x00FFFFFF)  # 黄=贴边弃权/绿=3轮真动/白=有效不足
                _tag = '边' if _edge else ('真动' if _real else '测')
                _lab = "田%s%s %d/%d %.2f" % (_dn, _tag, _n_rounds, len(_hist), _score)
                with self._flow_lock:
                    self._flow_boxes = [(_x1, _y1, _x2, _y2, _clr, _lab)]
                    self._flow_state = dict(axis=_axis, dir=_d, gap=_gap, edge=_edge, dd=_dd,
                                            score=_score, half=_halfhit, rounds=_n_rounds,
                                            rev=_n_rev, sum_eff=_sum_eff, n=len(_hist),
                                            frame_dt=_frame_dt, real=_real, t=_now_ms)
                if _now_ms - _last_log >= 250:
                    _last_log = _now_ms
                    _debug_log("[田字诊断] %s%s gap%d%s 帧d%.1f s%.2f 半%.2f | 窗%dms 同向%d 反向%d 累计%.0f 样本%d 帧周期%dms" % (
                        _dn, _tag, _gap, '(弃权)' if _edge else '', _dd, _score, _halfhit,
                        FLOW_WIN_MS, _n_rounds, _n_rev, _sum_eff, len(_hist), _frame_dt))
            except Exception as _fe:
                try:
                    _debug_log("[田字诊断] 异常:%s" % (_fe,))
                except Exception:
                    pass
                time.sleep(0.03)
'''

new = '''    def _flow_match(self, prev, roi, axis, d):
        """相邻两帧匹配区(都是MxM灰度、锚人物随动,M=160)。返回dict:
        dd=matchTemplate沿轴位移带号(正=内容下移/右移);score峰值;half=顺按键方向半区迁移相关;
        pcd/pcr=phaseCorrelate沿轴位移/响应(不受搜索半径限,互证);std=纹理强度(低=纯色/UI会假0)。"""
        _M = roi.shape[0]; _tsz = 48; _t0 = (_M - _tsz) // 2; _hm = _M // 2
        _std = float(roi.std())
        _tpl = prev[_t0:_t0 + _tsz, _t0:_t0 + _tsz]
        _res = cv2.matchTemplate(roi, _tpl, cv2.TM_CCOEFF_NORMED)
        _, _mv, _, _ml = cv2.minMaxLoc(_res)
        _dx = _ml[0] - _t0; _dy = _ml[1] - _t0
        if axis == 'y':
            _half = self._flow_corr(prev[_hm:_M, :], roi[0:_hm, :]) if d > 0 else self._flow_corr(prev[0:_hm, :], roi[_hm:_M, :])
            _dd = _dy
        else:
            _half = self._flow_corr(prev[:, _hm:_M], roi[:, 0:_hm]) if d > 0 else self._flow_corr(prev[:, 0:_hm], roi[:, _hm:_M])
            _dd = _dx
        _pcd = _pcr = 0.0
        try:
            _w = np.hanning(_M).astype(np.float32); _win = _w[:, None] * _w[None, :]
            (_px, _py), _pr = cv2.phaseCorrelate(np.float32(prev) * _win, np.float32(roi) * _win)
            _pcd = _py if axis == 'y' else _px; _pcr = float(_pr)
        except Exception:
            pass
        return dict(dd=float(_dd), score=float(_mv), half=float(_half), pcd=float(_pcd), pcr=_pcr, std=_std)

    def _flow_loop(self):
        """田字背景迁移检测线程(常开层):只在有移动意图时算按住的那条轴,吊在运动反方向(身后)500px。
        采集匹配区160(搜索半径56,吃低帧大位移),显示田字120十字四格。诊断版只发布+打日志,不参与任何动作判定。"""
        FLOW_BOX, FLOW_MATCH, FLOW_TAIL_GAP, FLOW_MIN_GAP, FLOW_MARGIN = 120, 160, 500, 160, 24
        FLOW_WIN_MS, FLOW_MIN_ROUNDS, FLOW_MATCH_THR, FLOW_MIN_D = 300, 3, 0.5, 1.0
        _hd = FLOW_BOX // 2; _hm = FLOW_MATCH // 2
        _last_seq = -1
        _prev = {}
        _hist = []
        _last_frame_ms = 0
        _last_log = 0
        while getattr(self, '_detect_running', False):
            try:
                _frame = self._latest_frame
                _seq = getattr(self, '_latest_frame_seq', 0)
                if _frame is None or _seq == _last_seq:
                    time.sleep(0.008); continue
                _last_seq = _seq
                _now_ms = int(time.time() * 1000)
                _frame_dt = _now_ms - _last_frame_ms if _last_frame_ms else 0
                _last_frame_ms = _now_ms
                _ch = getattr(self, '_raw_char_pos', None)
                with self._wd_lock:
                    _intents = {a: dict(v) for a, v in self._mv_intent.items()}
                if _ch is None or not _intents:
                    _prev.clear(); _hist = []
                    with self._flow_lock:
                        self._flow_boxes = []; self._flow_state = {}
                    time.sleep(0.012); continue
                _fh, _fw = _frame.shape[:2]
                _px, _py = int(_ch[0]), int(_ch[1])
                if 'y' in _intents:
                    _axis = 'y'; _d = int(_intents['y'].get('dir', 1) or 1)
                    _cx = _px; _cy = (_py - FLOW_TAIL_GAP) if _d > 0 else (_py + FLOW_TAIL_GAP)
                else:
                    _axis = 'x'; _d = int(_intents['x'].get('dir', 1) or 1)
                    _cx = (_px - FLOW_TAIL_GAP) if _d > 0 else (_px + FLOW_TAIL_GAP); _cy = _py
                _cx = max(FLOW_MARGIN + _hm, min(_cx, _fw - FLOW_MARGIN - _hm))
                _cy = max(FLOW_MARGIN + _hm, min(_cy, _fh - FLOW_MARGIN - _hm))
                _gap = abs(_cx - _px) if _axis == 'x' else abs(_cy - _py)
                _edge = _gap < FLOW_MIN_GAP
                _mx1, _my1, _mx2, _my2 = _cx - _hm, _cy - _hm, _cx + _hm, _cy + _hm
                _x1, _y1, _x2, _y2 = _cx - _hd, _cy - _hd, _cx + _hd, _cy + _hd
                _dd = _score = _half = _pcd = _pcr = _std = 0.0
                _n_rounds = _n_rev = 0; _sum_eff = 0.0
                if (not _edge) and _mx1 >= 0 and _my1 >= 0 and _mx2 <= _fw and _my2 <= _fh:
                    _roi = cv2.cvtColor(_frame[_my1:_my2, _mx1:_mx2], cv2.COLOR_BGR2GRAY).astype(np.float32)
                    _std = float(_roi.std())
                    if _axis in _prev:
                        if _hist and (_hist[-1][1] != _axis or _hist[-1][2] != _d):
                            _hist = []
                        _hist = [e for e in _hist if _now_ms - e[0] <= FLOW_WIN_MS]
                        _r = self._flow_match(_prev[_axis], _roi, _axis, _d)
                        _dd, _score, _half = _r['dd'], _r['score'], _r['half']
                        _pcd, _pcr, _std = _r['pcd'], _r['pcr'], _r['std']
                        _eff = -(_d * _dd)
                        _hist.append((_now_ms, _axis, _d, _eff, _score, _half))
                        _n_rounds = sum(1 for e in _hist if e[3] >= FLOW_MIN_D and e[4] >= FLOW_MATCH_THR)
                        _n_rev = sum(1 for e in _hist if e[3] <= -FLOW_MIN_D and e[4] >= FLOW_MATCH_THR)
                        _sum_eff = sum(e[3] for e in _hist)
                    _prev[_axis] = _roi
                else:
                    _edge = True
                _dn = ('下' if _d > 0 else '上') if _axis == 'y' else ('右' if _d > 0 else '左')
                _real = (_n_rounds >= FLOW_MIN_ROUNDS)
                _clr = 0x00FFFF if _edge else (0x00FF00 if _real else 0x00FFFFFF)
                _tag = '边' if _edge else ('真动' if _real else '测')
                _lab = "田%s%s %d/%d %.2f" % (_dn, _tag, _n_rounds, len(_hist), _score)
                with self._flow_lock:
                    self._flow_boxes = [(_x1, _y1, _x2, _y2, _clr, _lab)]
                    self._flow_state = dict(axis=_axis, dir=_d, gap=_gap, edge=_edge, dd=_dd, pcd=_pcd,
                                            score=_score, half=_half, pcr=_pcr, std=_std, rounds=_n_rounds,
                                            rev=_n_rev, sum_eff=_sum_eff, n=len(_hist),
                                            frame_dt=_frame_dt, real=_real, t=_now_ms)
                if _now_ms - _last_log >= 250:
                    _last_log = _now_ms
                    _debug_log("[田字诊断] %s%s gap%d%s mt[d%.1f s%.2f] pc[d%.1f r%.2f] std%.0f 半%.2f | 同向%d 反向%d 累计%.0f 样本%d 周期%dms" % (
                        _dn, _tag, _gap, '(弃权)' if _edge else '', _dd, _score, _pcd, _pcr, _std, _half,
                        _n_rounds, _n_rev, _sum_eff, len(_hist), _frame_dt))
            except Exception as _fe:
                try:
                    _debug_log("[田字诊断] 异常:%s" % (_fe,))
                except Exception:
                    pass
                time.sleep(0.03)
'''

assert text.count(old) == 1, '待替换段 count=%d' % text.count(old)
text = text.replace(old, new)
assert '\r' not in text
open(P, 'wb').write(codecs.BOM_UTF8 + text.encode('utf-8'))
py_compile.compile(P, doraise=True)
print('OK 田字诊断v2 替换完成 py_compile pass')
