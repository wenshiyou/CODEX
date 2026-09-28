# -*- coding: utf-8 -*-
"""十字框(田字背景迁移检测)从游戏窗口迁移到小地图:框40x40、与光点同水平线、朝内侧离光点40。"""
import io, sys

TARGET = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(TARGET, "r", encoding="utf-8", newline="") as f:
    _raw = f.read()
_crlf = "\r\n" in _raw
content = _raw.replace("\r\n", "\n")
edits = []

# 1. _flow_match 模板尺寸(框40时模板20)
edits.append(("1 flow_match模板",
"        _M = roi.shape[0]; _tsz = 48; _t0 = (_M - _tsz) // 2; _hm = _M // 2",
"        _M = roi.shape[0]; _tsz = max(12, _M // 2); _t0 = (_M - _tsz) // 2; _hm = _M // 2  # 框40时模板20"))

# 2. _flow_idle_match 模板尺寸
edits.append(("2 idle模板",
"        _tsz = 48; _t0 = (_M - _tsz) // 2",
"        _tsz = max(12, _M // 2); _t0 = (_M - _tsz) // 2   # 框40时模板20"))

# 3. 块A docstring+常量
edits.append(("3 常量",
'''        """田字背景迁移检测线程(常开层):框放人物斜上对角(水平朝屏幕内侧300、垂直上抬300,不平齐);人在左半屏挂右上、人在右半屏挂左上。
        移动档按有效键轴(x/y)算背景位移、原地档(无有效移动键)二维判静止;静止结论 still 参与主循环原地钉基点。采集匹配区160、显示田字120。"""
        FLOW_BOX, FLOW_MATCH, FLOW_TAIL_GAP, FLOW_MIN_GAP, FLOW_MARGIN = 120, 160, 300, 160, 24
        FLOW_CORNER_UP = 300  # 田字框对角定位垂直上抬:框放人物斜上对角(水平朝屏幕内侧300、垂直上抬300),不平齐(平齐全是怪/特效);人在左半屏挂右上、人在右半屏挂左上,上下不换侧(用户2026-09-24)
        FLOW_WIN_MS, FLOW_MIN_ROUNDS, FLOW_MATCH_THR, FLOW_MIN_D = 300, 3, 0.5, 1.0
        _hd = FLOW_BOX // 2; _hm = FLOW_MATCH // 2''',
'''        """田字背景迁移检测线程(常开层)·已迁移到小地图(用户2026-09-28):检测框40×40,与光点同水平线、
        朝小地图内侧离光点40px(光点偏左挂右/偏右挂左),检测小地图背景帧间变化;移动档按有效键轴算背景位移、
        原地档二维判静止。框画在小地图map_display上(块坐标)。"""
        FLOW_BOX, FLOW_TAIL_GAP, FLOW_MARGIN = 40, 40, 4   # 检测框=显示框40;框中心离光点40;块内边距4
        FLOW_WIN_MS, FLOW_MIN_ROUNDS, FLOW_MATCH_THR, FLOW_MIN_D = 300, 3, 0.5, 1.0
        _hd = FLOW_BOX // 2     # 匹配区半宽20(匹配框=显示框)'''))

