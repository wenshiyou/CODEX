# -*- coding: utf-8 -*-
# 根因修复(用户2026-09-22拍板"按你的来、少打补丁、从根本解决"):
# A 光点去钉旧值(find_player_dot空帧/小地图丢点都返回None,物理删last_player_pos/_last_smooth_dot)
#   + 两处None守卫(_transit_step爬梯中丢光点只暂停本帧不终止; 镜头检测当前光点None不崩)
# B 忙档截图16fps->30fps + 照搬上梯高帧的自适应退避(封顶60ms=旧现状), 闲档仍100ms, YOLO/模板/血条秒节流不动
# C 人物基点硬闸: 固定120px -> 按帧间隔dt归一化的速度判据(高帧战斗夹60px, 低帧夹150px), 真瞬移仍走黑框重捕
import io, sys

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
raw = io.open(P, "rb").read().decode("utf-8-sig")
raw = raw.replace("\r\n", "\n")

PATCHES = []

# ---------- C 常量: 删固定120, 加归一化三常量 ----------
PATCHES.append(("C0-硬闸常量",
"""ROLE_BIGJUMP_PX = 120       # 人物基点一帧最大合法跳变px(用户2026-09-20根治坐标帧间拽飞→B误判cross锁空梯):任何定位源(人名/脸/后脑/宠物)、任何帧(局部/全图)、无论分数多高,相对上一稳定基点位移>120一律不采信该模板候选、丢弃转黑框ROI重搜;正常跑步一帧远<120,真瞬移(>=250)由_research_anchor_around_dot借黑框光点第二源在新位置重捕""",
"""# 人物基点帧间跳变速度闸(2026-09-22由固定120px改为按帧间隔dt归一化):根因是忙档提到30fps后固定px阈值相对变松,
# 且误匹配到同名文本表现为"瞬时跳到另一固定文本"(高帧细密采样下真实移动是连续小步、误匹配是单帧大跳变)。
# 合法位移=ROLE_MAX_SPEED_PX_S*dt,夹在[FLOOR,CAP]:30fps战斗约60px(真实跑步/下落/爬梯帧位移<60,实测误匹配70~236px被拦),
# 低帧卡顿夹到150px(超大跳变不直接放行、仍转黑框光点第二源重捕);真瞬移(>=250)照样被拦后由_research_anchor_around_dot重捕。
ROLE_MAX_SPEED_PX_S = 1800.0   # 基点合法最大速度px/s(旧120px@约67ms反推的保守初值,宁漏拦不误杀真移动;真机按[跳变拦截]日志复核再标定)
ROLE_BIGJUMP_FLOOR_PX = 60     # dt很小(高帧)时单帧最小阈值,防真实快动作(下落/跳高)被误杀
ROLE_BIGJUMP_CAP_PX = 150      # dt很大(卡顿/低帧)时单帧阈值上限,超过一律不采信、转黑框重捕"""))

# ---------- B 常量: 忙档高帧自适应 ----------
PATCHES.append(("B0-忙档常量",
"""LADDER_PRECISE_MARK_MS = 20       # 高帧下梯子特征白框扫描节流(在识别线程;用户2026-09-15加快30→20≈50Hz,选梯更跟手;CPU有自适应退避兜底)""",
"""LADDER_PRECISE_MARK_MS = 20       # 高帧下梯子特征白框扫描节流(在识别线程;用户2026-09-15加快30→20≈50Hz,选梯更跟手;CPU有自适应退避兜底)
# 忙档高帧(用户2026-09-22根因修复):战斗忙档截图/人物/B决策节拍目标30fps,治16fps下窗口人名基点帧间跳变把平层怪误判cross;
# YOLO/怪模板/血条在B线程另按秒节流、提帧不多跑;跑不完照搬上梯高帧自适应退避、封顶60ms(=旧16fps,最坏退回现状),闲档仍100ms省电。
PERSON_BUSY_TARGET_MS = 33       # 忙档目标周期≈30fps
PERSON_BUSY_PERIOD_MAX = 60      # 自适应退避上限=旧忙档周期(机器再慢也只退回16fps现状,不会更差)
PERSON_BUSY_MIN_SLEEP_MS = 3     # 忙档每轮至少让出的空闲ms(保GIL/主线UI),防吃满一个核(与上梯高帧同值)
PERSON_BUSY_OVERLOAD_N = 3       # 连续几轮留不出最小空闲=过载,降帧一档
PERSON_BUSY_RELAX_N = 15         # 连续约15轮很轻松(≈0.4s)=性能够,升回一档直到目标周期
PERSON_BUSY_STEP_MS = 3          # 忙档自适应每档退避/回升步长ms"""))

