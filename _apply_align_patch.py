# -*- coding: utf-8 -*-
# 梯子末端对位改造:定时fine -> 速度预判制动+末端刹停。每处count必须==1,任一失败不写回。
import io, sys

PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"

NEW_CONST = u'''# === 上行小地图末端对位【速度预判制动+末端刹停】(用户2026-09-26定稿,取代定时自然趋近fine;新旧只留一套) ===
LADDER_MM_ALIGN_ENTRY_DX = 10   # |人梯X差|≤此值进入对位(跑跳窗之上给预判留距离;跑跳跨线仍由goto先判)
LADDER_MM_SPD_WIN_MS = 200      # 估速窗口ms(取窗内首尾光点位移/真实时间,帧率波动免疫)
LADDER_MM_SPD_MIN_DT_MS = 60    # 窗内首尾至少间隔才估速(否则沿用上一速度,防光点量化夹0)
LADDER_MM_BRAKE_LOOP_MS = 70    # 控制环路延迟(截图→决策→发键),算进制动提前量
LADDER_MM_BRAKE_COAST_MS = 180  # 松键后惯性滑行时间初值(按每次结果一阶滤波自学)
LADDER_MM_BRAKE_COAST_ALPHA = 0.30  # 滑行时间自学滤波系数
LADDER_MM_STOP_DX_MAX = 6       # 制动距离clamp上限(防速度异常提前太多松键)
LADDER_MM_SPD_VERY_LOW = 8      # 朝梯速度(px/s)低于此视为几乎静止
LADDER_MM_COAST_TIMEOUT_MS = 400   # 松键滑行最长等待(到点按当前位置settle,不死等)
LADDER_MM_BRAKE_TAP_AD = 0.6    # 末端刹停:|X差|≤此值且帧间仍朝梯动才反向轻点
LADDER_MM_BRAKE_TAP_MS = 60     # 反向轻点刹停时长ms(真机标定)
LADDER_MM_NUDGE_MS = 90         # 停稳后差格的最小点动时长ms(走路约1格,真机标定)
LADDER_MM_NUDGE_MAX_DX = 3      # 停稳|差|≤此值才点动补齐(差太远回approach重走)
LADDER_MM_NUDGE_MAX = 2         # 点动补齐/修正最多次数(超过拉开重来)
LADDER_MM_PULLBACK_DX = 6       # 拉开重来到|X差|≥此值再重新走近
LADDER_MM_PULLBACK_MAX = 2      # 拉开重来大轮上限(超过放弃回主线)
LADDER_MM_PULLBACK_TIMEOUT_MS = 1500  # 拉开移动超时兜底'''

OLD_CONST = u'''LADDER_MM_FINE_DX = 5           # |X差|<5进自然趋近(跑跳窗5~6以下):短按+松+滑行对位,不按住冲(用户2026-09-26)
LADDER_MM_FINE_MOVE_MIN_MS = 60 # 自然趋近单拍按住下限ms(越近越轻)
LADDER_MM_FINE_MOVE_MAX_MS = 110# 单拍按住上限ms(ad≈5)
LADDER_MM_FINE_MOVE_SLOPE = 22  # 按住时长随ad增长系数ms/小地图单位
LADDER_MM_FINE_MOVE_BASE_MS = 30# 按住时长基数ms:move_ms=clamp(MIN,int(ad*SLOPE)+BASE,MAX)
LADDER_MM_FINE_GAP_MS = 90      # 抬起后滑行/停稳检测时长ms(靠惯性自然滑停,不一顿一顿)
LADDER_MM_FINE_MAX = 3          # 最多几拍仍进不了直跳窗->放弃清锁回主线打怪(不发呆)'''