# 4. 块B 定位源+框定位
edits.append(("4 定位与框",
'''                # 【田字框定位源改光点·用户2026-09-27】不用游戏窗口基点(_raw_char_pos,不准/丢失时田字框放错),
                # 改用小地图光点换算的屏幕坐标(lock_screen_from_dot,光点稳定永不丢失)。光点不可用时田字框不检测。
                _ch = None
                try:
                    _dot_pos = self.lock_screen_from_dot()
                    if _dot_pos is not None:
                        _ch = (_dot_pos[0], _dot_pos[1])
                except Exception:
                    _ch = None
                with self._wd_lock:
                    _intents = {a: dict(v) for a, v in self._mv_intent.items()}
                if _ch is None:
                    _prev.clear(); _hist = []; _hist_idle = []
                    with self._flow_lock:
                        self._flow_boxes = []; self._flow_state = {}
                    time.sleep(0.012); continue
                _fh, _fw = _frame.shape[:2]
                _px, _py = int(_ch[0]), int(_ch[1])
                # 有效移动轴:方向键须持续按住>=MOVE_KEY_MIN_MS;更短(出手掰脸转身60ms)是轻点、不算移动(用户2026-09-24)
                _eff = {a: v for a, v in _intents.items()
                        if _now_ms - int(v.get('start_t', 0) or 0) >= MOVE_KEY_MIN_MS}
                _moving = bool(_eff)
                if _last_moving != _moving:
                    _hist = []; _hist_idle = []   # 移动<->原地模式切换,两套历史各自清零不串判
                    _last_moving = _moving
                # 田字框选侧只看人物在屏幕左/右(用户2026-09-24):人在左半屏->框挂右上方、人在右半屏->框挂左上方(始终朝屏幕内侧、不吊出屏),与移动朝向无关;垂直恒定上抬,上下不换侧
                _xdir = -1 if _px < (_fw / 2.0) else 1   # 人在左(_xdir-1)->cx=px+GAP框在右;人在右(+1)->cx=px-GAP框在左
                _cx = _px - _xdir * FLOW_TAIL_GAP
                _cy = _py - FLOW_CORNER_UP            # 恒定上抬300=右上方/左上方对角,上下不换侧
                _cx = max(FLOW_MARGIN + _hm, min(_cx, _fw - FLOW_MARGIN - _hm))
                _cy = max(FLOW_MARGIN + _hm, min(_cy, _fh - FLOW_MARGIN - _hm))
                _gap = int(abs(_cx - _px))
                _edge = (abs(_cx - _px) < FLOW_MIN_GAP) or (abs(_py - _cy) < FLOW_MIN_GAP)  # 身后或上方放不下被夹回身边=贴边弃权
                _mx1, _my1, _mx2, _my2 = _cx - _hm, _cy - _hm, _cx + _hm, _cy + _hm
                _x1, _y1, _x2, _y2 = _cx - _hd, _cy - _hd, _cx + _hd, _cy + _hd''',
'''                # 检测画面=小地图块(从全帧裁map_area_rect);锚=小地图光点(块坐标),不再用游戏窗口/lock_screen_from_dot。
                _mrect = getattr(self, 'map_area_rect', None)
                _dot = getattr(self, '_player_map_pos', None)
                with self._wd_lock:
                    _intents = {a: dict(v) for a, v in self._mv_intent.items()}
                if not _mrect or _dot is None:
                    _prev.clear(); _hist = []; _hist_idle = []
                    with self._flow_lock:
                        self._flow_boxes = []; self._flow_state = {}
                    time.sleep(0.012); continue
                _fh, _fw = _frame.shape[:2]
                _ax0, _ay0 = int(_mrect['left']), int(_mrect['top'])
                _ax1 = min(_ax0 + int(_mrect['width']), _fw)
                _ay1 = min(_ay0 + int(_mrect['height']), _fh)
                _mapblk = _frame[_ay0:_ay1, _ax0:_ax1]
                _bh, _bw = _mapblk.shape[:2]
                _px, _py = int(_dot[0]), int(_dot[1])
                # 有效移动轴:方向键须持续按住>=MOVE_KEY_MIN_MS;更短(出手掰脸转身60ms)是轻点、不算移动(用户2026-09-24)
                _eff = {a: v for a, v in _intents.items()
                        if _now_ms - int(v.get('start_t', 0) or 0) >= MOVE_KEY_MIN_MS}
                _moving = bool(_eff)
                if _last_moving != _moving:
                    _hist = []; _hist_idle = []   # 移动<->原地模式切换,两套历史各自清零不串判
                    _last_moving = _moving
                # 框与光点同水平线、朝小地图内侧离光点40:光点偏块中心左(_xdir-1)->框挂右(cx=px+40);偏右->挂左。
                _xdir = -1 if _px < (_bw / 2.0) else 1
                _cx = _px - _xdir * FLOW_TAIL_GAP
                _cy = _py                            # 同水平线,不上抬(用户2026-09-28)
                _cx = max(FLOW_MARGIN + _hd, min(_cx, _bw - FLOW_MARGIN - _hd))
                _cy = max(FLOW_MARGIN + _hd, min(_cy, _bh - FLOW_MARGIN - _hd))
                _gap = int(abs(_cx - _px))
                # 贴边弃权:框被夹回、中心离光点不足32(放不下40框);垂直同线不判(原斜上方逻辑已去)
                _edge = abs(_cx - _px) < (FLOW_TAIL_GAP - 8)
                _mx1, _my1, _mx2, _my2 = _cx - _hd, _cy - _hd, _cx + _hd, _cy + _hd
                _x1, _y1, _x2, _y2 = _mx1, _my1, _mx2, _my2   # 匹配框=显示框40'''))

# 5. 块C 移动档ROI
edits.append(("5 移动ROI",
'''                    if (not _edge) and _mx1 >= 0 and _my1 >= 0 and _mx2 <= _fw and _my2 <= _fh:
                        _roi = cv2.cvtColor(_frame[_my1:_my2, _mx1:_mx2], cv2.COLOR_BGR2GRAY).astype(np.float32)''',
'''                    if (not _edge) and _mx1 >= 0 and _mx2 <= _bw and _my2 <= _bh:
                        _roi = cv2.cvtColor(_mapblk[_my1:_my2, _mx1:_mx2], cv2.COLOR_BGR2GRAY).astype(np.float32)'''))

