# -*- coding: utf-8 -*-
"""田字背景迁移检测·只读诊断版(用户2026-09-20定稿)。
独立常开线程 detect_flow:复用截图帧(不自己截图)、锚人物_raw_char_pos、身后吊田字框500px、
轴向门控(只测当前按住方向的轴,无移动键整帧跳过=原地打怪零开销)、300ms窗>=3轮同向才算真动。
本版【只画框+发布self._flow_state+打日志】,不接任何动作判定、不删旧码、不改下跳逻辑。
maple 带 BOM/LF。四处插入:__init__字段 / 两个方法 / 常开层启动 / 蒙板画框。"""
import codecs, py_compile

P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
raw = open(P, 'rb').read()
assert raw.startswith(codecs.BOM_UTF8), 'maple 必须带 BOM'
text = raw.decode('utf-8-sig')

# ---------- 1) __init__ 字段(锚 _mv_intent 整行后) ----------
old_init = (
"        self._mv_intent = {}               # 当前移动意图 {'x':intent,'y':intent},水平/垂直独立记账可同时存在;intent=dict{dir,src,seg_t,seg_x,seg_y,reported...}\n"
)
assert text.count(old_init) == 1, 'init锚点=%d' % text.count(old_init)
new_init = old_init + (
"        self._flow_thread = None            # 田字背景迁移检测线程(常开层 detect_flow),独立线程只发布结果、不压主线\n"
"        self._flow_lock = threading.RLock() # 田字检测发布锁\n"
"        self._flow_boxes = []               # 蒙板田字画框 [(x1,y1,x2,y2,colorref,label)]\n"
"        self._flow_state = {}               # 最新诊断结果(轴/方向/位移/同向轮数/置信/贴边),别的线程只读\n"
)
text = text.replace(old_init, new_init)

# ---------- 2) 方法(插在 _person_loop 前) ----------
old_person = "    def _person_loop(self):\n"
assert text.count(old_person) == 1, 'person锚点=%d' % text.count(old_person)
methods = '''    def _flow_corr(self, a, b):
        """两块同尺寸灰度的归一化相关[-1,1](田字半区迁移命中分,不依赖绝对亮度)。"""
        aa = a.astype(np.float32); bb = b.astype(np.float32)
        aa = aa - aa.mean(); bb = bb - bb.mean()
        _den = float(np.sqrt((aa * aa).sum() * (bb * bb).sum())) + 1e-6
        return float((aa * bb).sum() / _den)

    def _flow_match(self, prev, roi, axis, d):
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
text = text.replace(old_person, methods + old_person)

# ---------- 3) 常开层启动(锚 print 常开层) ----------
old_start = '        print("[识别线程] 常开层启动: 截图+人物(绑定窗口常开)")\n'
assert text.count(old_start) == 1, 'start锚点=%d' % text.count(old_start)
new_start = (
"        if not (self._flow_thread and self._flow_thread.is_alive()):\n"
"            self._flow_thread = threading.Thread(target=self._flow_loop, daemon=True, name=\"detect_flow\")\n"
"            self._flow_thread.start()\n"
"        print(\"[识别线程] 常开层启动: 截图+人物+田字背景流(绑定窗口常开)\")\n"
)
text = text.replace(old_start, new_start)

# ---------- 4) 蒙板画框(锚 怪物特征点注释行,前插) ----------
old_paint = "                            # 怪物特征单独匹配点（紫色小点+数字编号，方便发现哪个特征误判）\n"
assert text.count(old_paint) == 1, 'paint锚点=%d' % text.count(old_paint)
paint_block = (
"                            # 田字背景迁移检测框(诊断·detect_flow发布):身后吊框;绿=3轮同向真动/黄=贴边弃权/白=有效不足3轮\n"
"                            try:\n"
"                                for (_fx1, _fy1, _fx2, _fy2, _fclr, _flab) in list(getattr(self, '_flow_boxes', [])):\n"
"                                    _fp = gdi32.CreatePen(0, 2, _fclr)\n"
"                                    if _fp: gdi_objs.append(_fp)\n"
"                                    _ofp = gdi32.SelectObject(hdc, _fp)\n"
"                                    gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷只描边\n"
"                                    gdi32.Rectangle(hdc, int(_fx1), int(_fy1), int(_fx2), int(_fy2))\n"
"                                    _mxx = (int(_fx1) + int(_fx2)) // 2; _myy = (int(_fy1) + int(_fy2)) // 2\n"
"                                    gdi32.MoveToEx(hdc, _mxx, int(_fy1), None); gdi32.LineTo(hdc, _mxx, int(_fy2))\n"
"                                    gdi32.MoveToEx(hdc, int(_fx1), _myy, None); gdi32.LineTo(hdc, int(_fx2), _myy)\n"
"                                    gdi32.SelectObject(hdc, _ofp)\n"
"                                    _ff = gdi32.CreateFontW(14, 0, 0, 0, 400, 0, 0, 0, 134, 3, 2, 1, 49, \"微软雅黑\")\n"
"                                    if _ff: gdi_objs.append(_ff)\n"
"                                    _off = gdi32.SelectObject(hdc, _ff)\n"
"                                    gdi32.SetTextColor(hdc, _fclr); gdi32.SetBkMode(hdc, 1)\n"
"                                    gdi32.TextOutW(hdc, int(_fx1) + 2, int(_fy1) - 16, _flab, len(_flab))\n"
"                                    gdi32.SelectObject(hdc, _off)\n"
"                            except Exception:\n"
"                                pass\n"
)
text = text.replace(old_paint, paint_block + old_paint)

assert '\r' not in text, '出现 CR'
open(P, 'wb').write(codecs.BOM_UTF8 + text.encode('utf-8'))
py_compile.compile(P, doraise=True)
print('OK 田字诊断版4处插入完成, py_compile pass, BOM/LF kept')