# ---------- A1b find_player_dot docstring 空图措辞 ----------
PATCHES.append(("A1b-docstring空图",
"""        返回:(x,y)小地图块坐标;空图沿用上一帧;无合格团返回None(主循环丢点/重定位契约不变)。\"\"\"""",
"""        返回:(x,y)小地图块坐标;空图/无合格团一律返回None、绝不沿用旧光点(用户2026-09-22坐标不钉旧值;主循环丢点/重定位契约不变)。\"\"\""""))

# ---------- A1 find_player_dot 空帧返回None ----------
PATCHES.append(("A1-find_player_dot空帧",
"""        # [健壮性] 截图瞬时失败传入None/空数组时沿用上一光点、不清空,绝不因inRange空图闪退
        if bgr is None or getattr(bgr, "size", 0) == 0:
            return getattr(self, "last_player_pos", None)""",
"""        # [健壮性] 截图瞬时失败传入None/空数组时返回None(用户2026-09-22绝不沿用旧光点、不钉旧值),下游本帧跳过、下帧重检
        if bgr is None or getattr(bgr, "size", 0) == 0:
            return None"""))

# ---------- A2 无合格团注释 ----------
PATCHES.append(("A2-无团注释",
"""        if not cands:
            # 本帧无合格团:不清除last_player_pos(留作下帧最近邻锚点),但仍返回None交主循环丢点逻辑
            return None""",
"""        if not cands:
            # 本帧无合格团:返回None交主循环丢点逻辑(不钉旧值、不冻结,用户2026-09-22)
            return None"""))

# ---------- A3 删 last_player_pos 写 ----------
PATCHES.append(("A3-删last_player_pos写",
"""        self.last_player_pos = (cx, cy)  # 更新上次位置(下帧最近邻锚点)
        return (cx, cy)  # 录制绿线/梯子/导航/边界共用的唯一中心点""",
"""        return (cx, cy)  # 录制绿线/梯子/导航/边界共用的唯一中心点(不缓存旧点,每帧独立检测,用户2026-09-22)"""))

# ---------- A4 init 删字段 ----------
PATCHES.append(("A4-init删字段",
"""        self._auto_refresh = True

        self.last_player_pos = None
        self.frame_count = 0""",
"""        self._auto_refresh = True

        self.frame_count = 0"""))

# ---------- A5 2340注释 ----------
PATCHES.append(("A5-小抖动注释",
"""                    return  # 小抖动:锁定基准不动=坐标系恒定(关键:不清last_player_pos,光点最近邻锚点连续)""",
"""                    return  # 小抖动:锁定基准不动=坐标系恒定(光点每帧独立检测,不依赖旧点)"""))

# ---------- A6 2345-2348 重定区域清空 ----------
PATCHES.append(("A6-重定区域清字段",
"""        self.minimap_rect = new_minimap
        self.map_area_rect = new_map
        self._save_region()
        self.last_player_pos = None
""",
"""        self.minimap_rect = new_minimap
        self.map_area_rect = new_map
        self._save_region()
"""))

# ---------- A7 8256 鼠标刷新 ----------
PATCHES.append(("A7-鼠标刷新清字段",
"""            self._detect_minimap()
            self.frame_count = 0
            self.last_player_pos = None
            return""",
"""            self._detect_minimap()
            self.frame_count = 0
            return"""))

