# -*- coding: utf-8 -*-
"""阶段3b: 蒙板段选梯重写——删两帧累积池、pick相位二帧稳梯才建锁(建锁才关扫)、
已锁红框每帧取实时同把(X+Y双判)、冻块仅空帧补位、平地连续3拍补不回清锁回pick。"""
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s = open(P, "rb").read().decode("utf-8-sig")
log = []
def rep(old, new, n=1, tag=""):
    global s
    c = s.count(old)
    assert c == n, "[%s] 命中%d次(期望%d) old=%r" % (tag, c, n, old[:80])
    s = s.replace(old, new); log.append("OK " + tag)

# rep1: 删两帧累积池, 改为当帧实时白框 + 新增相位/扫描节拍/起跳判定变量
rep(
'''                            # --- ①两帧累积候选池:当前白框并入,邻帧近邻归并同一把,淘汰超窗旧点 ---
                            if not hasattr(self, '_lad_marks_recent'):
                                self._lad_marks_recent = []
                            _recent = self._lad_marks_recent
                            for (_wx0, _wy0) in _white_now:
                                _hit_i = None
                                for _ri, (_rx0, _ry0, _rt0) in enumerate(_recent):
                                    if abs(_rx0 - _wx0) <= LADDER_RECENT_MERGE_PX and abs(_ry0 - _wy0) <= LADDER_RECENT_MERGE_PX:
                                        _hit_i = _ri
                                        break
                                if _hit_i is not None:
                                    _recent[_hit_i] = (_wx0, _wy0, _now_lm)   # 同一把:刷新到最新屏幕位置
                                else:
                                    _recent.append((_wx0, _wy0, _now_lm))
                            self._lad_marks_recent = [p for p in _recent if _now_lm - p[2] <= LADDER_PICK_RECENT_MS]
                            # 候选=两帧累积池里扫到的梯子;选哪把完全交给下面方向带(上行头顶Y-150~-20/下行脚下0~+150、X左右各300、怪在哪侧选哪侧),
                            # 只看方向不算梯子距离(用户2026-09-18定稿,取代三轮漏斗/怪梯人距离求和)。
                            _half = [(x, y) for (x, y, t) in self._lad_marks_recent]
                            _rx = _ry = None
                            _db_band = []
                            _stage = ''
                            _lock = getattr(self, '_ladder_lock', None)''',
'''                            # 候选=当帧实时白框(用户2026-09-19删两帧累积池:建锁改由"连续扫描节拍二帧稳定"判稳,
                            # 已锁后红框坐标每帧取实时同条;数据层一把梯只一个对象,不再累积旧帧)。
                            _half = _white_now
                            _rx = _ry = None
                            _db_band = []
                            _stage = ''
                            _lock = getattr(self, '_ladder_lock', None)
                            _fc = self._get_fight_config()
                            _far_x = max(50, int(_fc.get("far_range_x") or COMBAT_FAR_RANGE))
                            _far_yu = max(20, int(_fc.get("far_range_y_up") or FAR_RANGE_Y_UP_DEFAULT))
                            _ap = getattr(self, '_ladder_approach_phase', 'align')
                            _scan_t = getattr(self, '_lad_marks_scan_t', 0.0)
                            _jumped = (_climb_st == 'climbing') or (getattr(self, '_ladder_jump_phase', None) == 'post_jump') \\
                                or (getattr(self, '_ladder_realign_phase', None) in ('approach', 'settle'))''',
    tag="rep1删池加变量",
)

