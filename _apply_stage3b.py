# -*- coding: utf-8 -*-
"""阶段2: 黑框光点顶替人名基点(B方案) + 选框范围对齐寻怪 + enter不立即关扫 + 删transition关扫
+ 伺服原地直跳dot门控 + cross水平接近保险。全部内存替换、唯一命中断言、全过才写回+编译。"""
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s = open(P, "rb").read().decode("utf-8-sig")
log = []

def rep(old, new, n=1, tag=""):
    global s
    c = s.count(old)
    assert c == n, "[%s] 命中%d次(期望%d) old=%r" % (tag, c, n, old[:80])
    s = s.replace(old, new)
    log.append("OK " + tag)

# A) 新增 _dot_fallback_pos 助手(挂在 lock_screen_from_dot 之后、_get_player_screen_pos 之前)
rep(
"""        return int(sx), int(sy)

    def _get_player_screen_pos(self, frame):""",
"""        return int(sx), int(sy)

    def _dot_fallback_pos(self):
        \"\"\"黑框光点基点兜底(用户2026-09-19 B方案):人名/人脸/后脑特征全丢时,用小地图光点按比例映射出的
        屏幕锁定点(lock_screen_from_dot最终对齐点,已含死区/跟随/站立手动补偿)完整顶替人物基点;map_area/光点也缺返回None。
        与特征点同为游戏窗口像素系;Y两态基线照喂此点;人名恢复当帧由_get_player_screen_pos自动切回特征。\"\"\"
        try:
            if getattr(self, 'map_area_rect', None) is None:
                return None
            if getattr(self, '_player_map_pos', None) is None:
                return None
            _pt = self.lock_screen_from_dot()
            if not _pt:
                return None
            _sx, _sy = _pt
            if _sx is None or _sy is None:
                return None
            return int(_sx), int(_sy)
        except Exception:
            return None

    def _get_player_screen_pos(self, frame):""",
    tag="A_dot助手",
)

# B) 一个锚点都没采: 先 dot 顶替再退回 foot
rep(
"""            if not any(anchor.get("foot") for anchor in anchors):
                return tr["foot"]""",
"""            if not any(anchor.get("foot") for anchor in anchors):
                _dot = self._dot_fallback_pos()   # 特征一个没采:黑框光点基点先顶替,map/光点也缺才退回foot保持点(用户2026-09-19)
                if _dot is not None:
                    self._role_pos_src = 'dot'
                    return _dot
                return tr["foot"]""",
    tag="B_无锚点dot",
)

# C) _pick is None: dot 优先于 90拍旧foot
rep(
"""        if _pick is None:
            tr["miss"] += 1
            if need_full:
                tr["last_full"] = now
            fp = tr["foot"]
            if fp is not None and tr["miss"] > _hold:
                fp = None
                tr["foot"] = None
            if fp is not None:
                tr["last"] = fp
                return fp
            return None""",
"""        if _pick is None:
            tr["miss"] += 1
            if need_full:
                tr["last_full"] = now
            _dot = self._dot_fallback_pos()   # 人名/脸/后脑全丢:黑框光点基点无缝顶替全部下游(用户2026-09-19 B方案),比90拍旧foot点更新
            if _dot is not None:
                self._role_pos_src = 'dot'
                tr["last"] = _dot
                return _dot
            fp = tr["foot"]
            if fp is not None and tr["miss"] > _hold:
                fp = None
                tr["foot"] = None
            if fp is not None:
                if not getattr(self, '_role_pos_src', None):
                    self._role_pos_src = 'hold'
                tr["last"] = fp
                return fp
            self._role_pos_src = 'none'
            return None""",
    tag="C_pickNone_dot",
)

# D) _dir_band_pick_ladder 参数化(范围可由调用方传入对齐寻怪; None走原默认常量,下行不变)
rep(
"""        y_near, x_half = LADDER_TPL_Y_NEAR, LADDER_DIR_X_HALF
        if cdir < 0:
            ylo, yhi = psy, psy + LADDER_TPL_Y_FAR              # 下行:脚下0~150(近边不留白)
        else:
            ylo, yhi = psy - LADDER_DIR_Y_UP_FAR, psy - y_near  # 上行:头顶-200~-20(用户2026-09-18加高到200)""",
"""        if x_half is None:
            x_half = LADDER_DIR_X_HALF
        if cdir < 0:
            if y_far is None:
                y_far = LADDER_TPL_Y_FAR
            ylo, yhi = psy, psy + y_far                        # 下行:脚下0~y_far(近边不留白),默认150
        else:
            if y_far is None:
                y_far = LADDER_DIR_Y_UP_FAR
            if y_near is None:
                y_near = LADDER_TPL_Y_NEAR
            ylo, yhi = psy - y_far, psy - y_near              # 上行:头顶-y_far~-y_near(蒙板段传寻怪范围且y_near=0含脚边,用户2026-09-19)""",
    tag="D_dir_band参数化",
)
# D2) 函数签名加可选参数
rep(
"    def _dir_band_pick_ladder(half, psx, psy, cdir, mon_x):",
"    def _dir_band_pick_ladder(half, psx, psy, cdir, mon_x, x_half=None, y_far=None, y_near=None):",
    tag="D2_dir_band签名",
)