# ---------- A8 9402 框选应用(20空格缩进) ----------
PATCHES.append(("A8-框选应用清字段",
"""                    self._save_region()
                    self.frame_count = 0
                    self.last_player_pos = None
                    self._auto_refresh = False""",
"""                    self._save_region()
                    self.frame_count = 0
                    self._auto_refresh = False"""))

# ---------- A9 9568 另一处重定(8空格缩进) ----------
PATCHES.append(("A9-重定清字段",
"""        self._save_region()
        self.frame_count = 0
        self.last_player_pos = None
        self._auto_refresh = False
        self._selecting = False""",
"""        self._save_region()
        self.frame_count = 0
        self._auto_refresh = False
        self._selecting = False"""))

# ---------- A10 小地图线程丢点: 删_smooth沿用,置None,保留重定位自救 ----------
PATCHES.append(("A10-minimap丢点置None",
"""                    _pdot = self.find_player_dot(_frame)
                    if _pdot is not None:
                        self._player_map_pos = _pdot
                        self._last_smooth_dot = _pdot
                        self._map_dot_lost = 0
                    else:
                        if getattr(self, '_last_smooth_dot', None) is not None:
                            self._player_map_pos = self._last_smooth_dot
                        if getattr(self, '_auto_refresh', True) and self.hwnd:
                            self._map_dot_lost = getattr(self, '_map_dot_lost', 0) + 1
                            _now_force = time.time()
                            if (self._map_dot_lost >= 15
                                    and _now_force - getattr(self, '_last_minimap_force_t', 0) > 2.0):
                                self._last_minimap_force_t = _now_force
                                self._map_dot_lost = 0
                                try:
                                    self._detect_minimap(debug=False)
                                except Exception:
                                    pass""",
"""                    _pdot = self.find_player_dot(_frame)
                    if _pdot is not None:
                        self._player_map_pos = _pdot
                        self._map_dot_lost = 0
                    else:
                        # 本帧丢点:绝不钉旧值(用户2026-09-22),光点置None,下游本帧跳过、下帧重检;
                        # 爬梯/下跳进行中由_transit_step入口对climb状态容忍本帧None(不终止整套动作、不松键)。
                        self._player_map_pos = None
                        if getattr(self, '_auto_refresh', True) and self.hwnd:
                            self._map_dot_lost = getattr(self, '_map_dot_lost', 0) + 1
                            _now_force = time.time()
                            if (self._map_dot_lost >= 15
                                    and _now_force - getattr(self, '_last_minimap_force_t', 0) > 2.0):
                                self._last_minimap_force_t = _now_force
                                self._map_dot_lost = 0
                                try:
                                    self._detect_minimap(debug=False)
                                except Exception:
                                    pass"""))

# ---------- B守1 镜头检测当前光点None ----------
PATCHES.append(("B守-镜头检测None",
"""        # 判断光点是否在移动（光点不动=人物不动=镜头大概率不动）
        dot_moving = False
        if self._last_dot_pos is not None:
            dot_dx = self._player_map_pos[0] - self._last_dot_pos[0]
            dot_dy = self._player_map_pos[1] - self._last_dot_pos[1]
            if abs(dot_dx) > 0 or abs(dot_dy) > 0:
                dot_moving = True
        self._last_dot_pos = (self._player_map_pos[0], self._player_map_pos[1])""",
"""        # 判断光点是否在移动（光点不动=人物不动=镜头大概率不动）;当前帧光点None(光门遮挡)不判移动、不解包崩、不更新基准(用户2026-09-22)
        dot_moving = False
        _cur_dot = self._player_map_pos
        if _cur_dot is not None and self._last_dot_pos is not None:
            dot_dx = _cur_dot[0] - self._last_dot_pos[0]
            dot_dy = _cur_dot[1] - self._last_dot_pos[1]
            if abs(dot_dx) > 0 or abs(dot_dy) > 0:
                dot_moving = True
        if _cur_dot is not None:
            self._last_dot_pos = (_cur_dot[0], _cur_dot[1])"""))

