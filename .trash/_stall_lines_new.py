# -*- coding: utf-8 -*-
# 哨兵分行版新方法区(由 _apply_stall_lines.py 拼接进主文件,拼完即删)
    def _wd_stall_dispatch(self, now, intents, mmp, in_gate):
        """哨兵分发器(用户2026-09-28分行定稿):同一监管线程100ms节拍内,先推进独占行状态机,
        空闲时逐行检测(每行独立判定条件,任一行触发即独占,其余行冻结到收尾——行间绝不并行抢键)。"""
        # 先推进正在独占的行(纠偏进行中,其余行不检测)
        self._wd_stall_tick(now)
        if self._stall_active is not None:
            return
        if in_gate:
            return   # 跳后静默窗(镜头抖)所有行都不判,防误判
        if mmp is None:
            for ln in self._stall_lines.values():
                ln['track'] = None   # 光点丢失:各行基点全清(不冤枉),找回后重记
            return
        # 行1 卡梯(仅climbing;卡梯横跳后避让窗内冻结本行)
        self._stall_line_ladder(now, intents, mmp)
        if self._stall_active is not None:
            return
        # 行2 走路(X意图按住即判,不限状态)
        self._stall_line_walk(now, intents, mmp)
        if self._stall_active is not None:
            return
        # 行3 瞬移(零侵入读_combat_tp_pending)
        self._stall_line_tp(now, mmp)
        if self._stall_active is not None:
            return
        # 行4 锁怪(有怪不锁/锁了不打;不依赖光点位置,依赖怪表/锁状态)
        self._stall_line_lock(now)

    def _stall_slide_or_fire(self, line_key, mmp, now, limit_ms, cond_msg, spec):
        """行的公共骨架(仅行1/行2用):光点朝预期方向动过(MOVE_MIN_MAP_DX)就滑基准重计时;超limit_ms没动=触发。
        行专属差异全在spec(kind/axis/dir/vk/jump_key/steps)。track由各行独立持有,行间互不清对方的基点。"""
        ln = self._stall_lines[line_key]
        dirn = spec['dir']
        key_axis = spec['axis']
        tr = ln['track']
        if tr is None or tr.get('dir') != dirn:
            ln['track'] = {'t': now, 'bx': float(mmp[0]), 'by': float(mmp[1]), 'dir': dirn}
            return
        _prog = ((mmp[0] - tr['bx']) * dirn) if key_axis == 'x' else ((mmp[1] - tr['by']) * dirn)
        if _prog >= MOVE_MIN_MAP_DX:
            tr.update(t=now, bx=float(mmp[0]), by=float(mmp[1]))   # 真在动:滑基准重计时
            return
        if now - tr['t'] < limit_ms:
            return
        tr.update(t=now, bx=float(mmp[0]), by=float(mmp[1]))   # 滑基准防同一基点重复触发
        if STALL_SENTINEL_OBSERVE:
            _debug_log("[哨兵·观察][%s] %s 触发[观察模式不动键]" % (line_key, cond_msg))
            return
        # 恢复模式:统一纪律——关锁清锁→关主线→该行独占纠偏
        self._stall_enter(line_key, spec, mmp, now)

    def _stall_line_ladder(self, now, intents, mmp):
        """行1·卡梯(独立判定,与卡梯横跳的后脑判定互补):climbing中Y意图按住≥MOVE_KEY_MIN_MS且
        光点Y没动超STALL_CLIMB_MS。专属解法=重按爬键两试(梯上不跳不横跳——横跳归现有卡梯后脑行管);仍卡=清爬梯状态冷却回主线。"""
        ln = self._stall_lines['ladder']
        if getattr(self, '_climb_state', 'none') != 'climbing' \
                or now - getattr(self, '_ladder_jump_last_t', 0) < STALL_LADDER_JUMP_EVADE_MS:
            ln['track'] = None   # 不在climbing/横跳避让窗:基点清空(下次进climbing重记)
            return
        _it_y = intents.get('y')
        if not _it_y or now - int(_it_y.get('start_t', 0) or 0) < MOVE_KEY_MIN_MS:
            ln['track'] = None
            return
        _dirn = int(_it_y.get('dir') or -1)   # Y轴小地图上为负:向上爬dir=-1
        self._stall_slide_or_fire('ladder', mmp, now, STALL_CLIMB_MS,
                                  '按住爬键光点Y %.0fms没动' % STALL_CLIMB_MS,
                                  dict(kind='卡梯', axis='y', dir=_dirn, vk=VK_UP if _dirn < 0 else VK_DOWN,
                                       jump_key='', steps=('retry', 'retry')))

    def _stall_line_walk(self, now, intents, mmp):
        """行2·走路(独立判定):X意图按住且光点没朝意图方向动超STALL_WALK_MS。
        专属解法(用户定)=重按方向+跳→观察;跳了没用→反向走STALL_WALK_BACK_MS→观察;仍不动=放弃本段回主线重选。"""
        ln = self._stall_lines['walk']
        _it_x = intents.get('x')
        if not _it_x or now - int(_it_x.get('start_t', 0) or 0) < MOVE_KEY_MIN_MS:
            ln['track'] = None
            return
        _dirn = int(_it_x.get('dir') or 1)
        _jk = self._get_fight_config().get('jump_key', '')
        self._stall_slide_or_fire('walk', mmp, now, STALL_WALK_MS,
                                  '按住朝%s %.0fms光点没动' % ('右' if _dirn > 0 else '左', STALL_WALK_MS),
                                  dict(kind='走路', axis='x', dir=_dirn,
                                       vk=VK_RIGHT if _dirn > 0 else VK_LEFT,
                                       jump_key=_jk, steps=('jump', 'back')))

    def _stall_line_tp(self, now, mmp):
        """行3·瞬移(独立判定,零侵入读_combat_tp_pending):发出STALL_TP_MS光点没朝该轴动=瞬移没生效。
        专属解法=清pending(校验作废+主线850ms节流自然重发)+按原方向走;不重发瞬移(防蓝耗)。"""
        ln = self._stall_lines['tp']
        pen = getattr(self, '_combat_tp_pending', None)
        if pen is None:
            ln['track'] = None
            return
        tr = ln['track']
        _ax = pen.get('axis')
        _dirn = int(pen.get('dir') or 1)
        if tr is None or tr.get('t_ref') != pen.get('t'):
            ln['track'] = {'t_ref': pen.get('t'), 't': now, 'bx': float(mmp[0]), 'by': float(mmp[1]),
                           'dir': _dirn, 'axis': _ax}
            return
        _prog = ((mmp[0] - tr['bx']) * _dirn) if _ax == 'x' else ((mmp[1] - tr['by']) * _dirn)
        if _prog >= MOVE_MIN_MAP_DX:
            tr.update(t=now, bx=float(mmp[0]), by=float(mmp[1]))
            return
        if now - tr['t'] < STALL_TP_MS:
            return
        tr.update(t=now, bx=float(mmp[0]), by=float(mmp[1]))
        _dn = ('右' if _dirn > 0 else '左') if _ax == 'x' else ('下' if _dirn > 0 else '上')
        if STALL_SENTINEL_OBSERVE:
            _debug_log("[哨兵·观察][tp] 瞬移发出%.0fms光点没朝%s动[观察模式不动键]" % (STALL_TP_MS, _dn))
            return
        self._combat_tp_pending = None   # 清pending:这次校验作废
        self._stall_enter('tp', dict(kind='瞬移', axis=_ax, dir=_dirn,
                                     vk=(VK_RIGHT if _dirn > 0 else VK_LEFT) if _ax == 'x' else (VK_DOWN if _dirn > 0 else VK_UP),
                                     jump_key='', steps=('walk',)), mmp, now)

    def _stall_line_lock(self, now):
        """行4·锁怪(独立判定,用户2026-09-28新增):①寻怪框内有怪≥STALL_LOCK_MS却没锁上=锁怪决策卡死;
        ②B锁开+已锁上≥STALL_LOCK_MS却没出手(_combat_first_strike_time一直不设置)=决策/出包卡死。
        专属解法=关锁清锁再立即重开(B线用一直热着的怪表下一帧立即重锁)。不动移动键不关主线(锁决策问题,重锁即恢复)。"""
        ln = self._stall_lines['lock']
        if not getattr(self, '_random_running', False) or not getattr(self, '_b_lock_enabled', True):
            ln['track'] = None
            return
        _cands = getattr(self, '_b_candidates', None)
        if not _cands:
            ln['track'] = None   # 框内没怪:不判(没怪可锁是正常)
            return
        _locked = getattr(self, '_b_lock', None)
        if _locked is None:
            # 场景①:框内有怪却一直没锁上
            tr = ln['track']
            if tr is None or tr.get('mode') != 'no_lock':
                ln['track'] = {'mode': 'no_lock', 't': now}
                return
            if now - tr['t'] < STALL_LOCK_MS:
                return
            tr['t'] = now
            _kind = '有怪不锁'
        else:
            # 场景②:已锁上却没出手(首次出手时间一直没记)
            _fs = getattr(self, '_combat_first_strike_time', 0)
            if _fs:
                ln['track'] = None   # 出过手=正常打,基点清
                return
            _lt = getattr(self, '_b_lock_time', 0)
            if not _lt or now - _lt < STALL_LOCK_MS:
                ln['track'] = None   # 刚锁上还在3秒内=给决策时间,不判
                return
            tr = ln['track']
            if tr is None or tr.get('mode') != 'no_strike':
                ln['track'] = {'mode': 'no_strike', 't': now, 'lock_t': _lt}
                return
            if now - tr['t'] < STALL_LOCK_MS:
                return
            tr['t'] = now
            _kind = '锁了不打'
        if STALL_SENTINEL_OBSERVE:
            _debug_log("[哨兵·观察][lock] %s 持续%.0fms[观察模式不动键]" % (_kind, STALL_LOCK_MS))
            return
        # 专属解法:清锁重锁(维持行动纪律:行动前关锁清锁,行动后开锁)
        _debug_log("[哨兵][lock] %s 触发:清锁重锁" % _kind)
        self._rlog("[哨兵] %s,清锁重锁" % _kind, LOG_RED, log='exception')
        self._set_b_lock_enabled(False, why='哨兵·%s' % _kind)   # 关锁清锁
        self._set_b_lock_enabled(True, why='哨兵·%s·重锁' % _kind)  # 立即重开:B线下一帧用热怪表重锁
        self._stall_fail('lock', now, _kind)   # 记行失败统计(10分钟3次弹窗)

    def _stall_enter(self, line_key, spec, mmp, now):
        """行进入独占纠偏(统一纪律,用户2026-09-28):关锁清锁→关主线→建该行状态机。spec含
        kind/axis/dir/vk/jump_key/steps(该行专属纠偏步骤序列)。"""
        self._stall_active = line_key
        self._stall_lines[line_key]['state'] = {
            'kind': spec['kind'], 'axis': spec['axis'], 'dir': spec['dir'], 'vk': spec['vk'],
            'jump_key': spec.get('jump_key', ''), 'steps': spec['steps'],
            'step_i': 0, 'phase': 'start', 't': now, 'back_vk': None,
            'bx': float(mmp[0]), 'by': float(mmp[1])}
        self._set_b_lock_enabled(False, why='哨兵·%s卡住' % spec['kind'])
        self._stall_hold_main = True
        self._rlog("[哨兵] %s卡住,关锁关主线纠偏" % spec['kind'], LOG_RED, log='exception')

    def _wd_stall_tick(self, now):
        """独占行状态机推进(监管线程,每100ms一拍)。每行专属步骤序列按序执行,每个步骤:
        start(松全部方向键+按该步骤的键)→watch(STALL_RECOVER_WATCH_MS观察光点是否朝意图恢复)→
        恢复=脱困收尾;没动=下一步骤;步骤走完仍没动=放弃本段(记行失败统计)→收尾。全程try自保护。"""
        if self._stall_active is None:
            return
        line_key = self._stall_active
        st = self._stall_lines[line_key]['state']
        if st is None:
            self._stall_finish(why='状态丢失')
            return
        try:
            if not getattr(self, '_random_running', False):
                self._stall_finish(why='停运行')
                return
            mmp = getattr(self, '_player_map_pos', None)
            _steps = st['steps']
            _step = _steps[st['step_i']]
            if st['phase'] == 'start':
                # 松全部方向键(战斗/巡路两套账都松,防主线残留按住与新指令互搏)
                for _vk in (VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT):
                    self._release_combat_key(_vk)
                    if _vk in self._random_move_keys:
                        self._key_up(_vk)
                if _step == 'retry':
                    self._key_down(st['vk'])   # 卡梯:重按爬键(不跳,梯上跳=松梯)
                elif _step == 'jump':
                    self._key_down(st['vk'])   # 走路第一步:重按方向+跳一下
                    if st.get('jump_key'):
                        self._press_game_key(st['jump_key'], duration=120)
                elif _step == 'back':
                    # 走路第二步(用户定):跳了没用→反向走(换反方向键)
                    _back_vk = VK_LEFT if st['vk'] == VK_RIGHT else VK_RIGHT
                    st['back_vk'] = _back_vk
                    self._key_down(_back_vk)
                elif _step == 'walk':
                    self._key_down(st['vk'])   # 瞬移没生效:按原方向走(不重发瞬移防蓝耗)
                st['phase'] = 'watch'
                st['t'] = now
                st['bx'] = float(mmp[0]) if mmp is not None else st['bx']
                st['by'] = float(mmp[1]) if mmp is not None else st['by']
                _debug_log("[哨兵][%s] 纠偏步骤%d/%d(%s),观察%dms" % (
                    line_key, st['step_i'] + 1, len(_steps), _step, STALL_RECOVER_WATCH_MS))
                return
            # watch:满观察窗判这一步有没有恢复
            if now - st['t'] < STALL_RECOVER_WATCH_MS:
                return
            if mmp is not None:
                if _step == 'back':
                    # 反向走:人朝任意方向动起来就算脱困(反向能动=没卡死,是地形挡,主线重选路线)
                    _prog = abs(mmp[0] - st['bx'])
                else:
                    _prog = ((mmp[0] - st['bx']) * st['dir']) if st['axis'] == 'x' \
                        else ((mmp[1] - st['by']) * st['dir'])
                if _prog >= MOVE_MIN_MAP_DX:
                    _debug_log("[哨兵][%s] 纠偏生效(%.1f)=脱困" % (line_key, _prog))
                    self._stall_finish(why='脱困')
                    return
            # 这一步没动:松这一步按的键,进下一步骤或放弃
            self._key_up(st['back_vk'] if (_step == 'back' and st.get('back_vk')) else st['vk'])
            if st['step_i'] + 1 < len(_steps):
                st['step_i'] += 1
                st['phase'] = 'start'
                return
            # 步骤走完仍不动=放弃本段(记行失败统计,10分钟3次弹窗)
            _debug_log("[哨兵][%s] 步骤走完仍不动=放弃,%s回主线重选" % (line_key, st['kind']))
            self._rlog("[哨兵] %s纠偏无效,放弃本段回主线" % st['kind'], LOG_RED, log='exception')
            if st['kind'] == '卡梯':
                self._reset_climb()
                self._climb_fail_pause_until = now + LADDER_FAIL_REENTER_MS   # 爬梯冷却,主线先打边怪
            elif st['kind'] == '瞬移':
                self._combat_tp_pending = None
            self._stall_finish(why='放弃', count_fail=True)
        except Exception as e:
            try:
                _debug_log("[哨兵][%s] 恢复异常:%s(收尾防卡死)" % (line_key, e))
            except Exception:
                pass
            self._stall_finish(why='异常')

    def _stall_finish(self, why='', count_fail=False):
        """行收尾(统一纪律,用户2026-09-28:行动完开锁开主线):松该行纠偏键→撤关主线令→恢复锁怪
        (重锁由B线下一帧用一直热着的怪表立即完成)。count_fail=True时记该行失败统计。"""
        line_key = self._stall_active
        if line_key is not None:
            st = self._stall_lines[line_key]['state']
            if st is not None:
                for _vk in (st['vk'], st.get('back_vk')):
                    if _vk is not None:
                        try:
                            self._key_up(_vk)
                        except Exception:
                            pass
            self._stall_lines[line_key]['state'] = None
            self._stall_active = None
        self._stall_hold_main = False
        if not getattr(self, '_b_lock_enabled', True):
            self._set_b_lock_enabled(True, why='哨兵收尾:%s' % why)
        now = time.time() * 1000
        if count_fail and line_key is not None:
            self._stall_fail(line_key, now, why)

    def _stall_fail(self, line_key, now, why):
        """行失败统计(用户2026-09-28):同一行STALL_ALERT_WINDOW_MS(10分钟)内纠偏失败达STALL_ALERT_MAX(3)次
        =置弹窗令(主循环消费,弹项目风格窗口说明原因;tk弹窗必须主线程,2026-09-03教训)+全量复位(松全部方向键清意图)。"""
        ln = self._stall_lines[line_key]
        ln['fails'].append(now)
        ln['fails'] = [_t for _t in ln['fails'] if now - _t <= STALL_ALERT_WINDOW_MS]
        if len(ln['fails']) < STALL_ALERT_MAX:
            return
        ln['fails'] = []   # 触发后清空,下个10分钟窗重新计
        # 全量复位(该行上层逻辑在反复撞墙)
        for _vk in (VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT):
            try:
                self._release_combat_key(_vk)
                if _vk in self._random_move_keys:
                    self._key_up(_vk)
            except Exception:
                pass
        try:
            self._wd_clear_intent(None)
        except Exception:
            pass
        _reason = {'ladder': '爬梯反复卡住(按爬键光点不动)', 'walk': '走路反复卡住(按方向光点不动)',
                   'tp': '瞬移反复没生效(发出后光点不动)', 'lock': '锁怪反复异常(有怪不锁/锁了不打)'}
        self._stall_alert_msg = ("哨兵报警:%s\n10分钟内已连续%d次纠偏失败。\n已全量复位(松键清意图),请人工观察游戏状态。" % (
            _reason.get(line_key, line_key), STALL_ALERT_MAX))
        self._rlog("[哨兵] %s 10分钟内%d次失败,已置弹窗报警" % (line_key, STALL_ALERT_MAX), LOG_RED, log='exception')
        _debug_log("[哨兵][%s] 弹窗令已置" % line_key)