# rep2: 未锁分支 → pick相位二帧稳梯建锁
rep(
'''                            if _lock is None:
                                # ②未锁建锁·方向带(用户2026-09-18定稿,只看方向不算梯子距离):Y上行头顶-150~-20/下行脚下0~+150、X左右各300、有怪只留怪那侧
                                _has_mon = (_tmox is not None)
                                _pick_l, _pick_reason, _db_band = self._dir_band_pick_ladder(
                                    _half, _psx, _psy, _cdir, _tmox if _has_mon else None)
                                if _pick_l is not None:
                                    _rx, _ry = int(_pick_l[0]), int(_pick_l[1])
                                    self._ladder_lock = (_rx, _ry, _now_lm)    # 建锁:同时冻结这把梯此刻像素块(身份),坐标后续随动
                                    self._ladder_snap_x = _rx
                                    self._ladder_lock_t0 = _now_lm             # 建锁时刻(掉锁日志算"已锁多久")
                                    self._freeze_ladder_patch(_rx, _ry)
                                    _sel = (_rx, _ry, True)
                                    _stage = '建锁'
                                    self._note_freq_event('lock_lad', 3, 1000, "1秒内反复锁定梯子%d次(疑似掉锁/白框不稳)")
                                    _det = ';'.join('%d,%d' % (wx, wy) for wx, wy in _db_band) or '无'
                                    _debug_log("[选梯·建锁] 方向带向%s 人=(%d,%d) 怪X=%s 带内%d把[%s] 选中(%d,%d) | 带内:%s" % (
                                        '上' if _cdir > 0 else '下', _psx, _psy, _tmox, len(_db_band), _pick_reason, _rx, _ry, _det))
                                else:
                                    _stage = '未锁无候选'
''',
'''                            if _lock is None:
                                # ②未锁:只在to_ladder的pick相位(已走到怪下方站定、怪扫仍开)按"扫描节拍二帧稳定"建锁;
                                # settle走近/repos挪位不在此建锁;上行选框范围=寻怪范围、含脚边(y_near=0)。建锁那一刻才权威关怪扫。
                                if _climb_st == 'to_ladder' and _ap == 'pick':
                                    _pick_l, _pick_reason, _db_band = self._dir_band_pick_ladder(
                                        _half, _psx, _psy, _cdir, _tmox,
                                        x_half=_far_x, y_far=_far_yu, y_near=0)
                                    if _scan_t != self._ladder_pick_beat_scan_t:
                                        self._ladder_pick_beat_scan_t = _scan_t   # 一个新扫描节拍
                                        if _pick_l is not None:
                                            _bx, _by = int(_pick_l[0]), int(_pick_l[1])
                                            _stb = self._ladder_pick_stable
                                            if _stb and abs(_bx - _stb[0]) <= LADDER_PICK_STABLE_DX and abs(_by - _stb[1]) <= LADDER_PICK_STABLE_DY:
                                                _beats = _stb[2] + 1
                                            else:
                                                _beats = 1
                                            self._ladder_pick_stable = (_bx, _by, _beats)
                                            if _beats >= LADDER_PICK_STABLE_BEATS:
                                                # 二帧稳梯:建锁+冻像素块身份,这一帧才关怪扫(关扫窗口最短),转align对位
                                                self._ladder_lock = (_bx, _by, _now_lm)
                                                self._ladder_snap_x = _bx
                                                self._ladder_lock_t0 = _now_lm
                                                self._freeze_ladder_patch(_bx, _by)
                                                self._ladder_approach_phase = 'align'
                                                self._ladder_pick_stable = None
                                                self._ladder_pick_fail_beats = 0
                                                self._ladder_lost_beats = 0
                                                self._ladder_lost_beat_scan_t = _scan_t
                                                self._ladder_precise_mode = True
                                                _sel = (_bx, _by, True)
                                                _rx, _ry = _bx, _by
                                                _stage = '二帧稳梯建锁'
                                                self._note_freq_event('lock_lad', 3, 1000, "1秒内反复锁定梯子%d次(疑似掉锁/白框不稳)")
                                                _debug_log("[选梯·建锁] 二帧稳定向%s 人=(%d,%d) 怪X=%s 带内%d把[%s] 选中(%d,%d),已关怪扫一心上梯" % (
                                                    '上' if _cdir > 0 else '下', _psx, _psy, _tmox, len(_db_band), _pick_reason, _bx, _by))
                                            else:
                                                self._ladder_pick_fail_beats += 1
                                                _stage = '稳梯观察%d/%d' % (_beats, LADDER_PICK_STABLE_BEATS)
                                        else:
                                            self._ladder_pick_stable = None
                                            self._ladder_pick_fail_beats += 1
                                            _stage = '带内无梯'
                                else:
                                    _stage = '未锁·相位%s' % _ap''',
    tag="rep2未锁二帧建锁",
)