# ---------- B守2 _transit_step 入口: 爬梯中丢光点只暂停本帧 ----------
PATCHES.append(("B守-transit入口",
"""        if not self._combat_transit or not self._player_map_pos:
            self._combat_transit = False
            self._transit_target = None
            self._ladder_precise_mode = False   # 异常出口也要重开怪扫(用户2026-09-15开关配对)
            return""",
"""        if not self._combat_transit:
            self._combat_transit = False
            self._transit_target = None
            self._ladder_precise_mode = False
            return
        if not self._player_map_pos:
            # 光点本帧丢(光门/UI短暂遮挡):爬梯/下跳状态机进行中(_climb_state!=none)只暂停本帧——不终止、不清状态、不松键,
            # 等光点回来继续(连续长丢由爬梯总超时/录制时长+2s兜底);尚未进梯的walk/平地段才终止回打怪(用户2026-09-22去钉旧值配套)。
            if getattr(self, '_climb_state', 'none') != 'none':
                return
            self._combat_transit = False
            self._transit_target = None
            self._ladder_precise_mode = False   # 异常出口也要重开怪扫(用户2026-09-15开关配对)
            return"""))

# ---------- B1 忙档周期30fps自适应 ----------
PATCHES.append(("B1-忙档周期",
"""            else:
                self._precise_adapt_p = None  # 离开高帧:自适应档位清空,下次进按核数目标重新起步
                self._precise_ov_n = self._precise_rx_n = 0
                # 人物地基帧率保底(用户2026-09-17):人物识别是永不停的地基线程、吃这里的帧,不能被闲时省电拖到3fps(333ms延迟);
                # 截图(mss BitBlt释放GIL)很便宜,YOLO/模板在B线程另按时间节流、帧多也不会多跑。忙(锁怪/0.4s内见怪)保底60ms≈16fps,闲保底100ms≈10fps;上梯高帧档(_precise_now)不变。
                _PERSON_BUSY_MAX_MS, _PERSON_IDLE_MAX_MS = 60, 100
                _period = (min(self._perf_val('detect_busy_ms'), _PERSON_BUSY_MAX_MS) if _busy
                           else min(self._perf_val('detect_idle_ms'), _PERSON_IDLE_MAX_MS))""",
"""            else:
                self._precise_adapt_p = None  # 离开高帧:自适应档位清空,下次进按核数目标重新起步
                self._precise_ov_n = self._precise_rx_n = 0
                # 忙档(锁怪/0.4s内见怪)目标30fps(用户2026-09-22根因:16fps下窗口人名基点帧间跳变把平层怪误判cross,提帧让真实移动成连续小步、
                # 误匹配暴露为单帧大跳变被速度闸拦);截图(mss BitBlt释放GIL)很便宜,YOLO/模板/血条在B线程另按秒节流、帧多不多跑。
                # 忙档照搬上梯高帧自适应退避(跑不完每档+3ms、封顶60ms=旧16fps最坏退回现状);闲档仍100ms≈10fps省电。
                _PERSON_IDLE_MAX_MS = 100
                if _busy:
                    _btgt = min(self._perf_val('detect_busy_ms'), float(PERSON_BUSY_TARGET_MS))
                    _ap = getattr(self, '_busy_adapt_p', None)
                    if _ap is None:
                        _ap = _btgt; self._busy_adapt_p = _ap; self._busy_ov_n = 0; self._busy_rx_n = 0
                    if _elapse > _ap - PERSON_BUSY_MIN_SLEEP_MS:
                        self._busy_ov_n += 1; self._busy_rx_n = 0
                        if self._busy_ov_n >= PERSON_BUSY_OVERLOAD_N and _ap < PERSON_BUSY_PERIOD_MAX:
                            _ap = min(PERSON_BUSY_PERIOD_MAX, _ap + PERSON_BUSY_STEP_MS)
                            self._busy_adapt_p, self._busy_ov_n = _ap, 0
                            _debug_log("[忙帧监管] 单轮%.0fms跑不完%.0fms档,退避到%.0fms防CPU卡死" % (
                                _elapse, _ap - PERSON_BUSY_STEP_MS, _ap))
                    else:
                        self._busy_rx_n += 1; self._busy_ov_n = 0
                        if self._busy_rx_n >= PERSON_BUSY_RELAX_N and _ap > _btgt:
                            _ap = max(_btgt, _ap - PERSON_BUSY_STEP_MS)
                            self._busy_adapt_p, self._busy_rx_n = _ap, 0
                    _period = _ap
                else:
                    self._busy_adapt_p = None  # 离忙档重置自适应,下次进战斗从目标周期起步
                    self._busy_ov_n = self._busy_rx_n = 0
                    _period = min(self._perf_val('detect_idle_ms'), _PERSON_IDLE_MAX_MS)"""))