NEW_FIELDS = u'''        # === 上行小地图末端对位 速度预判制动(用户2026-09-26,取代fine) ===
        self._ladder_mm_align_phase = 'approach'  # 对位相位 approach/coast/brake_tap/nudge/pullback
        self._ladder_mm_align_t = 0               # 当前相位起始时刻ms
        self._ladder_mm_spd_hist = []             # 估速光点采样[(ms,x)]
        self._ladder_mm_speed_v = 0.0             # 最近估出的朝梯速度px/s
        self._ladder_mm_coast_ms = float(LADDER_MM_BRAKE_COAST_MS)  # 滑行时间(自学,同梯重试保留)
        self._ladder_mm_coast_in = None           # 松键瞬间(ad,v)供滑行自学
        self._ladder_mm_brake_done = False        # 本次coast是否已做末端刹停
        self._ladder_mm_coast_still = 0           # coast滑行连续停稳帧
        self._ladder_mm_nudge_count = 0           # 点动补齐/修正次数
        self._ladder_mm_pullback_round = 0        # 拉开重来大轮次数'''

OLD_FIELDS = u'''        self._ladder_mm_fine_phase = ''      # 小地图微调相位 ''/move/gap(用户2026-09-21)
        self._ladder_mm_fine_t = 0           # 微调当前拍起始时刻ms
        self._ladder_mm_fine_round = 0       # 微调已走拍数(最多LADDER_MM_FINE_MAX)'''

