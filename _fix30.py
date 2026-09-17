# -*- coding: utf-8 -*-
# A: 自绘框选窗全程TOPMOST压在游戏/怪物蒙板之上(根治框选窗跑到游戏后面、拖框无效保存不了)
# B: 窗口强制1280x800目标尺寸自愈(根治target反复卡None不拉回;下拉手选切换补设)
import io
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(P, "r", encoding="utf-8") as f:
    t = f.read()

pairs = []

# ---- A1: 框选窗创建后取win32句柄 ----
pairs.append((
"        _cv.imshow(win, frame)\n"
"        _cv.waitKey(1)  # 先让窗口真正创建出来,下面才能FindWindow做精确对齐\n",
"        _cv.imshow(win, frame)\n"
"        _cv.waitKey(1)  # 先让窗口真正创建出来,下面才能FindWindow做精确对齐\n"
"        # [2026-09-17 根因] 框选窗必须全程压在游戏/怪物蒙板(独立线程TOPMOST每帧重顶)之上:否则时前时后,\n"
"        # 被盖到游戏后面时鼠标落在蒙板/游戏上→拖不出框、坐标无效、回车也保存不了。先取句柄供首次置顶与循环保顶。\n"
"        _box_u = None\n"
"        _box_hwnd = None\n"
"        try:\n"
"            import ctypes as _ctb\n"
"            from ctypes import wintypes as _wtb\n"
"            _box_u = _ctb.windll.user32\n"
"            _box_u.FindWindowW.restype = _wtb.HWND\n"
"            _box_u.FindWindowW.argtypes = [_wtb.LPCWSTR, _wtb.LPCWSTR]\n"
"            _box_u.SetWindowPos.argtypes = [_wtb.HWND, _wtb.HWND, _ctb.c_int, _ctb.c_int,\n"
"                                           _ctb.c_int, _ctb.c_int, _wtb.UINT]\n"
"            _box_hwnd = _box_u.FindWindowW(None, win)\n"
"        except Exception:\n"
"            _box_u = None\n"
"            _box_hwnd = None\n"
))

# ---- A2: 首次置顶+前台; 定义保顶helper; 循环加计时变量 ----
pairs.append((
"        _cv.setMouseCallback(win, on_mouse)\n"
"        while True:\n",
"        def _box_bring_top(_activate=False):\n"
"            if _box_u and _box_hwnd:\n"
"                try:\n"
"                    _fl = 0x0001 | 0x0002 | (0x0040 if _activate else 0x0010)  # NOSIZE|NOMOVE;首次SHOWWINDOW并激活,平时NOACTIVATE只保顶\n"
"                    _box_u.SetWindowPos(_box_hwnd, -1, 0, 0, 0, 0, _fl)  # HWND_TOPMOST=-1\n"
"                    if _activate:\n"
"                        _box_u.SetForegroundWindow(_box_hwnd)\n"
"                except Exception:\n"
"                    pass\n"
"        _box_bring_top(True)   # 首次:置顶并拿前台焦点(回车/ESC/方向键需要)\n"
"        _cv.setMouseCallback(win, on_mouse)\n"
"        _box_top_t = 0.0\n"
"        while True:\n"
))

# ---- A3: 模态循环内每50ms重申置顶 ----
pairs.append((
"            _cv.imshow(win, disp)\n"
"            k = _cv.waitKey(1)\n",
"            _cv.imshow(win, disp)\n"
"            _box_now = time.time()\n"
"            if _box_now - _box_top_t >= 0.05:\n"
"                _box_top_t = _box_now\n"
"                _box_bring_top(False)   # 每50ms重申TOPMOST,压过怪物蒙板独立线程的置顶刷新;NOACTIVATE不抢键\n"
"            k = _cv.waitKey(1)\n"
))

# ---- B1: _save守卫放宽为只要有句柄即写死目标尺寸 ----
pairs.append((
"        if self.hwnd and self.window_rect:\n"
"            self._target_window_size = (GAME_W, GAME_H)",
"        if self.hwnd:   # 2026-09-17根因:有句柄即写死目标尺寸,不依赖window_rect此刻就绪(rect由_ensure自取),根治启动竞态target卡None\n"
"            self._target_window_size = (GAME_W, GAME_H)"
))

# ---- B2: _ensure开头自愈: 有句柄但target为None时补写死+去边框 ----
pairs.append((
'        if self.hwnd is None or self._target_window_size is None:\n'
'            _debug_log("[窗口固定诊断] 不拉回: hwnd=%s _target_window_size=%s" % (self.hwnd, self._target_window_size))\n'
'            return\n',
"        if self.hwnd is None:\n"
"            return\n"
"        if self._target_window_size is None:\n"
"            # 2026-09-17根因自愈:有有效句柄却没目标尺寸(启动时rect未就绪_save跳过/下拉手切换漏设),补齐写死1280x800+去可调边框,不再静默return不拉回\n"
"            self._target_window_size = (GAME_W, GAME_H)\n"
"            try:\n"
"                _sty = win32gui.GetWindowLong(self.hwnd, win32con.GWL_STYLE)\n"
"                win32gui.SetWindowLong(self.hwnd, win32con.GWL_STYLE, _sty & ~win32con.WS_THICKFRAME)\n"
"            except Exception as _se:\n"
'                _debug_log("[窗口固定] 自愈去边框异常: %s" % _se)\n'
'            _debug_log("[窗口固定] 检测到目标尺寸缺失,已补写死 %dx%d" % (GAME_W, GAME_H))\n'
))

# ---- B3: 下拉手选切换窗口补调_save ----
pairs.append((
'                                self._update_window_rect()\n'
'                                self._detect_minimap()\n'
'                                self._add_log("切换到: %s" % next_w["title"][:20])',
'                                self._update_window_rect()\n'
'                                self._detect_minimap()\n'
'                                self._save_target_window_size()   # 2026-09-17:下拉手选切换窗口此前漏设目标尺寸,对齐其余绑定路径写死1280x800\n'
'                                self._add_log("切换到: %s" % next_w["title"][:20])'
))

for i, (old, new) in enumerate(pairs, 1):
    c = t.count(old)
    assert c == 1, "R%d 锚点命中%d次" % (i, c)
    t = t.replace(old, new, 1)

with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(t)
print("框选置顶+窗口固定自愈完成, 共%d处" % len(pairs))