# ---------- B2 slack兜底(高帧/忙档都让3ms) ----------
PATCHES.append(("B2-slack兜底",
"""            _slack = _period - _elapse
            if _precise_now and _slack < LADDER_PRECISE_MIN_SLEEP_MS:
                _slack = LADDER_PRECISE_MIN_SLEEP_MS   # 高帧CPU监管兜底:哪怕本轮跑超时也强制让出3ms给GIL/主线UI,绝不吃满一个核""",
"""            _slack = _period - _elapse
            if (_precise_now or _busy) and _slack < PERSON_BUSY_MIN_SLEEP_MS:
                _slack = PERSON_BUSY_MIN_SLEEP_MS   # 高帧/忙档CPU监管兜底:哪怕本轮跑超时也强制让出3ms给GIL/主线UI,绝不吃满一个核"""))

# ---------- C1 tr init 加 last_t ----------
PATCHES.append(("C1-tr初始化last_t",
"""            tr = {"last": None, "foot": None, "miss": 0, "last_full": 0.0, "face": None, "score": 0.0, "off_save_t": 0.0}""",
"""            tr = {"last": None, "foot": None, "miss": 0, "last_full": 0.0, "face": None, "score": 0.0, "off_save_t": 0.0, "last_t": 0.0}"""))

# ---------- C2 冷启动首点 last_t ----------
PATCHES.append(("C2-冷启动首点last_t",
"""                tr["last"] = (_ax0, _ay0); tr["foot"] = (_ax0, _ay0); tr["miss"] = 0; tr["score"] = _sc0""",
"""                tr["last"] = (_ax0, _ay0); tr["foot"] = (_ax0, _ay0); tr["miss"] = 0; tr["score"] = _sc0; tr["last_t"] = time.time() * 1000"""))