NEW_FUNCS = u'''    def _ladder_mm_estimate_speed(self, dir_sign, px, now_ms):
        """估朝梯速度(小地图px/秒,帧率免疫):维护最近SPD_WIN_MS光点采样,取窗内首尾朝梯位移/真实时间。
        窗内时间不足MIN_DT沿用上一值(防光点量化夹0算出0或尖峰)。"""
        _hist = getattr(self, '_ladder_mm_spd_hist', None)
        if _hist is None:
            _hist = []; self._ladder_mm_spd_hist = _hist
        _hist.append((now_ms, float(px)))
        while _hist and now_ms - _hist[0][0] > LADDER_MM_SPD_WIN_MS:
            _hist.pop(0)
        if len(_hist) >= 2:
            _t0, _x0 = _hist[0]; _t1, _x1 = _hist[-1]
            _dt = _t1 - _t0
            if _dt >= LADDER_MM_SPD_MIN_DT_MS:
                _dx = float(dir_sign) * (_x1 - _x0)   # 朝梯为正
                self._ladder_mm_speed_v = max(0.0, _dx / _dt * 1000.0)
        return float(getattr(self, '_ladder_mm_speed_v', 0.0))

    def _ladder_mm_align_reset(self):
        """对位末端收口(同梯重试/拉开后重走):清相位/速度历史/点动计数/刹停标志;滑行自学值与大轮保留。"""
        self._ladder_mm_align_phase = 'approach'
        self._ladder_mm_align_t = 0
        self._ladder_mm_spd_hist = []
        self._ladder_mm_speed_v = 0.0
        self._ladder_mm_brake_done = False
        self._ladder_mm_coast_still = 0
        self._ladder_mm_nudge_count = 0
        self._ladder_mm_coast_in = None

    def _ladder_mm_align_settle(self, d, ad, dir_sign, vl, now_ms):
        """coast停稳/超时后按当前位置收口:先做滑行时间自学→对齐成功回goto / 差格点动 / 走过头反向点动 / 多次不齐拉开。
        返回False(对齐成功时清align相位,goto直跳判据ad≤vl停稳下一帧自然触发)。"""
        _cin = getattr(self, '_ladder_mm_coast_in', None)
        if _cin is not None:
            _ad_in, _v_in = _cin
            _coast_dx = max(0.0, float(_ad_in) - float(ad))   # 朝梯实际滑行距离
            if _v_in >= LADDER_MM_SPD_VERY_LOW and _coast_dx > 0.05:
                _t_obs = max(40.0, min(500.0, _coast_dx / _v_in * 1000.0))
                self._ladder_mm_coast_ms = (self._ladder_mm_coast_ms * (1.0 - LADDER_MM_BRAKE_COAST_ALPHA)
                                            + _t_obs * LADDER_MM_BRAKE_COAST_ALPHA)
                _debug_log("[对位·小地图] 滑行自学 入ad=%.2f v=%.0f 实滑%.2f → t_coast=%.0fms" % (
                    _ad_in, _v_in, _coast_dx, self._ladder_mm_coast_ms))
        self._ladder_mm_coast_in = None
        if ad <= max(float(vl), 0.6):
            self._ladder_mm_align_phase = ''   # 对齐成功:回goto,下帧停稳vert直跳
            _debug_log("[对位·小地图] 已对齐 ad=%.2f,回goto停稳直跳" % ad)
            return False
        if self._ladder_mm_nudge_count >= LADDER_MM_NUDGE_MAX:
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            self._ladder_mm_align_phase = 'pullback'; self._ladder_mm_align_t = now_ms
            _debug_log("[对位·小地图] 点动%d次仍不齐(ad=%.2f),拉开重来" % (LADDER_MM_NUDGE_MAX, ad))
            return False
        if ad <= LADDER_MM_NUDGE_MAX_DX:
            _nudge_vk = VK_RIGHT if d > 0 else VK_LEFT   # 走过头d翻号→自动调头
            _nudge_ovk = VK_LEFT if _nudge_vk == VK_RIGHT else VK_RIGHT
            if _nudge_ovk in self._random_move_keys: self._key_up(_nudge_ovk)
            if _nudge_vk not in self._random_move_keys: self._key_down(_nudge_vk)
            self._ladder_mm_nudge_count += 1
            self._ladder_mm_align_phase = 'nudge'; self._ladder_mm_align_t = now_ms
            _debug_log("[对位·小地图] 差%.2f第%d次最小点动%dms补齐" % (
                ad, self._ladder_mm_nudge_count, LADDER_MM_NUDGE_MS))
            return False
        # 差太远(滑行没到位且超过点动带):回approach重新按住走近
        self._ladder_mm_align_phase = 'approach'; self._ladder_mm_align_t = 0
        self._ladder_mm_brake_done = False; self._ladder_mm_coast_still = 0
        return False

    def _ladder_mm_align_tick(self, px, d, ad, vl, py, now_ms, jump_key):
        """末端对位(用户2026-09-26定稿,|X差|≤ALIGN_ENTRY_DX;取代定时fine,纯小地图坐标,不碰屏幕):
        approach=按住朝梯,每帧按实时速度v算制动距离 d_stop=v×(环路延迟+滑行时间),ad≤d_stop立刻松键(正好滑到ad≈0);
        coast=松键滑行:末端ad≤BRAKE_TAP_AD仍帧间朝梯动→反向轻点刹停;连续停稳/超时→settle(滑行时间自学);
        nudge/brake_tap=到时松键回coast;pullback=按住远离梯到ad≥6重新走近(大轮2次),再不行放弃回主线。"""
        ph = getattr(self, '_ladder_mm_align_phase', 'approach')
        dir_sign = getattr(self, '_ladder_mm_dir_sign', None)
        if dir_sign not in (1, -1):
            dir_sign = 1 if d >= 0 else -1
            self._ladder_mm_dir_sign = dir_sign
        vk = VK_RIGHT if dir_sign > 0 else VK_LEFT
        ovk = VK_LEFT if vk == VK_RIGHT else VK_RIGHT

        if ph == 'approach':
            v = self._ladder_mm_estimate_speed(dir_sign, px, now_ms)
            _t_total = LADDER_MM_BRAKE_LOOP_MS + float(self._ladder_mm_coast_ms)
            d_stop = max(0.0, min(float(LADDER_MM_STOP_DX_MAX), v * _t_total / 1000.0))
            if ad <= d_stop or (ad <= vl and v <= LADDER_MM_SPD_VERY_LOW):
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                self._ladder_mm_align_phase = 'coast'; self._ladder_mm_align_t = now_ms
                self._ladder_mm_coast_in = (ad, v); self._ladder_mm_coast_still = 0
                self._ladder_mm_brake_done = False
                _debug_log("[对位·小地图] 预判松键 ad=%.2f v=%.0f d_stop=%.2f(环路%d+滑行%.0f):靠惯性滑入梯底" % (
                    ad, v, d_stop, LADDER_MM_BRAKE_LOOP_MS, self._ladder_mm_coast_ms))
                return False
            if ovk in self._random_move_keys: self._key_up(ovk)
            if vk not in self._random_move_keys: self._key_down(vk)
            return False

        if ph == 'coast':
            _prev_x = getattr(self, '_ladder_mm_prev_px', None)
            _frame_dx = (float(dir_sign) * (px - _prev_x)) if _prev_x is not None else 0.0  # 朝梯为正
            if not self._ladder_mm_brake_done and ad <= LADDER_MM_BRAKE_TAP_AD and _frame_dx > 0:
                if vk in self._random_move_keys: self._key_up(vk)
                if ovk not in self._random_move_keys: self._key_down(ovk)
                self._ladder_mm_brake_done = True
                self._ladder_mm_align_phase = 'brake_tap'; self._ladder_mm_align_t = now_ms
                return False
            if abs(_frame_dx) <= LADDER_MM_STILL_DX:
                self._ladder_mm_coast_still += 1
            else:
                self._ladder_mm_coast_still = 0
            _timeout = now_ms - self._ladder_mm_align_t >= LADDER_MM_COAST_TIMEOUT_MS
            if self._ladder_mm_coast_still >= LADDER_MM_STILL_FRAMES or _timeout:
                return self._ladder_mm_align_settle(d, ad, dir_sign, vl, now_ms)
            return False

        if ph == 'brake_tap':
            if now_ms - self._ladder_mm_align_t >= LADDER_MM_BRAKE_TAP_MS:
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                _debug_log("[对位·小地图] 末端反向刹停%dms完成,settle" % LADDER_MM_BRAKE_TAP_MS)
                return self._ladder_mm_align_settle(d, ad, dir_sign, vl, now_ms)
            return False

        if ph == 'nudge':
            if now_ms - self._ladder_mm_align_t >= LADDER_MM_NUDGE_MS:
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                self._ladder_mm_align_phase = 'coast'; self._ladder_mm_align_t = now_ms
                self._ladder_mm_coast_still = 0
            return False

        if ph == 'pullback':
            _pb_vk = VK_LEFT if d > 0 else VK_RIGHT      # 朝"当前远离梯"方向,走过头也正确
            _pb_ovk = VK_RIGHT if _pb_vk == VK_LEFT else VK_LEFT
            if _pb_ovk in self._random_move_keys: self._key_up(_pb_ovk)
            if _pb_vk not in self._random_move_keys: self._key_down(_pb_vk)
            if ad >= LADDER_MM_PULLBACK_DX:
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                self._ladder_mm_pullback_round += 1
                if self._ladder_mm_pullback_round >= LADDER_MM_PULLBACK_MAX:
                    _debug_log("[对位·小地图] 拉开重来%d轮仍对不齐,放弃回主线打怪" % LADDER_MM_PULLBACK_MAX)
                    self._rlog("小地图对位反复对不齐梯,回主线打怪", LOG_RED, log='exception')
                    self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
                    self._reset_climb(); self._decide_climb_fail_action()
                    return False
                _debug_log("[对位·小地图] 已拉开ad=%.1f,第%d轮重新走近对位" % (ad, self._ladder_mm_pullback_round))
                self._ladder_mm_align_reset()
            elif now_ms - self._ladder_mm_align_t >= LADDER_MM_PULLBACK_TIMEOUT_MS:
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                self._ladder_mm_pullback_round += 1
                self._ladder_mm_align_reset()
            return False
        return False'''

