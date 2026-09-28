# -*- coding: utf-8 -*-
"""十字框:尺寸30x30、标签五组(向左/右/上/下/静止..)、标签加底条+simhei治乱码。"""
import io, sys
TARGET = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(TARGET, "r", encoding="utf-8", newline="") as f:
    _raw = f.read()
_crlf = "\r\n" in _raw
content = _raw.replace("\r\n", "\n")
edits = []

# 1. 框尺寸 40 -> 30
edits.append(("1 框30",
"        FLOW_BOX, FLOW_TAIL_GAP, FLOW_MARGIN = 40, 40, 4   # 检测框=显示框40;框中心离光点40;块内边距4",
"        FLOW_BOX, FLOW_TAIL_GAP, FLOW_MARGIN = 30, 40, 4   # 检测框=显示框30;框中心离光点40;块内边距4"))

# 2. _putcn 签名加 font
edits.append(("2 putcn签名",
"    def _putcn(self, frame, text, x, y, color=(255, 255, 255)):",
"    def _putcn(self, frame, text, x, y, color=(255, 255, 255), font=None):"))

# 3. _putcn getbbox 用 _f
edits.append(("3 putcn bbox",
"            bb = self._log_font.getbbox(text, anchor=\"ls\")  # 相对基线锚点(x,y)的包围盒,上方为负",
"            _f = font or self._log_font\n            bb = _f.getbbox(text, anchor=\"ls\")  # 相对基线锚点(x,y)的包围盒,上方为负"))

# 4. _putcn draw 用 _f
edits.append(("4 putcn draw",
"            ImageDraw.Draw(_pil).text((x - X0, y - Y0), text, font=self._log_font,",
"            ImageDraw.Draw(_pil).text((x - X0, y - Y0), text, font=_f,"))

# 5. 移动档标签五组
edits.append(("5 移动标签",
'''                    _dn = ('下' if _d > 0 else '上') if _axis == 'y' else ('右' if _d > 0 else '左')
                    _real = (_n_rounds >= FLOW_MIN_ROUNDS)
                    _clr = 0x00FFFF if _edge else (0x00FF00 if _real else 0x00FFFFFF)
                    _tag = '边' if _edge else ('真动' if _real else '测')
                    _lab = "田%s%s %d/%d %.2f" % (_dn, _tag, _n_rounds, len(_hist), _score)''',
'''                    _real = (_n_rounds >= FLOW_MIN_ROUNDS)
                    _clr = 0x00FFFF if _edge else (0x00FF00 if _real else 0x00FFFFFF)
                    _lab = ('向下..' if _d > 0 else '向上..') if _axis == 'y' else ('向右..' if _d > 0 else '向左..')'''))

# 6. 原地档标签五组(颜色不变:黄静止/红动/青弃权)
edits.append(("6 原地标签",
'''                    _itag = '边' if _edge else ('静' if _still is True else ('动' if _still is False else '?'))
                    _clr = 0x00FFFF if (_edge or _still is None) else (0xFFFF00 if _still else 0x0000FF)  # 青=确认静止 红=背景在动 黄=弃权/未定
                    _lab = "田原%s %d" % (_itag, len(_hist_idle))''',
'''                    _clr = 0x00FFFF if (_edge or _still is None) else (0xFFFF00 if _still else 0x0000FF)  # 黄=确认静止 红=背景在动 青=弃权/未定
                    if _still is False and (abs(_idx) >= 1.0 or abs(_idy) >= 1.0):
                        _lab = ('向上..' if _idy < 0 else '向下..') if abs(_idy) >= abs(_idx) else ('向左..' if _idx < 0 else '向右..')
                    else:
                        _lab = '静止..' '''))

# 7. 绘制块:底条+simhei+修正注释
edits.append(("7 绘制块",
'''        # 田字背景迁移检测框(已从游戏窗口迁来·用户2026-09-28):_flow_boxes为小地图块坐标,乘scale_x/y到map_display;
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
            self._putcn(map_display, _flab, _bx1, max(0, _by1 - 16), _fcol)''',
'''        # 田字背景迁移检测框(已从游戏窗口迁来·用户2026-09-28):_flow_boxes为小地图块坐标,乘scale_x/y到map_display;
        # 矩形+十字,颜色:绿=真动/红=背景在动/黄=确认静止/青=弃权未定。标签加深色底条+simhei,杜绝中文糊在地图纹理上乱码。
        _flow_lab_font = self._load_cn_font(13)
        for (_fx1, _fy1, _fx2, _fy2, _fclr, _flab) in list(getattr(self, '_flow_boxes', [])):
            _cB, _cG, _cR = (_fclr >> 16) & 255, (_fclr >> 8) & 255, _fclr & 255
            _fcol = (int(_cB), int(_cG), int(_cR))
            _bx1 = int(_fx1 * scale_x); _by1 = int(_fy1 * scale_y)
            _bx2 = int(_fx2 * scale_x); _by2 = int(_fy2 * scale_y)
            cv2.rectangle(map_display, (_bx1, _by1), (_bx2, _by2), _fcol, 1)
            _bcx = (_bx1 + _bx2) // 2; _bcy = (_by1 + _by2) // 2
            cv2.line(map_display, (_bcx, _by1), (_bcx, _by2), _fcol, 1)
            cv2.line(map_display, (_bx1, _bcy), (_bx2, _bcy), _fcol, 1)
            _ty = _by1 - 17
            if _ty < 0: _ty = _by2 + 3      # 框上方放不下就放框下方
            _tb = _flow_lab_font.getbbox(_flab, anchor="ls")
            cv2.rectangle(map_display,
                          (_bx1 + 2 + _tb[0] - 1, _ty + _tb[1] - 1),
                          (_bx1 + 2 + _tb[2] + 1, _ty + _tb[3] + 1), (0, 0, 0), -1)
            self._putcn(map_display, _flab, _bx1 + 2, _ty, (255, 255, 255), font=_flow_lab_font)'''))

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
