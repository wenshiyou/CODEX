# -*- coding: utf-8 -*-
"""原子补丁:上梯起跳定位改人工px(分左右),废伺服速度预测/制动自学。
跑跳=离梯子中心多远带速起跳(rj_l/rj_r);直跳=梯子底下还差多少px松方向键靠惯性滑入(vl_l/vl_r)。
随梯子方案 route_xxx_ladder_tpl.json 永久存盘,梯子管理面板4个正数输入框。maple: utf-8-sig/LF。"""
import ast, io, sys

P = "maple_route_ui.py"
with io.open(P, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()

edits = []

# 1) 常量:5个自学常量 -> 人工px默认/clamp
edits.append(("const",
"""LADDER_SERVO_BRAKE_T_DEFAULT = 100  # 松手→人物相对梯真正停住的总延迟初值ms(识别一拍+按键+行走惯性);自适应学习的起点
LADDER_SERVO_BRAKE_T_MIN = 40       # 制动延迟自学下限ms(夹范围防跑飞)
LADDER_SERVO_BRAKE_T_MAX = 260      # 制动延迟自学上限ms
LADDER_SERVO_BRAKE_ALPHA = 0.35     # 制动延迟一阶学习率(每次停稳小步修正,越用越准;只存内存不写盘)
LADDER_SERVO_HIST_MS = 300          # 靠近速度样本窗ms(窗内最早~最新|X差|变化算收敛速率,抗单帧识别抖)
""",
"""LADDER_RUNJUMP_DX_DEFAULT = 68      # 人工·跑跳起跳人梯X差px(离梯子中心多远带水平速度起跳),梯子管理面板分左右可调(用户2026-09-21废自学改人工)
LADDER_RUNJUMP_DX_MIN = 60          # 跑跳目标下限clamp(必须>伺服入口LADDER_RUNJUMP_LO=60,否则跑跳永不触发)
LADDER_VERT_LEAD_DEFAULT = 15       # 人工·直跳提前松键px(走到梯子底下还差这么多px就松方向键,靠惯性滑入中心;分左右可调)
LADDER_VERT_LEAD_MIN = 5            # 直跳提前px下限clamp
LADDER_VERT_LEAD_MAX = 60           # 直跳提前px上限clamp
"""))

# 2) init 加 cfg
edits.append(("init",
"""        self._ladder_templates = []     # [{id,img,width,height}]
""",
"""        self._ladder_templates = []     # [{id,img,width,height}]
        # 人工上梯起跳定位(随梯子方案存盘,正数px,废速度自学;用户2026-09-21):rj=跑跳离梯心多远带速起跳 / vl=直跳还差多远松键滑入
        self._ladder_jump_cfg = {"rj_l": LADDER_RUNJUMP_DX_DEFAULT, "rj_r": LADDER_RUNJUMP_DX_DEFAULT,
                                 "vl_l": LADDER_VERT_LEAD_DEFAULT, "vl_r": LADDER_VERT_LEAD_DEFAULT}
"""))

# 3) _reset_climb 删 hist 字段
edits.append(("reset_hist",
"""        self._ladder_realign_hist = []       # 最近样本[(|X差|,now_ms)]估靠近速度(收敛速率)
""", ""))

# 4) _reset_climb 删 rel_adiff/rel_r + 自学注释,保留 rel_timeout
edits.append(("reset_rel",
"""        self._ladder_realign_rel_adiff = 0.0 # 松手瞬间|X差|(制动延迟自学用)
        self._ladder_realign_rel_r = 0.0     # 松手瞬间靠近速度px/ms(制动延迟自学用)
        self._ladder_realign_rel_timeout = False  # 本次松手是否为approach超时(超时样本不参与制动学习)
        # 注:_ladder_brake_t(制动延迟自学值)不在此复位,跨梯子保留、越用越准;首次访问getattr取LADDER_SERVO_BRAKE_T_DEFAULT
""",
"""        self._ladder_realign_rel_timeout = False  # 本次松手是否为approach超时(仅日志/兜底标记;人工px方案不再自学)
"""))

# 5) realign_jump 入口删 hist=[]
edits.append(("jump_hist",
"""        self._ladder_realign_phase = 'approach'
        self._ladder_realign_hist = []
        self._ladder_realign_corr = 0
""",
"""        self._ladder_realign_phase = 'approach'
        self._ladder_realign_corr = 0
"""))

# 6) realign_jump 入口删 rel 字段 + 日志去制动T
edits.append(("jump_log",
"""        self._ladder_realign_last_spx = None
        self._ladder_realign_rel_adiff = 0.0
        self._ladder_realign_rel_r = 0.0
        self._ladder_realign_rel_timeout = False
        _debug_log("[伺服直跳] 第%d/%d次尝试(原因=%s):按住朝梯连续走→眼手同步提前松手→停稳直跳(制动T=%.0fms)"
                   % (self._ladder_realign_round, LADDER_REALIGN_MAX_ROUNDS, why,
                      getattr(self, '_ladder_brake_t', LADDER_SERVO_BRAKE_T_DEFAULT)))
""",
"""        self._ladder_realign_last_spx = None
        self._ladder_realign_rel_timeout = False
        _debug_log("[伺服直跳] 第%d/%d次尝试(原因=%s):按住朝梯走→离梯心提前%dpx松键滑入→停稳直跳"
                   % (self._ladder_realign_round, LADDER_REALIGN_MAX_ROUNDS, why,
                      int(self._ladder_jump_cfg.get('vl_r', LADDER_VERT_LEAD_DEFAULT))))
"""))

# 7) approach 速度预测整块 -> 人工px提前松键
edits.append(("approach",
"""        if ph == 'approach':
            # 连续闭环(眼手同步):按住dir_vk不抬,每帧用最新|人梯X差|在最近窗内的收敛速率估靠近速度,
            # 按 速度×制动延迟 提前松手(让人靠惯性正好滑到X差≈0)。镜头平移对人梯同向同量,差分里被抵消,r只反映人相对梯靠近。
            _hist = self._ladder_realign_hist
            _hist.append((adiff, now_ms))
            while _hist and now_ms - _hist[0][1] > LADDER_SERVO_HIST_MS:
                _hist.pop(0)
            _r = 0.0
            if len(_hist) >= 2:
                _a0, _t0 = _hist[0]
                _a1, _t1 = _hist[-1]
                _dtn = _t1 - _t0
                if _dtn > 0:
                    _r = max(0.0, (_a0 - _a1) / float(_dtn))   # px/ms,朝梯靠近为正
            _brake_t = getattr(self, '_ladder_brake_t', LADDER_SERVO_BRAKE_T_DEFAULT)
            _brake_px = _r * _brake_t
            _timeout = (now_ms - self._ladder_realign_t) >= LADDER_SERVO_APPROACH_TIMEOUT_MS
            # 松手判据:已进容差;或确在靠近且剩余距离≤制动滑行量+半容差(预测松手正好滑到0);或approach超时(卡死兜底)
            _release = (adiff <= LADDER_REALIGN_TOL) or                        (_r > 0.0 and adiff <= _brake_px + LADDER_REALIGN_TOL * 0.5) or _timeout
            if _release:
                self._ladder_realign_rel_adiff = float(adiff)
                self._ladder_realign_rel_r = _r
                self._ladder_realign_rel_timeout = bool(_timeout and adiff > LADDER_REALIGN_TOL)
                self._realign_release_move()
                self._ladder_realign_phase = 'settle'
                self._ladder_realign_t = now_ms
                self._ladder_realign_ok_frames = 0
                self._ladder_realign_last_spx = spx
                _debug_log("[伺服直跳] 松手进停稳(剩%.1f 靠近%.3fpx/ms 制动%.1fpx T%.0fms%s)"
                           % (adiff, _r, _brake_px, _brake_t, " approach超时" if _timeout else ""))
            else:
                if opp_vk in self._random_move_keys:
                    self._key_up(opp_vk)
                if dir_vk not in self._random_move_keys:
                    self._key_down(dir_vk)
            return False
""",
"""        if ph == 'approach':
            # 人工px提前松键(用户2026-09-21定稿,物理废速度预测/制动自学):按住朝梯方向走,|人梯X差|≤该方向"直跳提前px"
            # 就松方向键,靠惯性滑入中心(settle里dx≤10且人名不滑=停稳原地直跳)。只认距离、不估速度、不乘帧率,左右各一值面板可调。
            _lead = int(self._ladder_jump_cfg.get('vl_r' if diff > 0 else 'vl_l', LADDER_VERT_LEAD_DEFAULT))
            _timeout = (now_ms - self._ladder_realign_t) >= LADDER_SERVO_APPROACH_TIMEOUT_MS
            _release = adiff <= _lead or adiff <= LADDER_REALIGN_TOL or _timeout
            if _release:
                self._ladder_realign_rel_timeout = bool(_timeout and adiff > LADDER_REALIGN_TOL)
                self._realign_release_move()
                self._ladder_realign_phase = 'settle'
                self._ladder_realign_t = now_ms
                self._ladder_realign_ok_frames = 0
                self._ladder_realign_last_spx = spx
                _debug_log("[伺服直跳] 提前%dpx松键进停稳(剩%.1f 梯在%s%s)"
                           % (_lead, adiff, ('右' if diff > 0 else '左'), " approach超时" if _timeout else ""))
            else:
                if opp_vk in self._random_move_keys:
                    self._key_up(opp_vk)
                if dir_vk not in self._random_move_keys:
                    self._key_down(dir_vk)
            return False
"""))

# 8) settle 删自学更新块 + 日志去制动T
edits.append(("settle_selflearn",
"""        if self._ladder_realign_ok_frames >= LADDER_REALIGN_HOLD_FRAMES:
            # 制动延迟自学(仅非超时松手、且松手时确有靠近速度):松手后惯性实际走完(松手残差-停稳残差),反推有效制动时间,一阶滤波夹范围
            if (not self._ladder_realign_rel_timeout) and self._ladder_realign_rel_r > 0.0:
                _moved = max(0.0, self._ladder_realign_rel_adiff - adiff)
                _t_real = _moved / self._ladder_realign_rel_r
                _t_real = min(LADDER_SERVO_BRAKE_T_MAX, max(LADDER_SERVO_BRAKE_T_MIN, _t_real))
                _cur = getattr(self, '_ladder_brake_t', LADDER_SERVO_BRAKE_T_DEFAULT)
                self._ladder_brake_t = _cur + LADDER_SERVO_BRAKE_ALPHA * (_t_real - _cur)
            _jk = self._get_fight_config().get("jump_key", "")
            self._climb_start_y = py    # 起跳前Y=成败基准,起跳后看到后脑/Y变小=抓住接爬梯段
            if _jk:
                self._press_game_key(_jk, duration=120)
            self._ladder_vert_jumped = True
            self._ladder_jump_phase = 'post_jump'
            self._ladder_post_jump_step = 'delay1'
            self._ladder_post_jump_t = now_ms
            self._ladder_realign_phase = None
            _debug_log("[伺服直跳] 停稳达标(X差%.1f≤%d 帧滑%.1f)→原地直跳,跳后判后脑/Y(学到制动T=%.0fms)"
                       % (diff, LADDER_REALIGN_TOL, _slid,
                          getattr(self, '_ladder_brake_t', LADDER_SERVO_BRAKE_T_DEFAULT)))
            return False
""",
"""        if self._ladder_realign_ok_frames >= LADDER_REALIGN_HOLD_FRAMES:
            _jk = self._get_fight_config().get("jump_key", "")
            self._climb_start_y = py    # 起跳前Y=成败基准,起跳后看到后脑/Y变小=抓住接爬梯段
            if _jk:
                self._press_game_key(_jk, duration=120)
            self._ladder_vert_jumped = True
            self._ladder_jump_phase = 'post_jump'
            self._ladder_post_jump_step = 'delay1'
            self._ladder_post_jump_t = now_ms
            self._ladder_realign_phase = None
            _debug_log("[伺服直跳] 停稳达标(X差%.1f≤%d 帧滑%.1f)→原地直跳,跳后判后脑/Y"
                       % (diff, LADDER_REALIGN_TOL, _slid))
            return False
"""))

# 9) settle 回 approach 删 hist=[]
edits.append(("settle_back_hist",
"""                self._ladder_realign_phase = 'approach'
                self._ladder_realign_hist = []
                self._ladder_realign_t = now_ms
                self._ladder_realign_lock_vk = None     # 回approach重定方向(走过头下一帧自动反向)
""",
"""                self._ladder_realign_phase = 'approach'
                self._ladder_realign_t = now_ms
                self._ladder_realign_lock_vk = None     # 回approach重定方向(走过头下一帧自动反向)
"""))

# 10) 跑跳触发:区间 -> 人工分方向目标px
edits.append(("rj_trig",
"""        # 段2:移动中跑跳(用户2026-09-19定稿):屏幕X差[60,75]、朝梯方向键此刻正按住(=带水平速度)、选中白框=移动中起跳;
        # 贴脸X差≈0水平速度为0跳不上,故必须在60-75带速度提前跳(80贴边危险已收窄)。X差≤60不跑跳,由段2.6直接进连续伺服校准直跳。
        _moving_to_lad = _dir_vk in self._random_move_keys
        _rj_trig = (not getattr(self, '_ladder_run_jumped', False)) \\
            and _moving_to_lad \\
            and LADDER_RUNJUMP_LO <= asdx <= LADDER_RUNJUMP_HI \\
            and _merged
""",
"""        # 段2:移动中跑跳(用户2026-09-21改人工px):朝梯方向键正按住(=带水平速度)、选中白框、人梯X差从远降到该方向"跑跳目标px"
        # 即带速起跳(目标分左右,梯子管理面板可调);X差≤60(伺服入口)不再跑跳,由段2.6进人工提前px的伺服直跳。
        _moving_to_lad = _dir_vk in self._random_move_keys
        _rj_dx = int(self._ladder_jump_cfg.get('rj_r' if sdx > 0 else 'rj_l', LADDER_RUNJUMP_DX_DEFAULT))
        _rj_trig = (not getattr(self, '_ladder_run_jumped', False)) \\
            and _moving_to_lad \\
            and LADDER_RUNJUMP_LO < asdx <= _rj_dx \\
            and _merged
"""))

# 11) 跑跳日志两处
edits.append(("rj_dbg",
"""            _debug_log("[爬梯·屏幕·跑跳] 60-75带起跳(梯X=%d 人X=%d 差%.1f):起跳松左右、100ms后按↑、300ms后判Y(基准Y=%.0f)" % (
                tpl_x, spx, sdx, py))
""",
"""            _debug_log("[爬梯·屏幕·跑跳] 目标%dpx实际差%.1f起跳(梯X=%d 人X=%d朝%s):起跳松左右、100ms后按↑、300ms后判Y(基准Y=%.0f)" % (
                _rj_dx, sdx, tpl_x, spx, ('右' if sdx > 0 else '左'), py))
"""))
edits.append(("rj_rlog",
"""            self._rlog("跑跳上梯(60-75带X差%.1f起跳)" % sdx, log='behavior')
""",
"""            self._rlog("跑跳上梯(目标%dpx实际%.1f朝%s)" % (_rj_dx, sdx, ('右' if sdx > 0 else '左')), log='behavior')
"""))

# 12) 辅助 clamp/load 方法(插在 _load_ladder_templates 前)
edits.append(("helpers",
"""    def _load_ladder_templates(self, route_id):
        \"\"\"从方案永久文件加载梯子特征到运行时副本（重开脚本/切换方案/导入都调它）\"\"\"
""",
"""    def _clamp_ladder_jump_cfg(self, j):
        \"\"\"规整人工上梯起跳定位(正数px):rj跑跳离梯心距离(≥伺服入口60)、vl直跳提前松键px(5~60),缺省/非法回默认。\"\"\"
        def _num(v, d, lo, hi):
            try:
                return max(lo, min(hi, int(round(float(v)))))
            except Exception:
                return d
        return {
            "rj_l": _num(j.get("rj_l"), LADDER_RUNJUMP_DX_DEFAULT, LADDER_RUNJUMP_DX_MIN, 200),
            "rj_r": _num(j.get("rj_r"), LADDER_RUNJUMP_DX_DEFAULT, LADDER_RUNJUMP_DX_MIN, 200),
            "vl_l": _num(j.get("vl_l"), LADDER_VERT_LEAD_DEFAULT, LADDER_VERT_LEAD_MIN, LADDER_VERT_LEAD_MAX),
            "vl_r": _num(j.get("vl_r"), LADDER_VERT_LEAD_DEFAULT, LADDER_VERT_LEAD_MIN, LADDER_VERT_LEAD_MAX),
        }

    def _load_ladder_jump_cfg(self, j):
        self._ladder_jump_cfg = self._clamp_ladder_jump_cfg(j or {})

    def _load_ladder_templates(self, route_id):
        \"\"\"从方案永久文件加载梯子特征到运行时副本（重开脚本/切换方案/导入都调它）\"\"\"
"""))

# 13) load 读 jump
edits.append(("load_read",
"""            self._ladder_tpl_sim = float(d.get("sim", LADDER_TPL_DEFAULT_SIM))
""",
"""            self._ladder_tpl_sim = float(d.get("sim", LADDER_TPL_DEFAULT_SIM))
            self._load_ladder_jump_cfg(d.get("jump", {}))
"""))

# 14) save 写 jump
edits.append(("save_write",
"""                json.dump({"templates": out, "count": len(out),
                           "sim": getattr(self, '_ladder_tpl_sim', LADDER_TPL_DEFAULT_SIM)},
                          f, ensure_ascii=False, indent=2)
""",
"""                json.dump({"templates": out, "count": len(out),
                           "sim": getattr(self, '_ladder_tpl_sim', LADDER_TPL_DEFAULT_SIM),
                           "jump": getattr(self, '_ladder_jump_cfg', {})},
                          f, ensure_ascii=False, indent=2)
"""))

# 15) 面板窗口/两栏加高
edits.append(("ui_size",
"""        self._position_window(win, 460, 380)
""",
"""        self._position_window(win, 460, 478)
"""))
edits.append(("ui_left",
"""        left = tk.Frame(win, width=300, height=350)
""",
"""        left = tk.Frame(win, width=300, height=448)
"""))
edits.append(("ui_right",
"""        right = tk.Frame(win, width=150, height=350)
""",
"""        right = tk.Frame(win, width=150, height=448)
"""))

# 16) on_save 读4框
edits.append(("ui_save",
"""        def on_save():
            try:
                self._ladder_tpl_sim = float(sim_entry.get().strip() or LADDER_TPL_DEFAULT_SIM)
            except Exception:
                self._ladder_tpl_sim = LADDER_TPL_DEFAULT_SIM
            self._save_ladder_templates(self.current_route)
            self._add_log("梯子特征已保存到方案%d（共%d套）" % (self.current_route, len(self._ladder_templates)))
            self._close_window("_ladder_feature_window")
""",
"""        def on_save():
            try:
                self._ladder_tpl_sim = float(sim_entry.get().strip() or LADDER_TPL_DEFAULT_SIM)
            except Exception:
                self._ladder_tpl_sim = LADDER_TPL_DEFAULT_SIM
            self._ladder_jump_cfg = self._clamp_ladder_jump_cfg({
                "rj_l": rj_l_e.get(), "rj_r": rj_r_e.get(),
                "vl_l": vl_l_e.get(), "vl_r": vl_r_e.get()})
            self._save_ladder_templates(self.current_route)
            self._add_log("梯子特征已保存到方案%d（共%d套；起跳定位 跑跳左%d/右%d 直跳左%d/右%d）" % (
                self.current_route, len(self._ladder_templates),
                self._ladder_jump_cfg["rj_l"], self._ladder_jump_cfg["rj_r"],
                self._ladder_jump_cfg["vl_l"], self._ladder_jump_cfg["vl_r"]))
            self._close_window("_ladder_feature_window")
"""))

# 17) 底部红框位置加4个输入框
edits.append(("ui_box",
"""        tk.Label(right, text="说明:\\n一个地图录一次\\n随方案导出/导入\\n只在上梯、小地图差≤5时识别\\n只取梯子X对齐起跳",
                 font=("微软雅黑", 8), fg="gray", justify="left", wraplength=135).pack(pady=8, anchor="n")
        win.update()
""",
"""        tk.Label(right, text="说明:\\n一个地图录一次\\n随方案导出/导入\\n只在上梯、小地图差≤5时识别\\n只取梯子X对齐起跳",
                 font=("微软雅黑", 8), fg="gray", justify="left", wraplength=135).pack(pady=(8, 2), anchor="n")
        # 人工上梯起跳定位(用户2026-09-21):跑跳离梯心px / 直跳提前松键px,分左右,正数;随梯子方案存盘
        jf = tk.Frame(right, relief="solid", borderwidth=1)
        jf.pack(fill="x", pady=(0, 2), padx=2)
        tk.Label(jf, text="上梯起跳定位(px正数)", font=("微软雅黑", 8, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=3, pady=(2, 1))
        _jc = getattr(self, '_ladder_jump_cfg', {})
        def _mk_e(r, c, val):
            _e = tk.Entry(jf, width=4, font=("微软雅黑", 8))
            _e.insert(0, str(val)); _e.grid(row=r, column=c, padx=2, pady=1)
            return _e
        tk.Label(jf, text="跑跳", font=("微软雅黑", 8)).grid(row=1, column=0, sticky="e")
        rj_l_e = _mk_e(1, 1, _jc.get("rj_l", LADDER_RUNJUMP_DX_DEFAULT))
        rj_r_e = _mk_e(1, 2, _jc.get("rj_r", LADDER_RUNJUMP_DX_DEFAULT))
        tk.Label(jf, text="直跳", font=("微软雅黑", 8)).grid(row=2, column=0, sticky="e")
        vl_l_e = _mk_e(2, 1, _jc.get("vl_l", LADDER_VERT_LEAD_DEFAULT))
        vl_r_e = _mk_e(2, 2, _jc.get("vl_r", LADDER_VERT_LEAD_DEFAULT))
        tk.Label(jf, text="列: 左 / 右", font=("微软雅黑", 7), fg="gray").grid(
            row=3, column=1, columnspan=2, sticky="w", pady=(0, 2))
        win.update()
"""))

for name, old, new in edits:
    c = s.count(old)
    if c != 1:
        print("FAIL [%s] count=%d (expect 1)" % (name, c))
        sys.exit(1)
    s = s.replace(old, new)

ast.parse(s)
with io.open(P, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
print("JUMPLEAD_OK edits=%d" % len(edits))