OLD_FUNCS = u'''    def _ladder_natural_move_ms(self, ad):
        """自然趋近单拍按住时长(用户2026-09-26):随人梯|X差|递减,越近越轻;clamp[MIN,MAX]。"""
        _ms = int(ad * LADDER_MM_FINE_MOVE_SLOPE) + LADDER_MM_FINE_MOVE_BASE_MS
        return max(LADDER_MM_FINE_MOVE_MIN_MS, min(LADDER_MM_FINE_MOVE_MAX_MS, _ms))

    def _ladder_mm_fine_tick(self, d, ad, vl, py, now_ms, jump_key):
        """自然趋近(vl<ad<LADDER_MM_FINE_DX=5,跑跳窗以下;用户2026-09-26):像真人减速走近——
        每拍短按朝梯(时长随ad递减:ad≈5按110ms、越近越轻至60ms)→抬键靠惯性滑行GAP_MS→检测,最多FINE_MAX拍;
        vk每拍按当前d重算,走过头(d翻号)自动调头修正;gap后ad<=vl=到位,回goto停稳原地直跳;拍满仍ad>vl=对不齐,放弃回主线(不发呆)。"""
        ph = getattr(self, '_ladder_mm_fine_phase', '')
        vk = VK_RIGHT if d > 0 else VK_LEFT
        ovk = VK_LEFT if vk == VK_RIGHT else VK_RIGHT
        if ph == '':
            self._ladder_mm_fine_phase = 'move'; self._ladder_mm_fine_t = now_ms
            self._ladder_mm_fine_round = 1
            self._ladder_mm_fine_move_ms = self._ladder_natural_move_ms(ad)
            if ovk in self._random_move_keys: self._key_up(ovk)
            if vk not in self._random_move_keys: self._key_down(vk)
            return False
        if ph == 'move':
            if now_ms - self._ladder_mm_fine_t >= self._ladder_mm_fine_move_ms:
                if vk in self._random_move_keys: self._key_up(vk)
                self._ladder_mm_fine_phase = 'gap'; self._ladder_mm_fine_t = now_ms
            return False
        if now_ms - self._ladder_mm_fine_t >= LADDER_MM_FINE_GAP_MS:
            if ad <= vl:
                self._ladder_mm_fine_phase = ''   # 回goto:停稳判据唯一在goto,下帧停稳后vert起跳
                return False
            if self._ladder_mm_fine_round >= LADDER_MM_FINE_MAX:
                _debug_log("[爬梯·小地图] 微调%d拍仍进不了0~%d直跳窗(剩%.1f),放弃回主线打怪" % (
                    LADDER_MM_FINE_MAX, vl, ad))
                self._rlog("小地图微调对不齐梯,回主线打怪", LOG_RED, log='exception')
                if vk in self._random_move_keys: self._key_up(vk)
                self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
                self._reset_climb(); self._decide_climb_fail_action()
                return False
            self._ladder_mm_fine_round += 1
            self._ladder_mm_fine_phase = 'move'; self._ladder_mm_fine_t = now_ms
            self._ladder_mm_fine_move_ms = self._ladder_natural_move_ms(ad)
            if vk not in self._random_move_keys: self._key_down(vk)
        return False'''