# 6. 块D 原地档ROI
edits.append(("6 原地ROI",
'''                    if not _edge:
                        _roi = cv2.cvtColor(_frame[_my1:_my2, _mx1:_mx2], cv2.COLOR_BGR2GRAY).astype(np.float32)''',
'''                    if not _edge:
                        _roi = cv2.cvtColor(_mapblk[_my1:_my2, _mx1:_mx2], cv2.COLOR_BGR2GRAY).astype(np.float32)'''))

# 7. 删除游戏窗口蒙板绘制
edits.append(("7 拆游戏蒙板",
'''                            # 田字背景迁移检测框(诊断·detect_flow发布):身后吊框;绿=3轮同向真动/黄=贴边弃权/白=有效不足3轮
                            try:
                                for (_fx1, _fy1, _fx2, _fy2, _fclr, _flab) in list(getattr(self, '_flow_boxes', [])):
                                    _fp = gdi32.CreatePen(0, 2, _fclr)
                                    if _fp: gdi_objs.append(_fp)
                                    _ofp = gdi32.SelectObject(hdc, _fp)
                                    gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷只描边
                                    gdi32.Rectangle(hdc, int(_fx1), int(_fy1), int(_fx2), int(_fy2))
                                    _mxx = (int(_fx1) + int(_fx2)) // 2; _myy = (int(_fy1) + int(_fy2)) // 2
                                    gdi32.MoveToEx(hdc, _mxx, int(_fy1), None); gdi32.LineTo(hdc, _mxx, int(_fy2))
                                    gdi32.MoveToEx(hdc, int(_fx1), _myy, None); gdi32.LineTo(hdc, int(_fx2), _myy)
                                    gdi32.SelectObject(hdc, _ofp)
                                    _ff = gdi32.CreateFontW(14, 0, 0, 0, 400, 0, 0, 0, 134, 3, 2, 1, 49, "微软雅黑")
                                    if _ff: gdi_objs.append(_ff)
                                    _off = gdi32.SelectObject(hdc, _ff)
                                    gdi32.SetTextColor(hdc, _fclr); gdi32.SetBkMode(hdc, 1)
                                    gdi32.TextOutW(hdc, int(_fx1) + 2, int(_fy1) - 16, _flab, len(_flab))
                                    gdi32.SelectObject(hdc, _off)
                            except Exception:
                                pass''',
'''                            # 田字背景迁移检测框已迁移到小地图map_display(用户2026-09-28),游戏窗口蒙板不再绘制'''))

# 8. 小地图 map_display 加绘制
edits.append(("8 小地图绘制",
'''                cv2.circle(map_display, (_dcx, _dcy), 2, (0, 0, 255), -1)                 # 中心红实心点

        # 光点锁定可视化框已移除（与校准/正常模式绿框重复，保留后者即可）''',
'''                cv2.circle(map_display, (_dcx, _dcy), 2, (0, 0, 255), -1)                 # 中心红实心点

        # 田字背景迁移检测框(已从游戏窗口迁来·用户2026-09-28):_flow_boxes为小地图块坐标,乘scale_x/y到map_display;
        # 矩形+十字,颜色:绿=3轮同向真动/红=背景在动/青=确认静止/黄=贴边弃权。COLORREF(0xBBGGRR)->cv2(B,G,R)。
        for (_fx1, _fy1, _fx2, _fy2, _fclr, _flab) in list(getattr(self, '_flow_boxes', [])):
            _cB, _cG, _cR = (_fclr >> 16) & 255, (_fclr >> 8) & 255, _fclr & 255
            _fcol = (int(_cB), int(_cG), int(_cR))
            _bx1 = int(_fx1 * scale_x); _by1 = int(_fy1 * scale_y)
            _bx2 = int(_fx2 * scale_x); _by2 = int(_fy2 * scale_y)
            cv2.rectangle(map_display, (_bx1, _by1), (_bx2, _by2), _fcol, 1)
            _bcx = (_bx1 + _bx2) // 2; _bcy = (_by1 + _by2) // 2
            cv2.line(map_display, (_bcx, _by1), (_bcx, _by2), _fcol, 1)
            cv2.line(map_display, (_bx1, _bcy), (_bx2, _bcy), _fcol, 1)
            self._putcn(map_display, _flab, _bx1, max(0, _by1 - 16), _fcol)

        # 光点锁定可视化框已移除（与校准/正常模式绿框重复，保留后者即可）'''))

fails = []
for name, old, new in edits:
    c = content.count(old)
    if c == 1:
        content = content.replace(old, new); print("OK  ", name)
    else:
        fails.append((name, c)); print("FAIL", name, "count=", c)
if fails:
    print("\n有失败项,未写回。"); sys.exit(1)
if _crlf:
    content = content.replace("\n", "\r\n")
with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("\n补丁已写回")