# rep3: 已锁分支 → 实时同把优先+冻块空帧补位+3拍丢失回pick
rep(
'''                            else:
                                # ③已锁·用户2026-09-15冻像素块:优先拿建锁冻结的这把梯实拍小块,在上一帧位置附近搜索区重定位
                                # (坐标随动、不串另一把、白框闪空也能找回);冻结块这帧没认回就在【寻怪范围白框池】重找同一把新点(用户2026-09-16:不钉旧点、不全屏);池里一把都没有才snap=None保身份,连续1500ms真丢才清锁
                                _lx, _ly, _lt = _lock
                                _patch = getattr(self, '_ladder_lock_patch', None)
                                _frf = self._raw_frame
                                if _patch is not None and _frf is not None:
                                    _ph, _pw = _patch.shape[:2]
                                    _fh2, _fw2 = _frf.shape[:2]
                                    _sx1 = max(0, _lx - LADDER_LOCK_SEARCH_X); _sx2 = min(_fw2, _lx + LADDER_LOCK_SEARCH_X)
                                    _sy1 = max(0, _ly - LADDER_LOCK_SEARCH_Y); _sy2 = min(_fh2, _ly + LADDER_LOCK_SEARCH_Y)
                                    _search = _frf[_sy1:_sy2, _sx1:_sx2]
                                    if _search.shape[0] > _ph and _search.shape[1] > _pw:
                                        _rr = cv2.matchTemplate(_search, _patch, cv2.TM_CCOEFF_NORMED)
                                        _, _mv, _, _mloc = cv2.minMaxLoc(_rr)
                                        if _mv >= LADDER_LOCK_PATCH_SIM:
                                            _rx = int(_sx1 + _mloc[0] + _pw // 2)
                                            _ry = int(_sy1 + _mloc[1] + _ph // 2)
                                            self._ladder_lock = (_rx, _ry, _now_lm)   # 冻结块认回自己:身份不变、坐标更新到最新
                                            self._ladder_snap_x = _rx
                                            _sel = (_rx, _ry, True)
                                            _stage = '冻结块跟踪'
                                if _sel is None:
                                    # 冻结块这帧没认回:直接在【寻怪范围两帧白框池_half】里重找同一把(用户2026-09-16:不钉旧点、
                                    # 丢了就在寻怪范围找、绝不全屏;白框本就只在寻怪范围crop扫、结果现成不另算)。镜头主要横滚、梯Y相邻帧几乎不动:
                                    # 先在Y±LADDER_LOCK_MAX_STEP_Y内取离上帧锁点最近(不串到上下另一把),Y池一把没有再放宽全池宁跟勿断;
                                    # X不再卡120硬邻域(快滚一帧位移>120正是旧法接不上、掉去钉旧点的根因)。
                                    _same_y = [p for p in _half if abs(p[1] - _ly) <= LADDER_LOCK_MAX_STEP_Y]
                                    _pool = _same_y if _same_y else _half
                                    if _pool:
                                        _nx, _ny = min(_pool, key=lambda p: (p[0] - _lx) ** 2 + (p[1] - _ly) ** 2)
                                        _rx, _ry = _nx, _ny
                                        self._ladder_lock = (_rx, _ry, _now_lm)    # 身份不变、坐标更新到寻怪范围里重找到的最新位置
                                        self._ladder_snap_x = _rx
                                        _sel = (_rx, _ry, True)
                                        _stage = '寻怪范围重找'
                                    else:
                                        # ④这帧寻怪范围两帧池一把白框都没有(全被挡/没扫到):不钉旧点(旧法吐上帧坐标,镜头滚后框钉死1~2秒、
                                        # 直跳拿旧坐标算出差值乱跳),snap置None=红框这帧不画、直跳不拿旧坐标算差值;但保留_ladder_lock身份,
                                        # 下帧继续在寻怪范围找同一把;只有连续LADDER_MERGE_WAIT_MS池里真一把都没有才清锁(身份/冻结块一起清),下帧重选/回主线
                                        self._ladder_snap_x = None
                                        _sel = None
                                        _stage = '空帧无新点'
                                        if _now_lm - _lt >= LADDER_MERGE_WAIT_MS:
                                            _hold_ms = int(_now_lm - getattr(self, '_ladder_lock_t0', _now_lm))
                                            _debug_log("[梯子·掉锁] 真丢失:寻怪范围连续%dms一把白框都没有(最后锁点(%d,%d),这把已锁%dms),清锁回主线重选/打怪" % (
                                                LADDER_MERGE_WAIT_MS, _lx, _ly, _hold_ms))
                                            self._ladder_lock = None
                                            self._ladder_snap_x = None
                                            self._ladder_lock_patch = None
                                            _rx = _ry = None
                                            _stage = '真丢失放弃'
''',
'''                            else:
                                # ③已锁(用户2026-09-19):红框坐标每帧取【实时白框里的同一条】(X+Y双判,半径=合并阈值),
                                # 数据层一把梯只一个对象、红框与真梯实时重合;实时这帧没同条,才用建锁冻结块matchTemplate补位(仅空帧补位)。
                                _lx, _ly, _lt = _lock
                                _rt = None
                                _same = [p for p in _half if abs(p[0] - _lx) <= LADDER_MERGE_DX and abs(p[1] - _ly) <= LADDER_MERGE_DY]
                                if _same:
                                    _nx, _ny = min(_same, key=lambda p: (p[0] - _lx) ** 2 + (p[1] - _ly) ** 2)
                                    _rt = (int(_nx), int(_ny)); _stage = '实时同把'
                                else:
                                    _patch = getattr(self, '_ladder_lock_patch', None)
                                    _frf = self._raw_frame
                                    if _patch is not None and _frf is not None:
                                        _ph, _pw = _patch.shape[:2]
                                        _fh2, _fw2 = _frf.shape[:2]
                                        _sx1 = max(0, _lx - LADDER_LOCK_SEARCH_X); _sx2 = min(_fw2, _lx + LADDER_LOCK_SEARCH_X)
                                        _sy1 = max(0, _ly - LADDER_LOCK_SEARCH_Y); _sy2 = min(_fh2, _ly + LADDER_LOCK_SEARCH_Y)
                                        _search = _frf[_sy1:_sy2, _sx1:_sx2]
                                        if _search.shape[0] > _ph and _search.shape[1] > _pw:
                                            _rr = cv2.matchTemplate(_search, _patch, cv2.TM_CCOEFF_NORMED)
                                            _, _mv, _, _mloc = cv2.minMaxLoc(_rr)
                                            if _mv >= LADDER_LOCK_PATCH_SIM:
                                                _rt = (int(_sx1 + _mloc[0] + _pw // 2), int(_sy1 + _mloc[1] + _ph // 2)); _stage = '冻结块补位'
                                if _rt is not None:
                                    _rx, _ry = _rt
                                    self._ladder_lock = (_rx, _ry, _now_lm)   # 身份不变、坐标更新到实时/补位点
                                    self._ladder_snap_x = _rx
                                    self._ladder_lost_beats = 0
                                    _sel = (_rx, _ry, True)
                                else:
                                    # 实时+冻块这帧都补不回:snap=None(红框这帧不画、对位不拿旧点),按扫描节拍计丢失
                                    self._ladder_snap_x = None
                                    _sel = None
                                    _stage = '补不回'
                                    if _scan_t != self._ladder_lost_beat_scan_t:
                                        self._ladder_lost_beat_scan_t = _scan_t
                                        self._ladder_lost_beats += 1
                                        if (not _jumped) and self._ladder_lost_beats >= LADDER_PICK_FAIL_BEATS:
                                            # 未起跳(平地align)连续3拍补不回:清锁回pick重新二帧稳梯(再3拍无→主线挪位/冷却回主线);
                                            # 起跳后(post_jump/realign/climbing)保身份等找回,不清锁、不挪位
                                            _debug_log("[梯子·掉锁] 建锁后平地连续%d扫描节拍实时+冻块补不回(最后锁点(%d,%d)),清锁回pick重新稳梯" % (
                                                LADDER_PICK_FAIL_BEATS, _lx, _ly))
                                            self._ladder_lock = None
                                            self._ladder_lock_patch = None
                                            self._ladder_snap_x = None
                                            self._ladder_approach_phase = 'pick'
                                            self._ladder_pick_stable = None
                                            self._ladder_pick_fail_beats = 0
                                            self._ladder_pick_beat_scan_t = 0.0
                                            self._ladder_lost_beats = 0
                                            _rx = _ry = None
                                            _stage = '回pick重稳' ''',
    tag="rep3已锁实时优先",
)