NEW_GOTO = u'''        # 朝梯方向只在人还离梯较远(ad>对位入口)时按d符号更新;进对位后保持,冲过梯X不翻向(真走过头由对位settle调头)
        if ad > LADDER_MM_ALIGN_ENTRY_DX:
            self._ladder_mm_dir_sign = 1 if d > 0 else -1
        _dir_sign = getattr(self, '_ladder_mm_dir_sign', None)
        if _dir_sign not in (1, -1):
            _dir_sign = 1 if d >= 0 else -1
        _right = _dir_sign > 0
        rj = int(self._ladder_jump_cfg.get('rj_r' if _right else 'rj_l', LADDER_MM_RUNJUMP_DEFAULT))
        vl = int(self._ladder_jump_cfg.get('vl_r' if _right else 'vl_l', LADDER_MM_VERT_DEFAULT))
        _prev_px = getattr(self, '_ladder_mm_prev_px', None)
        dpx = (px - _prev_px) if _prev_px is not None else 0.0
        approach = float(_dir_sign) * dpx    # >0=朝梯移动(用锁定的靠近方向,不被d=0翻向)
        if approach > 0:
            self._ladder_mm_approach_streak += 1
        elif approach < 0:
            self._ladder_mm_approach_streak = 0
        # approach==0(光点量化0帧/coast)保持累计不清零:真机走路约1px/帧且夹0帧;倒退才清零
        if abs(dpx) <= LADDER_MM_STILL_DX:
            self._ladder_mm_still_frames += 1
        else:
            self._ladder_mm_still_frames = 0
        prev_ad = getattr(self, '_ladder_mm_prev_ad', None)
        # ---- 3) 跑跳:只在跨rj下降沿、连续朝梯那一次(用户2026-09-26;删掉`or ad<=rj`兜底,它曾让ad<=rj全程抢先跑跳、直跳永远到不了) ----
        _cross = (prev_ad is not None and prev_ad > rj and ad <= rj)
        if (not getattr(self, '_ladder_run_jumped', False)
                and self._ladder_mm_approach_streak >= LADDER_MM_APPROACH_FRAMES
                and _cross):
            self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return self._ladder_mm_start_jump('run', d, py, now_ms, jump_key, vx=approach)
        # ---- 4) 直跳:ad<=vl 且连续停稳 ----
        if ad <= vl and self._ladder_mm_still_frames >= LADDER_MM_STILL_FRAMES:
            self._ladder_mm_align_phase = ''
            self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return self._ladder_mm_start_jump('vert', d, py, now_ms, jump_key, vx=approach)
        # ---- 5) 末端对位(速度预判制动+刹停):ad≤对位入口交给align状态机 ----
        if ad <= LADDER_MM_ALIGN_ENTRY_DX:
            self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return self._ladder_mm_align_tick(px, d, ad, vl, py, now_ms, jump_key)
        # ---- 6) walk 持续按住朝梯走 ----
        if self._ladder_mm_align_phase:
            self._ladder_mm_align_phase = ''
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
        self._hold_toward_ladder(d)
        self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
        return False'''

