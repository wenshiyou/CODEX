# -*- coding: utf-8 -*-
# 影子法下行(替换段2:mm对位+新状态机主体;由拼接脚本合入)
    def _enter_desc_mm_ladder(self, px, py, now_ms):
        """方式二入口(实心台直接跳不下,用户2026-09-28影子法):用小地图光点+录制梯选下行梯,
        mm_to_lad对位(复用_desc_horiz_walk),对齐后进dot_grab压↓200ms影子判抓住。"""
        self._release_move_conflicts()
        self._desc_grab_realign = 0
        self._desc_side_leap_n = 0
        self._desc_phase = 'mm_to_lad'
        self._desc_phase_t = now_ms
        self._desc_mm_no_pick_t = 0
        _debug_log("[下行·影子法] 转梯子:小地图选下行梯对位")

    def _desc_mm_ladder_tick(self, px, py, now_ms):
        """方式二小地图选梯+对位:选下行梯(梯顶Y差<=LADDER_MM_END_TOL、梯身下通)钉x;对齐<=LADDER_MM_DESC_ALIGN_TOL
        进dot_grab压↓影子判;没到按住朝梯走(_desc_horiz_walk带stall);连续选不到/走不到=放弃回主线。"""
        ld = self._pick_ladder_minimap(getattr(self, 'ladders', None), px, py, -1, None)
        if ld is None:
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            if getattr(self, '_desc_mm_no_pick_t', 0) == 0:
                self._desc_mm_no_pick_t = now_ms
            elif now_ms - self._desc_mm_no_pick_t >= LADDER_MM_NOPICK_TIMEOUT_MS:
                _debug_log("[下行·影子法] 连续%.0fms小地图无下行合格梯,放弃回主线" % LADDER_MM_NOPICK_TIMEOUT_MS)
                self._rlog("小地图找不到下行梯,回主线打怪", LOG_RED, log='exception')
                self._desc_grab_realign = 0; self._desc_side_leap_n = 0; self._desc_drop_try = 1
                self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
                self._reset_climb(); self._decide_climb_fail_action()
            return False
        self._desc_mm_no_pick_t = 0
        self._climb_ladder_x = float(ld['x'])
        self._climb_ladder_y_top = float(ld['y_top'])
        self._climb_ladder_y_bottom = float(ld['y_bottom'])
        dx = float(ld['x']) - float(px)
        if abs(dx) <= LADDER_MM_DESC_ALIGN_TOL:
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            _debug_log("[下行·影子法] 光点对齐梯X(差%.1f<=%d),压↓%dms影子判抓梯" % (
                dx, LADDER_MM_DESC_ALIGN_TOL, DESC_DOT_GRAB_HOLD_MS))
            self._desc_phase = 'dot_grab'   # 影子法:压↓200ms后判down
            self._desc_phase_t = now_ms
            self._desc_base_y = py
            if VK_DOWN not in self._random_move_keys:
                self._key_down(VK_DOWN)
            return False

        def _on_stall():
            _debug_log("[下行·影子法] 小地图走不到梯X,放弃回主线")
            self._rlog("下行走不到梯子,回主线打怪", LOG_RED, log='exception')
            self._desc_grab_realign = 0; self._desc_side_leap_n = 0; self._desc_drop_try = 1
            self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
            self._reset_climb(); self._decide_climb_fail_action()

        self._desc_horiz_walk(float(ld['x']), px, now_ms, _on_stall,
                              "[下行·影子法] 走向梯X连续%dms没靠近,放弃" % DESC_GOTO_STALL_MS)
        return False

    def _descend_step(self, px, py, now_ms):
        """下行状态机(用户2026-09-28影子法定稿·整体重写):全程用光点影子判"向下/静止",不用特征Y不用固定sleep。
        ①direct_drop:压↓100ms→跳→松↓→300ms后影子判:down→dot_fall(still=落地重锁开打);
          没down→再跳一次;两跳都没下去=实心台→转梯子。②mm_to_lad:对齐梯→压↓200ms→影子判down=抓住梯
          →立即横跳(压怪侧100ms+跳)→200ms后查后脑:无后脑=离梯,等影子still落地重锁;有后脑=还挂梯再横跳;
          压↓后没down=梯位没找准→再对齐。px/py=人物小地图坐标。"""
        _jk = self._get_fight_config().get("jump_key", "")
        ph = self._desc_phase

        # ①pre_wait 前置(纪律:进_descend已关锁清锁关主线松键;这里等150ms站稳)
        if ph == 'pre_wait':
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT); self._key_up(VK_DOWN)
            if now_ms - self._desc_phase_t >= 150:
                self._desc_phase = 'direct_drop'
                self._desc_phase_t = now_ms
                self._desc_jump_t = 0
                self._desc_drop_try = 1
                _debug_log("[下行·影子法] 站稳,开始直接下跳(第1次)")
            return False

        # ②direct_drop 直接下跳(不横跳)
        if ph == 'direct_drop':
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            if self._desc_jump_t == 0:
                # 子步1:压↓满100ms→按跳→松↓(用户时序)
                if VK_DOWN not in self._random_move_keys:
                    self._key_down(VK_DOWN)
                if now_ms - self._desc_phase_t >= DESC_DOT_DOWN_HOLD_MS:
                    if _jk:
                        self._press_game_key(_jk, duration=120)
                    if VK_DOWN in self._random_move_keys:
                        self._key_up(VK_DOWN)
                    self._desc_jump_t = now_ms
                    _debug_log("[下行·影子法] ↓压%dms+跳+松↓,等%dms看影子" % (
                        DESC_DOT_DOWN_HOLD_MS, DESC_DOT_CHECK_MS))
            elif now_ms - self._desc_jump_t >= DESC_DOT_CHECK_MS:
                # 子步2:跳后300ms影子判
                _mv = self._dot_moving_state()
                if _mv == 'down':
                    _debug_log("[下行·影子法] 跳后影子=down,下落中,转落地观察")
                    self._desc_phase = 'dot_fall'
                    self._desc_phase_t = now_ms
                elif _mv == 'unknown':
                    pass   # 光点丢失:挂起等下一拍
                else:
                    _n = getattr(self, '_desc_drop_try', 1)
                    if _n < DESC_DOT_MAX_TRY:
                        self._desc_drop_try = _n + 1
                        self._desc_phase_t = now_ms
                        self._desc_jump_t = 0
                        _debug_log("[下行·影子法] 跳后影子=%s(没下去),第%d次再下跳" % (_mv, _n + 1))
                    else:
                        _debug_log("[下行·影子法] 两跳都没下去(影子%s)=实心台,转梯子" % _mv)
                        self._rlog("下跳两次没下去=实心台,转梯子", LOG_RED, log='exception')
                        self._desc_drop_try = 1
                        self._enter_desc_mm_ladder(px, py, now_ms)
            return False

        # ③dot_fall 落地观察(影子still=到底层):不按任何键
        if ph == 'dot_fall':
            self._key_up(VK_DOWN); self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            _mv = self._dot_moving_state()
            if _mv == 'still':
                _debug_log("[下行·影子法] 影子转still=到底层,清锁重锁开打")
                self._rlog("影子法:下跳落地,重锁开打", log='behavior')
                self._desc_drop_try = 1
                self._desc_grab_realign = 0; self._desc_side_leap_n = 0
                self._reset_climb()
                self._reset_lock_after_arrival('影子法下跳落地')
            elif now_ms - self._desc_phase_t > DESC_DOT_FALL_TIMEOUT_MS:
                _debug_log("[下行·影子法] 落地观察%.0fms兜底(影子=%s),按落地收尾" % (DESC_DOT_FALL_TIMEOUT_MS, _mv))
                self._rlog("下跳落地超时兜底,回主线", LOG_RED, log='exception')
                self._desc_drop_try = 1
                self._desc_grab_realign = 0; self._desc_side_leap_n = 0
                self._reset_climb()
                self._reset_lock_after_arrival('影子法下跳超时')
            return False

        # ④mm_to_lad 走到梯位对齐
        if ph == 'mm_to_lad':
            return self._desc_mm_ladder_tick(px, py, now_ms)

        # ⑤dot_grab 梯位压↓200ms→影子判down
        if ph == 'dot_grab':
            if VK_DOWN not in self._random_move_keys:
                self._key_down(VK_DOWN)
            if now_ms - self._desc_phase_t < DESC_DOT_GRAB_HOLD_MS:
                return False
            _mv = self._dot_moving_state()
            if _mv == 'down':
                # 抓住梯子在滑=立即横跳(用户:压左/右100ms后按跳,方向=怪在哪按哪边)
                _t = getattr(self, '_combat_locked_target', None) or getattr(self, '_combat_last_target_pos', None)
                if _t is not None and abs(float(_t[0]) - float(px)) > 1.0:
                    _d = 1 if float(_t[0]) > float(px) else -1
                else:
                    _d = self._pick_desc_side(px, py)   # 无目标参照:避梯选侧
                self._desc_leap_dir = _d
                _svk = VK_RIGHT if _d > 0 else VK_LEFT
                self._key_up(VK_DOWN)
                if _svk not in self._random_move_keys:
                    self._key_down(_svk)
                self._desc_phase = 'dot_leap'
                self._desc_phase_t = now_ms
                self._desc_jumped = False
                self._desc_side_leap_n = getattr(self, '_desc_side_leap_n', 0) + 1
                _debug_log("[下行·影子法] 梯上影子=down,横跳离梯(朝%s,第%d次)" % (
                    '怪侧' if _t is not None else '避梯侧', self._desc_side_leap_n))
            elif _mv == 'unknown':
                pass
            else:
                # 没down=梯位没找准,再对齐一次(上限后放弃)
                _n = getattr(self, '_desc_grab_realign', 0)
                if _n < DESC_DOT_REALIGN_MAX:
                    self._desc_grab_realign = _n + 1
                    self._key_up(VK_DOWN)
                    _debug_log("[下行·影子法] 梯位压↓影子=%s(没抓住),第%d次再对齐" % (_mv, _n + 1))
                    self._desc_phase = 'mm_to_lad'
                    self._desc_phase_t = now_ms
                else:
                    _debug_log("[下行·影子法] 对齐%d次抓不住梯,放弃回主线" % DESC_DOT_REALIGN_MAX)
                    self._rlog("梯位抓不住(%d次),回主线重选" % DESC_DOT_REALIGN_MAX, LOG_RED, log='exception')
                    self._desc_grab_realign = 0; self._desc_side_leap_n = 0; self._desc_drop_try = 1
                    if VK_DOWN in self._random_move_keys:
                        self._key_up(VK_DOWN)
                    self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
                    self._reset_climb()
                    self._decide_climb_fail_action()
            return False

        # ⑥dot_leap 横跳:压方向满100ms→按跳→松方向→200ms后查后脑
        if ph == 'dot_leap':
            _svk = VK_RIGHT if getattr(self, '_desc_leap_dir', 1) > 0 else VK_LEFT
            if not self._desc_jumped:
                if _svk not in self._random_move_keys:
                    self._key_down(_svk)
                if now_ms - self._desc_phase_t >= DESC_DOT_LEAP_SIDE_MS:
                    if _jk:
                        self._press_game_key(_jk, duration=120)
                    self._desc_jumped = True
                    self._desc_phase_t = now_ms
                    self._key_up(VK_LEFT); self._key_up(VK_RIGHT); self._key_up(VK_DOWN)
                    _debug_log("[下行·影子法] 方向%dms+跳离梯,等%dms查后脑" % (
                        DESC_DOT_LEAP_SIDE_MS, DESC_DOT_BACK_CHECK_MS))
            elif now_ms - self._desc_phase_t >= DESC_DOT_BACK_CHECK_MS:
                _bv, _bs = self._back_head_visible()
                if not _bv:
                    _debug_log("[下行·影子法] 横跳后无后脑=离梯下落,等影子still落地")
                    self._desc_phase = 'dot_fall'
                    self._desc_phase_t = now_ms
                elif getattr(self, '_desc_side_leap_n', 0) >= DESC_LAD_LEAP_MAX:
                    _debug_log("[下行·影子法] 横跳%d次仍见后脑(%.2f)=挂梯,放弃回主线" % (
                        self._desc_side_leap_n, _bs))
                    self._rlog("横跳%d次仍挂梯,回主线重锁" % self._desc_side_leap_n, LOG_RED, log='exception')
                    self._desc_grab_realign = 0; self._desc_side_leap_n = 0; self._desc_drop_try = 1
                    self._key_up(VK_LEFT); self._key_up(VK_RIGHT); self._key_up(VK_DOWN)
                    self._reset_climb()
                    self._reset_lock_after_arrival('横跳挂梯放弃')
                else:
                    _debug_log("[下行·影子法] 横跳后仍见后脑(%.2f)=挂梯,回压↓再横跳" % _bs)
                    self._desc_phase = 'dot_grab'   # 再横跳:回压↓等影子down
                    self._desc_phase_t = now_ms
            return False

        # ⑦兜底:未知相位复位(防旧字段/异常相位卡死)
        _debug_log("[下行·影子法] 未知相位%s,复位回主线" % ph)
        self._reset_climb()
        return False