# ---------- C3 硬闸速度归一化 ----------
PATCHES.append(("C3-速度闸",
"""            # 大跳变硬闸(用户2026-09-20根治坐标帧间拽飞→B误判cross锁空梯;实测误匹配把人783,515一帧拽到505,302=284px):
            # 任何定位源、任何帧(局部/全图)、无论分数多高(含≥0.75强匹配),相对上一稳定基点一帧位移>ROLE_BIGJUMP_PX一律不采信、continue转黑框ROI重搜;
            # 正常跑步一帧远<120;真瞬移(≥250)由_research_anchor_around_dot以黑框光点(独立第二源)在新位置ROI内重捕,硬拦不影响真瞬移。
            if last is not None and np.hypot(_bx - last[0], _by - last[1]) > ROLE_BIGJUMP_PX:
                continue""",
"""            # 帧间跳变速度闸(用户2026-09-22根治:忙档提到30fps后固定px阈值相对变松,改为按帧间隔dt归一化的速度判据):
            # 任何定位源、任何帧(局部/全图)、无论分多高,相对上一可信基点的位移速度超ROLE_MAX_SPEED_PX_S一律不采信、continue转黑框ROI重搜。
            # 30fps下真实跑步/下落/爬梯是连续小步(<60px/帧),误匹配到同名文本是瞬时跳到另一固定文本(实测70~236px=2100~7000px/s)必被拦;
            # 阈值夹[FLOOR60,CAP150]:高帧战斗≈60px、低帧卡顿≤150px(超大跳变不直接放行);真瞬移(≥250)同样被拦后由_research_anchor_around_dot
            # 借黑框光点(独立第二源)在新位置ROI重捕,硬拦不影响真瞬移。V_MAX=1800px/s是旧120px@约67ms反推的保守初值,真机按[跳变拦截]日志复核再标定。
            if last is not None:
                _dtm = now - tr.get("last_t", 0.0)
                if _dtm <= 0.0:
                    _dtm = 1000.0 / 30.0   # 无上一帧时间戳/同帧重入:按忙档30fps标称间隔,阈值落到FLOOR附近
                _disp_lim = min(ROLE_BIGJUMP_CAP_PX,
                                max(ROLE_BIGJUMP_FLOOR_PX, ROLE_MAX_SPEED_PX_S * _dtm / 1000.0))
                _jd = float(np.hypot(_bx - last[0], _by - last[1]))
                if _jd > _disp_lim:
                    if now - getattr(self, '_bigjump_log_t', 0.0) > 500.0:
                        self._bigjump_log_t = now
                        _debug_log("[角色跟踪] 跳变拦截 d=%.0fpx 限%.0fpx dt=%.0fms v=%.0fpx/s 源=%s(超速度闸转黑框重捕)" % (
                            _jd, _disp_lim, _dtm, _jd / max(_dtm, 1.0) * 1000.0, _pk))
                    continue"""))

# ---------- C4 正常采信 last_t ----------
PATCHES.append(("C4-正常采信last_t",
"""            tr["last"] = (ax, ay)
            tr["foot"] = (ax, ay)  # 单平台只看X,不做到脚补偿
            tr["miss"] = 0; tr["score"] = ps""",
"""            tr["last"] = (ax, ay)
            tr["foot"] = (ax, ay)  # 单平台只看X,不做到脚补偿
            tr["miss"] = 0; tr["score"] = ps; tr["last_t"] = now"""))

# ---------- C5 黑框采信 last_t ----------
PATCHES.append(("C5-黑框采信last_t",
"""            tr["last"] = (_ax2, _ay2); tr["foot"] = (_ax2, _ay2); tr["miss"] = 0; tr["score"] = _sc2""",
"""            tr["last"] = (_ax2, _ay2); tr["foot"] = (_ax2, _ay2); tr["miss"] = 0; tr["score"] = _sc2; tr["last_t"] = now"""))

# ===== 校验 =====
fails = []
for name, old, new in PATCHES:
    c = raw.count(old)
    print("%-22s count=%d %s" % (name, c, "OK" if c == 1 else "*** FAIL ***"))
    if c != 1:
        fails.append((name, c))

# 旧字段/旧常量残留检查(替换后应为0;last_player_pos在替换后应彻底消失)
apply = "--apply" in sys.argv
if fails:
    print("\n锚点校验失败,不写盘。失败项:", fails)
    sys.exit(3)

if not apply:
    print("\nDRY-RUN 全部锚点唯一命中,加 --apply 写盘。")
    sys.exit(0)

for name, old, new in PATCHES:
    raw = raw.replace(old, new, 1)

# 写盘后残留自检
for token in ("last_player_pos", "_last_smooth_dot", "ROLE_BIGJUMP_PX", "_PERSON_BUSY_MAX_MS"):
    n = raw.count(token)
    print("残留检查 %-22s %d" % (token, n))

out = raw.replace("\n", "\r\n")
io.open(P, "w", encoding="utf-8-sig", newline="").write(out)
print("\n已写盘:", P)