OLD_GOTO = u'''        # 朝梯方向只在人还离梯有距离(ad>微调带)时按d符号更新;进微调/直跳带后保持,冲过梯X(d=0或轻微越线)不翻向
        if ad > LADDER_MM_FINE_DX:
            self._ladder_mm_dir_sign = 1 if d > 0 else -1
        _dir_sign = getattr(self, '_ladder_mm_dir_sign', None)
        if _dir_sign not in (1, -1):
            _dir_sign = 1 if d >= 0 else -1
        _right = _dir_sign > 0
        rj = int(self._ladder_jump_cfg.get('rj_r' if _right else 'rj_l', LADDER_MM_RUNJUMP_DEFAULT))
        vl = int(self._ladder_jump_cfg.get('vl_r' if _right else 'vl_l', LADDER_MM_VERT_DEFAULT))
        _prev_px = getattr(self, '_ladder_mm_prev_px', None)
        dpx = (px - _prev_px) if _prev_px is not None else 0.0
        approach = float(_dir_sign) * dpx    # >0=朝梯移动(用锁定的靠近方向,不被d=0翻向)
        if approach > 0:
            self._ladder_mm_approach_streak += 1
        elif approach < 0:
            self._ladder_mm_approach_streak = 0
        # approach==0(光点量化0帧/coast)保持累计不清零:真机走路约1px/帧且夹0帧,连续硬判把跨7线跑跳拖到ad≈2(真机实证);倒退才清零,静止光点正负抖动仍凑不齐
        if abs(dpx) <= LADDER_MM_STILL_DX:
            self._ladder_mm_still_frames += 1
        else:
            self._ladder_mm_still_frames = 0
        prev_ad = getattr(self, '_ladder_mm_prev_ad', None)
        # ---- 3) 跑跳:只在跨rj下降沿、且落在5~rj带、连续朝梯那一次(用户2026-09-26;删掉`or ad<=rj`兜底,
        #      它曾让ad<=rj全程抢先跑跳、直跳永远到不了);ad<5即使没跳也不再跑跳,落自然趋近走近对位走直跳 ----
        _cross = (prev_ad is not None and prev_ad > rj and ad <= rj)
        if (not getattr(self, '_ladder_run_jumped', False)
                and self._ladder_mm_approach_streak >= LADDER_MM_APPROACH_FRAMES
                and _cross and ad >= LADDER_MM_FINE_DX):
            self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return self._ladder_mm_start_jump('run', d, py, now_ms, jump_key, vx=approach)
        # ---- 4) 直跳:ad<=vl 且连续停稳 ----
        if ad <= vl and self._ladder_mm_still_frames >= LADDER_MM_STILL_FRAMES:
            self._ladder_mm_fine_phase = ''
            self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return self._ladder_mm_start_jump('vert', d, py, now_ms, jump_key, vx=approach)
        band = self._ladder_mm_band(ad, rj, vl)
        if band == 'fine':
            self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return self._ladder_mm_fine_tick(d, ad, vl, py, now_ms, jump_key)
        if ad <= vl:
            # 进了直跳距离但还在滑(高速冲到正下)/停稳帧不足:松键等停,不零速原地跳
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return False
        if self._ladder_mm_fine_phase:
            self._ladder_mm_fine_phase = ''
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
        # ---- 5) walk 持续按住朝梯走 ----
        self._hold_toward_ladder(d)
        self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
        return False'''