# E) _match_ladder_screen_x 范围对齐寻怪
rep(
'        _frx = LADDER_DIR_X_HALF  # 方向带选梯X左右半宽=300(用户2026-09-18,不用寻怪far_range=500,太宽梯子多会认错)',
'        _fc = self._get_fight_config()\n'
'        _frx = max(50, int(_fc.get("far_range_x") or COMBAT_FAR_RANGE))  # 选框X与扫描同口径=寻怪范围(用户2026-09-19,不再硬编码300)',
    tag="E_match_X范围",
)
rep(
'            ry1, ry2 = ppy - LADDER_DIR_Y_UP_FAR, ppy - LADDER_TPL_Y_NEAR   # 上行:头顶-200~-20(用户2026-09-18加高,下行仍150)',
'            _yup = max(20, int(_fc.get("far_range_y_up") or FAR_RANGE_Y_UP_DEFAULT))\n'
'            ry1, ry2 = ppy - _yup, ppy   # 上行:头顶-_yup~脚边(删-20留白,连通梯从脚边延到怪层都收得到,用户2026-09-19)',
    tag="E_match_Y范围",
)

# F) _enter_to_ladder_up: 不立即关扫, 进 settle 站定相位
rep(
'''        self._climb_state = "to_ladder"
        self._ladder_precise_mode = True  # _reset_climb()刚把它清回False,确定上梯必须立刻置回(堵"首帧状态已是to_ladder但怪扫仍开"的空窗,用户2026-09-15)
        self._climb_ladder_x = 0''',
'''        self._climb_state = "to_ladder"
        # 用户2026-09-19:进上梯不再立刻关怪扫。先保持怪扫开、走到怪X±300内自然松键站定(settle),
        # 连续2帧稳梯建锁成功那一刻才由蒙板段权威置precise=True关扫,关扫窗口最短;走近/站定/扫梯/挪位全程怪扫开、身边出怪可打断回打。
        self._ladder_precise_mode = False
        self._ladder_approach_phase = 'settle'
        self._ladder_settle_last_x = None
        self._ladder_settle_last_char_t = 0
        self._ladder_settle_frames = 0
        self._ladder_pick_beat_scan_t = 0.0
        self._ladder_pick_stable = None
        self._ladder_pick_fail_beats = 0
        self._ladder_lost_beat_scan_t = 0.0
        self._ladder_lost_beats = 0
        self._ladder_repos_until = 0
        self._ladder_repos_dir = 0
        self._climb_ladder_x = 0''',
    tag="F_enter_settle",
)

# G) _try_platform_transition 上行: 删除 precise=True(enter自管settle相位)
rep(
'''            if _up_cands:
                self._ladder_precise_mode = True
                if self._enter_to_ladder_up(px, py, now_ms, _umx, _umy):
                    return True''',
'''            if _up_cands:
                # precise不在此置True:enter后进settle站定相位、怪扫保持开,稳梯建锁成功才关扫(用户2026-09-19)
                if self._enter_to_ladder_up(px, py, now_ms, _umx, _umy):
                    return True''',
    tag="G_transition删关扫",
)

# H) 伺服 settle 原地直跳 dot 门控
rep(
'''            else:
                # settle:键已松,等人物自己停稳;只用人名中心X,帧间位移≤LADDER_SERVO_STOP_DPX连续LADDER_REALIGN_HOLD_FRAMES帧=真停稳,立刻原地直跳
                self._realign_release_move()
                _adiff = abs(snap_x - spx)''',
'''            else:
                # settle:键已松,等人物自己停稳;只用人名中心X,帧间位移≤LADDER_SERVO_STOP_DPX连续LADDER_REALIGN_HOLD_FRAMES帧=真停稳,立刻原地直跳
                self._realign_release_move()
                if getattr(self, '_role_pos_src', None) == 'dot':
                    # ≤10px原地直跳必须认人名/后脑特征点:黑框光点基点精度不足以保证抓梯。特征全丢时暂停伺服、
                    # 不耗修正次数/轮次、不拿dot硬跳,原地等特征恢复(跑跳60-75不gate,用户2026-09-19)
                    self._rlog_throttle('realign_dot_wait', '人名/后脑特征丢失(黑框光点顶替中),原地直跳暂停、等特征恢复', 500, log='behavior')
                    return False
                _adiff = abs(snap_x - spx)''',
    tag="H_settle_dot门控",
)

# I) cross 水平接近保险(X>300先走,怪扫开)
rep(
'''            _cross_cands = _dl.get('cross_candidates', [])
            if self._try_platform_transition(_cross_cands, now):''',
'''            # 水平接近保险(用户2026-09-19):目标怪X还在300外先水平走近、不进上梯(B线本就X≥300归pursue,
            # 此保险只兜坐标临界/冻结;走近段怪扫开,身边刷同层怪B线下帧cast/pursue自然打断回打)。此时_combat_transit尚False,战斗移动可用。
            if abs(t_cx - px) > LADDER_DIR_X_HALF:
                self._set_combat_move('right' if t_cx > px else 'left')
                self._rlog_throttle('cross_walkin', '目标怪X差%+d>%d,先水平走近再选梯(怪扫开)' % (t_cx - px, LADDER_DIR_X_HALF), 800, log='behavior')
                return
            _cross_cands = _dl.get('cross_candidates', [])
            if self._try_platform_transition(_cross_cands, now):''',
    tag="I_cross水平保险",
)

open(P, "wb").write(s.encode("utf-8-sig"))
import py_compile
py_compile.compile(P, doraise=True)
print("\n".join(log))
print("阶段2写回并编译通过")