# rep4: 节流日志适配新相位/丢拍
rep(
'''                                if _lock is None:
                                    _allx = ('带内%d把:%s' % (len(_db_band), ';'.join('%d,%d' % (wx, wy) for wx, wy in _db_band))) if _db_band else '带内无梯'
                                else:
                                    # C 跟踪态补"锁点帧漂移"(相对上一帧移动多少,镜头快滚/串梯一眼可见)和"人梯X差"
                                    _drift = (abs(_rx - _lock[0]) + abs(_ry - _lock[1])) if _rx is not None else -1
                                    _xdiff = (_rx - _psx) if _rx is not None else 0
                                    _allx = '锁点(%d,%d)窗内%d把 帧漂移%d 人梯X差%+.0f' % (
                                        _lock[0], _lock[1], len(_half), _drift, _xdiff)''',
'''                                if _lock is None:
                                    if _climb_st == 'to_ladder' and _ap == 'pick':
                                        _allx = ('%s 带内%d把:%s' % (_stage, len(_db_band), ';'.join('%d,%d' % (wx, wy) for wx, wy in _db_band))) if _db_band else ('%s 带内无梯' % _stage)
                                    else:
                                        _allx = '相位%s(不建锁)' % _ap
                                else:
                                    # 已锁补"锁点帧漂移"(镜头快滚/串梯一眼可见)、"人梯X差"、连续补不回拍数
                                    _drift = (abs(_rx - _lock[0]) + abs(_ry - _lock[1])) if _rx is not None else -1
                                    _xdiff = (_rx - _psx) if _rx is not None else 0
                                    _allx = '%s 锁点(%d,%d)窗内%d把 帧漂移%d 人梯X差%+.0f 丢拍%d' % (
                                        _stage, _lock[0], _lock[1], len(_half), _drift, _xdiff, self._ladder_lost_beats)''',
    tag="rep4节流日志",
)

open(P, "wb").write(s.encode("utf-8-sig"))
import py_compile
py_compile.compile(P, doraise=True)
print("\n".join(log)); print("阶段3b写回并编译通过")