OLD_REALIGN_RST = u'''        self._ladder_post_jump_step = None
        self._ladder_mm_fine_phase = ''
        self._ladder_mm_fine_t = 0
        self._ladder_mm_fine_round = 0
        # 同梯重试:锁id保留,只重置速度/停稳基线与候选(候选对齐到已锁id),不重选梯'''
NEW_REALIGN_RST = u'''        self._ladder_post_jump_step = None
        self._ladder_mm_align_reset()
        # 同梯重试:锁id保留,只重置对位/速度/停稳基线与候选(候选对齐到已锁id),不重选梯'''

OLD_CLIMB_RST = u'''        self._ladder_jump_phase = 'mm_goto'   # 小地图选梯/对位中(post_jump=起跳后看后脑)
        self._ladder_mm_fine_phase = ''
        self._ladder_mm_fine_t = 0
        self._ladder_mm_fine_round = 0
        self._ladder_mm_no_pick_t = 0'''
NEW_CLIMB_RST = u'''        self._ladder_jump_phase = 'mm_goto'   # 小地图选梯/对位中(post_jump=起跳后看后脑)
        self._ladder_mm_align_reset()
        self._ladder_mm_pullback_round = 0
        self._ladder_mm_coast_ms = float(LADDER_MM_BRAKE_COAST_MS)
        self._ladder_mm_no_pick_t = 0'''

OLD_BAND = u'''    def _ladder_mm_band(ad, rj, vl):
        """上行小地图人梯|X差|静态分带(只分三档;带速跑跳由goto按"跨rj下降沿+朝梯速度"单独触发,不在此):
        ad<=vl=vert原地直跳;vl<ad<=FINE_DX=fine微调点动;其余=walk持续按住朝梯走(旧far/near同动作合并)。"""
        if ad <= vl:
            return 'vert'
        if ad <= LADDER_MM_FINE_DX:
            return 'fine'
        return 'walk'
'''

REPLACEMENTS = [
    ("const", OLD_CONST, NEW_CONST),
    ("fields", OLD_FIELDS, NEW_FIELDS),
    ("funcs", OLD_FUNCS, NEW_FUNCS),
    ("goto", OLD_GOTO, NEW_GOTO),
    ("realign_rst", OLD_REALIGN_RST, NEW_REALIGN_RST),
    ("climb_rst", OLD_CLIMB_RST, NEW_CLIMB_RST),
    ("band", OLD_BAND, u""),
]

with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    content = f.read()

# 预检:旧符号计数
for name, old, new in REPLACEMENTS:
    c = content.count(old)
    if c != 1:
        print("[FAIL] %s count=%d (expect 1) -> abort, no write" % (name, c))
        sys.exit(1)

for name, old, new in REPLACEMENTS:
    content = content.replace(old, new, 1)
    print("[OK] %s applied" % name)

with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("ALL DONE, file written")
