# -*- coding: utf-8 -*-
"""阶段二 锁怪权移交B线程 施工脚本(一次性)。
全部替换先在内存做并断言计数,任一失败不写回,保证可反复重跑不污染文件。
maple_route_ui.py = UTF-8 BOM + LF。"""
import io, sys

PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, 'r', encoding='utf-8-sig', newline='') as f:
    text = f.read()

REP = []   # (desc, old, new, expected_count)
CUT = []   # (desc, start_marker, end_marker(保留), new_text)

# ============ 1. __init__ 删除 slope_high_blocked ============
REP.append(("del slope_high_blocked field",
'''        self._slope_high_mode = False              # 当前锁定目标是否处于"高坡走-跳-打"模式(用于区分高坡打空vs普通空怪)
        self._slope_high_blocked = False           # 当前锁定目标跳打已打空(无血条无伤害=够不着)→降级:本次让它落cross走梯子/瞬移，换目标清除
''',
'''        self._slope_high_mode = False              # 跳高打动作状态机(留主线);打空=普通空怪换一只,绝不降级cross(能不能打到只看面板跳高带)
''', 1))

# ============ 2. __init__ 备胎包字段 -> 决策包/反馈/B锁生命周期 ============
REP.append(("init decision/feedback/b_lock fields",
'''        self._combat_intent_packet = None   # 【阶段一】B线程原子发布的预备怪next {next,next_tier,t,group,cross_candidates};current一死主线同帧晋升,0等待
        self._b_next_anchor = None          # B私有备胎锚点(cx,cy,tier):in-range钉身份、坐标每帧随框刷新,out/cross每帧可换;只B写主线只读
''',
'''        self._combat_decision_packet = None  # 【阶段二】B线程原子发布的权威锁怪决策包(target/state/dist/drop/next...),锁怪唯一脑子;主线只读镜像、只执行
        self._combat_exec_feedback = None    # 【阶段二】主线→B出手反馈{'pos':(x,y),'first':ms,'t':ms};B据此+血条/伤害判空怪,绝不靠主线选怪
        self._b_lock = None                  # B私有:当前锁定怪(cx,cy),跨帧维持(B唯一写)
        self._b_lock_tier = None             # B私有:锁定类别 in/out/cross
        self._b_hp_confirmed = False         # B私有:当前锁是否已见血条
        self._b_gone = 0                     # B私有:连续无血条帧
        self._b_lock_time = 0                # B私有:当前锁锁定时刻ms
        self._b_probe_side = random.choice([-1, 1])   # B私有:左右探测侧(决策归B)
        self._b_probe_switched = False
''', 1))

# ============ 3. 伤害检测函数:支持B传入frame/monsters(B不自行截图) ============
REP.append(("damage fn signature",
"    def _detect_damage_number(self, target_cx, target_cy):",
"    def _detect_damage_number(self, target_cx, target_cy, frame=None, monsters=None):", 1))
REP.append(("damage fn monster source",
'''        for (x1, y1, x2, y2, _) in self._monsters:
            cx = (x1 + x2) // 2  # 怪物中心X''',
'''        for (x1, y1, x2, y2, _) in (monsters if monsters is not None else self._monsters):
            cx = (x1 + x2) // 2  # 怪物中心X''', 1))
REP.append(("damage fn frame source",
'''        # 步骤2：截取游戏画面，在目标头顶上方区域搜索
        # 2026-09-07 CPU优化·截图共用：优先复用检测线程最新帧(战斗时250ms一帧,够用)，超龄才补截
        _rf = getattr(self, '_raw_frame', None)
        _rft = getattr(self, '_raw_frame_t', 0)
        if _rf is not None and (time.time() - _rft) <= 0.6:
            frame = _rf
        else:
            frame = self._capture_window()
        if frame is None:
            return False''',
'''        # 步骤2：在目标头顶上方区域搜索。B线程调用必须传入本检测帧frame(禁止B自行截图抢capture线程);
        # 主线兼容旧路径:未传frame时才复用_raw_frame、超龄补截
        if frame is None:
            _rf = getattr(self, '_raw_frame', None)
            _rft = getattr(self, '_raw_frame_t', 0)
            if _rf is not None and (time.time() - _rft) <= 0.6:
                frame = _rf
            else:
                frame = self._capture_window()
        if frame is None:
            return False''', 1))

# ============ 4. 空怪拉黑 3秒 -> 1秒 ============
REP.append(("phantom docstring 1s",
"        ①最近被判定空怪/已放弃位置±60px内的怪(打一下无血条无伤害→drop,3秒不重锁)；",
"        ①最近被判定空怪/已放弃位置±60px内的怪(打一下无血条无伤害→drop,1秒不重锁,用户2026-09-18)；", 1))
REP.append(("phantom ttl 1000",
'''        # 只保留近3秒内的空怪记录
        self._combat_dropped_phantoms = [(cx, cy, t) for (cx, cy, t) in self._combat_dropped_phantoms
                                         if now_ms - t < 3000]''',
'''        # 只保留近1秒内的空怪记录(用户2026-09-18:空怪拉黑1秒就换下一只,不蹲5秒)
        self._combat_dropped_phantoms = [(cx, cy, t) for (cx, cy, t) in self._combat_dropped_phantoms
                                         if now_ms - t < 1000]''', 1))

# ============ 5. 新增 B只读过滤(空怪黑名单+压制侧),不清理不append ============
REP.append(("insert readonly phantom filter",
'''            if not near and not side_blocked:
                out.append((x1, y1, x2, y2, score))
        return out

    def _merge_detections(self, yolo_monsters, feature_monsters):''',
'''            if not near and not side_blocked:
                out.append((x1, y1, x2, y2, score))
        return out

    def _phantom_filter_readonly(self, monsters, px):
        """【阶段二·B线程只读】按当前空怪1秒黑名单+压制侧剔除候选,不清理不append
        (过期清理/写入都归主线_filter,避免两线程同改一个list)。px=人物X(判压制侧左右)。"""
        if not monsters or px is None:
            return monsters
        _now_ms = time.time() * 1000
        _ph = list(self._combat_dropped_phantoms)
        _ss = self._combat_suppress_side
        out = []
        for (x1, y1, x2, y2, score) in monsters:
            cx = (x1 + x2) // 2
            cy = y2
            near = any(abs(cx - dx) <= 60 and abs(cy - dy) <= 60 for (dx, dy, _t) in _ph)
            _side = 'right' if cx >= px else 'left'
            side_blocked = bool(_ss and _now_ms < _ss[1] and _side == _ss[0])
            if not near and not side_blocked:
                out.append((x1, y1, x2, y2, score))
        return out

    def _merge_detections(self, yolo_monsters, feature_monsters):''', 1))

# ============ 6. B线程启动初始化 b_* ============
REP.append(("B loop init b state",
'''        if not hasattr(self, '_yolo_cache'):   # 重活缓存归B私有
            self._yolo_cache, self._yolo_last_t = [], 0.0
            self._feat_cache, self._feat_last_t = [], 0.0
            self._bars_cache, self._bars_last_t = [], 0.0''',
'''        if not hasattr(self, '_yolo_cache'):   # 重活缓存归B私有
            self._yolo_cache, self._yolo_last_t = [], 0.0
            self._feat_cache, self._feat_last_t = [], 0.0
            self._bars_cache, self._bars_last_t = [], 0.0
        # 【阶段二】B线程每次启动:锁怪生命周期/决策包/出手反馈全部归零,杜绝上一轮运行残留
        self._b_lock = None; self._b_lock_tier = None
        self._b_hp_confirmed = False; self._b_gone = 0; self._b_lock_time = 0
        self._b_probe_side = random.choice([-1, 1]); self._b_probe_switched = False
        self._combat_decision_packet = None; self._combat_exec_feedback = None''', 1))

# ============ 7. B循环 关怪扫清空 ============
REP.append(("B scan-off clear decision",
'''                    self._combat_intent_packet = None   # 关怪扫(上梯/下跳)=无怪池,预备next一并清空,主线拿不到任何怪/备胎
                    self._b_next_anchor = None''',
'''                    self._combat_decision_packet = None   # 关怪扫(上梯/下跳)=B不决策,主线拿不到锁,专心爬梯不抢主权
                    self._b_lock = None; self._b_lock_tier = None
                    self._b_hp_confirmed = False; self._b_gone = 0; self._b_lock_time = 0''', 1))

# ============ 8. B循环 YOLO节流锁定源改 b_lock ============
REP.append(("B yolo throttle uses b_lock",
"                    _lk = getattr(self, '_combat_locked_target', None)",
"                    _lk = getattr(self, '_b_lock', None)", 1))

# ============ 9. B循环 决策调用 ============
REP.append(("B loop decision call",
'''                    try:
                        self._publish_combat_intent(_ch, _merged, _metric, _fc)
                    except Exception as _ie:
                        _debug_log("[识别B] 预选怪next异常:%s" % _ie)''',
'''                    # 【阶段二】B线程跑完整锁怪决策(选/维持/判死/同帧重选),原子发布决策包;纯看不发键;关怪扫/上梯精准模式不跑
                    try:
                        self._publish_combat_decision(_ch, _merged, _metric, _fc, _frame, _bars, int(_now_det * 1000))
                    except Exception as _ie:
                        _debug_log("[识别B] 锁怪决策异常:%s" % _ie)''', 1))

# ============ 10. (原except清空REP删除:实际except块本无清intent,保持原行为,异常下轮成功即刷新) ============

# ============ 11. 停止运行 清B决策 ============
REP.append(("stop runtime clear b",
'''        self._recognize_thread = None
        self._stop_move_watchdog()''',
'''        self._recognize_thread = None
        # 【阶段二】停运行:清B锁怪决策/反馈,停止后不残留红框与旧锁
        self._combat_decision_packet = None; self._combat_exec_feedback = None
        self._b_lock = None; self._b_lock_tier = None
        self._b_hp_confirmed = False; self._b_gone = 0; self._b_lock_time = 0
        self._stop_move_watchdog()''', 1))

# ============ 12. 到顶/到新平台 清B锁(强制新层重锁) ============
REP.append(("arrival reset clear b",
'''        self._combat_locked_target = None
        self._combat_last_target_pos = None
        self._clear_locked_ladder('登顶/到新平台')   # 锁定梯到此自然终点,解绑回主线重锁本层怪(用户2026-09-11:到顶就开主线自由发挥)''',
'''        self._combat_locked_target = None
        self._combat_last_target_pos = None
        # 【阶段二】翻层必清B锁怪生命周期+决策包,强制B用新层怪表重锁,杜绝拿旧层坐标又把人拉下去
        self._b_lock = None; self._b_lock_tier = None
        self._b_hp_confirmed = False; self._b_gone = 0; self._b_lock_time = 0
        self._b_probe_side = random.choice([-1, 1]); self._b_probe_switched = False
        self._combat_decision_packet = None; self._combat_exec_feedback = None
        self._clear_locked_ladder('登顶/到新平台')   # 锁定梯到此自然终点,解绑回主线重锁本层怪(用户2026-09-11:到顶就开主线自由发挥)''', 1))

# ============ 13. overlay 黄框读决策包 next ============
REP.append(("overlay next from decision",
'''                    _intent_pkt_o = getattr(self, '_combat_intent_packet', None)
                    self._monster_overlay_data["next_target"] = (_intent_pkt_o['next'] if _intent_pkt_o else None)''',
'''                    _dlpkt_o = getattr(self, '_combat_decision_packet', None)
                    self._monster_overlay_data["next_target"] = (_dlpkt_o.get('next') if _dlpkt_o else None)''', 1))

# ============ 14. 主线:删 slope_blocked/eff_up_band ============
REP.append(("main del slope blocked band",
'''        # 当前锁定目标若跳打已打空(出手无血条无伤害=当前位置够不着)→本次降级：上方分界收回到攻击Y范围，让它落cross走梯子/瞬移；换目标清除
        _slope_blocked = getattr(self, '_slope_high_blocked', False)
        # 上方"可锁定/可接近"分界：启用且未降级=用户上限(区间内走高跳打、不找梯子)；否则=_atk_y_up(旧行为：超出攻击Y范围就cross走梯子)
        _eff_up_band = _sj_max if (_slope_on and not _slope_blocked) else _atk_y_up
''',
'''        # 【阶段二】上方可达分界(跳高带_sjMax/主攻带_atk_y_up)由B决策统一计算;跳高打空=普通空怪换一只,不再降级cross(用户2026-09-18)
''', 1))

# ============ 15. 主线:删 伤害检测/出手反馈/判死 输入段 ============
REP.append(("main del damage/attacked inputs",
'''        _lock_p = self._combat_locked_target
        _lcx, _lcy = (_lock_p if _lock_p else (None, None))
        # 伤害数字只在"停步出手线+Y范围内"的锁定目标上检测（用户2026-09-10：4/5线内才算真能打到,之外继续走近、不判空怪）；
        # 超线(pursue还没走近)不判空怪、也省一次抓帧
        _in_skill = bool(_lock_p) and abs(_lcx - px) <= stop_range and -_atk_y_up <= (_lcy - py_layer) <= _atk_y_down
        _has_dmg = _in_skill and self._detect_damage_number(_lcx, _lcy)
        # 空怪/打死判定：已出手 且 距【首次】出手超过 POST_STRIKE_CHECK_MS(130ms)反馈窗口(用户2026-09-07：250→130,更快判死换怪)。
        # 关键保护：血条/伤害都来自检测线程帧,必须已拿到一帧"出手时刻之后"的新画面(_raw_frame_t≥首次出手)才判,
        # 否则130ms时用的还是出手前旧帧→会把真怪误判成空怪丢掉。没等到新帧就再等一轮,绝不拿旧帧下结论。
        _fs = getattr(self, '_combat_first_strike_time', 0)
        _post_frame = (not _fs) or (getattr(self, '_raw_frame_t', 0) * 1000 >= _fs)
        _attacked = getattr(self, '_combat_target_attacked', False) and _post_frame \\
            and (not _fs or now - _fs > POST_STRIKE_CHECK_MS)
''',
'''        # 【阶段二】伤害数字检测/出手反馈对齐/空怪判死全部搬到B决策线程(_publish_combat_decision),主线不再截图判生死
''', 1))

# ============ 16. 主线:删 16930 重复解target/写locked ============
REP.append(("main del duplicate target unpack",
'''        t_dist, t_cx, t_cy = target
        # 更新锁定位置（怪会移动）
        self._combat_locked_target = (t_cx, t_cy)
        # 记录目标位置，用于下一轮血条搜索
        self._combat_last_target_pos = (t_cx, t_cy)

        # === 存活/空怪 已由 combat_step 处理（血条OR伤害=活；打一下都无=空怪drop）===
        # 不再在这里重复检测血条/伤害，避免重复截图+与combat_step冲突

''',
'', 1))

# ============ 17. 出手反馈(3处) ============
REP.append(("feedback slope hit",
'''                    self._combat_target_attacked = True
                    if not self._combat_first_strike_time:
                        self._combat_first_strike_time = now''',
'''                    self._combat_target_attacked = True
                    if not self._combat_first_strike_time:
                        self._combat_first_strike_time = now
                    self._combat_exec_feedback = {'pos': (t_cx, t_cy), 'first': self._combat_first_strike_time, 't': now}''', 1))
REP.append(("feedback aoe hit",
'''                self._combat_target_attacked = True  # 群攻也算对锁定目标出手：空放无反馈时同样走130ms空怪drop换目标
                if not self._combat_first_strike_time:
                    self._combat_first_strike_time = now
                skill_cast = True''',
'''                self._combat_target_attacked = True  # 群攻也算对锁定目标出手：空放无反馈时同样走130ms空怪drop换目标
                if not self._combat_first_strike_time:
                    self._combat_first_strike_time = now
                self._combat_exec_feedback = {'pos': (t_cx, t_cy), 'first': self._combat_first_strike_time, 't': now}
                skill_cast = True''', 1))
REP.append(("feedback main hit",
'''                self._combat_target_attacked = True  # 已对锁定目标出手：空怪判定用
                self._note_stale_target_attack(t_cx, t_cy, now)  # I纯观测:锁定目标不在当前怪列表(限频5s,不干预)
                if not self._combat_first_strike_time:  # 仅记首次出手，持续攻击不刷新，保证130ms窗口后空怪能被drop
                    self._combat_first_strike_time = now
                skill_cast = True''',
'''                self._combat_target_attacked = True  # 已对锁定目标出手：空怪判定用
                self._note_stale_target_attack(t_cx, t_cy, now)  # I纯观测:锁定目标不在当前怪列表(限频5s,不干预)
                if not self._combat_first_strike_time:  # 仅记首次出手，持续攻击不刷新，保证130ms窗口后空怪能被drop
                    self._combat_first_strike_time = now
                self._combat_exec_feedback = {'pos': (t_cx, t_cy), 'first': self._combat_first_strike_time, 't': now}
                skill_cast = True''', 1))

# ============ CUT A: _publish_combat_intent 整方法 -> _publish_combat_decision ============
NEW_DECISION = '''    def _publish_combat_decision(self, ch, merged, metric, fc, frame, bars, now_ms):
        """【阶段二·B识别线程=锁怪唯一脑子】每检测轮跑完整目标生命周期(选/维持/判死/同帧重选),
        原子写 _combat_decision_packet,主线只读它执行、永不自己选怪。B永不发键;出手事实由主线经
        _combat_exec_feedback 回传,血条/伤害数字由B在本检测帧感知。
        跳高打空(怪在面板跳高带内、出手后无血条无伤)=普通空怪drop、1秒黑名单换一只,绝不降级cross;
        能不能跳高打到只由面板跳高Y范围决定(用户2026-09-18)。"""
        if ch is None or not merged:
            self._b_lock = None
            self._b_lock_tier = None
            self._b_hp_confirmed = False
            self._b_gone = 0
            self._b_lock_time = 0
            self._combat_decision_packet = None
            return
        px, py = ch
        _skr = int(fc.get("atk1_distance", 150) or 150)
        _stop = max(1, int(_skr * 4 // 5))
        _aoe = int(fc.get("aoe_distance", 200) or 200)
        _yup = abs(int(fc.get("attack_y_up", -ATTACK_Y_UP)))
        _ydn = abs(int(fc.get("attack_y_down", ATTACK_Y_DOWN)))
        _ayv_up = fc.get("aoe_y_up"); _ayv_dn = fc.get("aoe_y_down")
        _ayup = abs(int(_ayv_up)) if _ayv_up is not None else None
        _aydn = abs(int(_ayv_dn)) if _ayv_dn is not None else None
        _sjmv = fc.get("slope_jump_y_min"); _sjxv = fc.get("slope_jump_y_max")
        try:
            _sjmin = abs(int(_sjmv)) if _sjmv is not None else None
            _sjmax = abs(int(_sjxv)) if _sjxv is not None else None
        except (TypeError, ValueError):
            _sjmin = _sjmax = None
        _slope_on = (_sjmin is not None and _sjmax is not None and _sjmax >= _sjmin)
        _eff_up = _sjmax if _slope_on else _yup   # 面板跳高带内=cand可跳高打;永不因打空收回(删旧slope_blocked降级)
        _far_x = max(50, int(fc.get("far_range_x", COMBAT_FAR_RANGE) or COMBAT_FAR_RANGE))
        _gp = bool(fc.get("group_priority"))
        _dual = bool(fc.get("aoe_dual"))
        # 空怪1秒黑名单+压制侧:只读过滤候选(清理/append归主线,避免两线程同改list)
        _cand = self._phantom_filter_readonly(list(merged), px)
        # 主线出手反馈→必须与当前b_lock是同一只(±40X/±50Y)才算数,防换目标后旧出手污染新怪
        _bl = self._b_lock
        _fb = getattr(self, '_combat_exec_feedback', None)
        _attacked = False
        if _bl is not None and _fb and _fb.get('pos'):
            _fpos = _fb['pos']
            if abs(_fpos[0] - _bl[0]) <= 40 and abs(_fpos[1] - _bl[1]) <= 50:
                _first = _fb.get('first', 0) or 0
                # 过POST_STRIKE反馈窗才判(本轮处理的帧时间在出手之后=出手后新帧,杜绝拿旧帧误杀真怪)
                if _first and now_ms >= _first and (now_ms - _first) > POST_STRIKE_CHECK_MS:
                    _attacked = True
        # can_strike=锁在停步线+主攻Y带(真打得到);只有成立时才用"无血无伤"判死
        _in_skill = bool(_bl) and abs(_bl[0] - px) <= _stop and -_yup <= (_bl[1] - py) <= _ydn
        _has_dmg = False
        if _in_skill and _attacked:
            try:
                _has_dmg = self._detect_damage_number(_bl[0], _bl[1], frame=frame, monsters=merged)
            except Exception as _e:
                _debug_log("[B决策] 伤害数字检测异常: %s" % _e)
                _has_dmg = False
        _freeze = self._is_lock_frozen()
        _dl = combat_logic.combat_step(
            now_ms, px, py, _cand, self._selected_platforms, _skr, _aoe, _far_x,
            _bl, bars, _has_dmg, True, True,
            self._b_probe_side, self._b_probe_switched,
            self._is_monster_on_platform, self._get_monster_platform,
            self._b_lock_time, self._b_hp_confirmed, self._b_gone, _bl,
            _attacked, _eff_up, _ydn, True, freeze_lock=_freeze,
            group_priority=_gp, group_radius=_aoe,
            aoe_y_up=_ayup, aoe_y_down=_aydn, aoe_dual=_dual,
            can_strike=_in_skill, lock_tier=self._b_lock_tier,
            same_platform_fn=None, metric=metric, fallback_next=None)
        # B锁生命周期回存
        self._b_hp_confirmed = _dl['hp_confirmed']
        self._b_gone = _dl['gone_frames']
        self._b_lock_tier = _dl.get('tier')
        _tgt = _dl.get('target')
        _old = _bl
        _drop = bool(_dl.get('drop'))
        _new_target = False
        if _tgt is None:
            if _old is not None:
                self._b_lock = None; self._b_lock_time = 0
                self._b_hp_confirmed = False; self._b_gone = 0
        else:
            if _old is None or _drop or abs(_tgt[0] - _old[0]) > 40 or abs(_tgt[1] - _old[1]) > 50:
                _new_target = True
                self._b_lock_time = now_ms
                self._b_hp_confirmed = False
                self._b_gone = 0
            self._b_lock = _tgt
        if _dl.get('state') == 'switch':
            self._b_probe_side = -self._b_probe_side
            self._b_probe_switched = True
        # drop当帧催下轮立刻全图重扫(B内部节流自处理,替代旧主线跨线程写_yolo_last_t)
        if _drop:
            self._yolo_last_t = 0.0
            self._bars_last_t = 0.0
        # 备胎next给蒙板黄框(current活着时);current死当帧combat_step已全表重选、0等待接手
        _nxt = None
        if _tgt is not None and not _drop:
            try:
                _nd = combat_logic.pick_next(
                    px, py, list(_cand), self._selected_platforms, _skr,
                    self._get_monster_platform, _eff_up, _ydn, _gp, _aoe,
                    _ayup, _aydn, _dual, True, metric=metric, same_platform_fn=None,
                    exclude=_tgt, cur_cross=_tgt)
                _nxt = _nd.get('target')
            except Exception:
                _nxt = None
        self._combat_decision_packet = {
            'target': _tgt, 'state': _dl.get('state'), 'tier': _dl.get('tier'),
            'dist': _dl.get('dist'), 'cross_candidates': _dl.get('cross_candidates'),
            'group': _dl.get('group'), 'next': _nxt,
            'drop': _drop, 'drop_pos': _dl.get('drop_pos'),
            'new_target': _new_target, 'alive': _dl.get('alive'),
            'hp_confirmed': _dl['hp_confirmed'], 'gone': _dl['gone_frames'],
            'has_dmg': _has_dmg, 'attacked': _attacked, 'in_skill': _in_skill,
            't': time.time()}

'''
CUT.append(("replace publish method",
            "    def _publish_combat_intent(self, ch, merged, metric, fc):",
            "    def _compute_locked_rect(self, lt):", NEW_DECISION))

# ============ CUT B: 主线 combat_step调用段 -> 读决策包+善后+诊断 ============
NEW_READ = '''        # === 【阶段二】锁怪决策(选/维持/判死/同帧重选)由B线程整帧做好,主线只读决策包、只执行 ===
        _dlpkt = getattr(self, '_combat_decision_packet', None)
        if not _dlpkt or not _dlpkt.get('target'):
            # B无锁(无怪/关怪扫):爬梯/瞬移已由上面freeze分支接走,这里按无目标松键,不打不巡、不发呆乱走
            self._combat_active = False
            self._combat_had_target = False
            self._combat_last_target_pos = None
            self._combat_locked_target = None
            if self._combat_transit:
                self._transit_step()
            self._release_combat_move()
            return
        _dl = _dlpkt
        t_cx, t_cy = _dl['target']
        t_dist = int(_dl.get('dist') or 0)
        target = (t_dist, t_cx, t_cy)
        self._combat_locked_target = (t_cx, t_cy)
        self._combat_last_target_pos = (t_cx, t_cy)
        # --- drop善后(动作层):B判死,主线把旧坐标拉黑1秒+清出手反馈+上屏;跳高打空也走这(=普通空怪,不降级cross) ---
        if _dl.get('drop'):
            _dpos = _dl.get('drop_pos') or (t_cx, t_cy)
            self._combat_dropped_phantoms.append((_dpos[0], _dpos[1], now))
            self._note_phantom_drop('空怪')
            self._combat_target_attacked = False
            self._combat_first_strike_time = 0
            self._combat_exec_feedback = None
            self._rlog("怪无血条/无伤害(已死或假怪),放弃并重新锁怪", LOG_RED)
        # --- 新目标:动作层重置出手反馈/跳高节奏/上屏(选怪权在B,这里只管执行侧状态不选怪) ---
        if _dl.get('new_target'):
            self._note_freq_event('lock_tgt', 3, 1000, "1秒内锁定/换锁怪%d次(疑似锁不住或假怪多)")
            self._combat_target_attacked = False
            self._combat_first_strike_time = 0
            self._combat_exec_feedback = None
            self._combat_target_lock_time = now
            _new_in_sj = bool(_slope_on) and _sj_min <= (py_layer - t_cy) <= _sj_max
            _oldm = getattr(self, '_last_mirror_lock', None)
            _old_in_sj = bool(_slope_on) and _oldm is not None and _sj_min <= (py_layer - _oldm[1]) <= _sj_max
            if not (_new_in_sj and _old_in_sj):
                self._slope_high_mode = False
                self._slope_phase = 'wait_jump'
                self._slope_next_at = 0
            self._rlog("锁定怪 X差%+d Y差%+d(正=在上) 距离%d [%s]" % (
                t_cx - px, py_layer - t_cy, t_dist, _dl['state']))
            _grp = _dl.get('group')
            if _grp:
                _g_n, _g_tag = _grp
                if _g_tag == 'dual':
                    _g_desc = "双向·站怪群中心(共%d只,两侧同时打)" % _g_n
                elif _g_tag in ('left', 'right'):
                    _g_desc = "单向·先打%s侧怪群(%d只,这侧清空再换边)" % ("左" if _g_tag == 'left' else "右", _g_n)
                else:
                    _g_desc = "锁怪群%d只" % _g_n
                self._rlog("群怪优先·%s [%s]" % (_g_desc, _dl['state']))
        self._last_mirror_lock = (t_cx, t_cy)
        # 战斗状态切换才上屏一条
        _cstate_map = {'cast': "正在打怪(射程内,持续攻击)", 'pursue': "正在找怪/靠近(射程外,走向目标)",
                       'switch': "切换锁定目标", 'idle': "无目标,待机找怪中"}
        if _dl['state'] != getattr(self, '_last_combat_state', None):
            if _dl['state'] in _cstate_map:
                self._rlog(_cstate_map[_dl['state']])
            self._last_combat_state = _dl['state']
        # 打怪决策日志(0.6s)
        if not hasattr(self, '_combat_dlog_last') or now - self._combat_dlog_last > 600:
            self._combat_dlog_last = now
            _debug_log("[打怪决策] 状态=%s 锁定=(%d,%d) 人物=(%d,%d) X差=%d Y差=%d 距离=%s" % (
                _dl['state'], t_cx, t_cy, px, py_layer, abs(t_cx - px), abs(t_cy - py_layer), t_dist))
        # 空怪诊断(1s,全从B决策包读)
        if not hasattr(self, '_kong_last') or now - self._kong_last > 1000:
            self._kong_last = now
            _debug_log("[空怪诊断] 状态=%s 活着=%s drop=%s 伤害=%s 已出手=%s 确认血=%s gone=%d 血条数=%d" % (
                _dl['state'], _dl.get('alive'), _dl.get('drop'), _dl.get('has_dmg'),
                _dl.get('attacked'), _dl.get('hp_confirmed'), _dl.get('gone'), len(self._monster_hp_bars)))

'''
CUT.append(("main read decision packet",
            "        _combat_mons = self._monsters",
            "        # 【巡路优先·一条线原则", NEW_READ))

# ============ CUT C: cast/pursue 路由块 瘦身 ============
NEW_CAST = '''        if _dl['state'] in ('cast', 'pursue') and _dl['target']:
            # 有同平台怪:锁谁/判死/换锁全由B决策包定,这里只进入打/追执行(target已在上面解出)
            self._combat_active = True

'''
CUT.append(("slim cast/pursue branch",
            "        if _dl['state'] in ('cast', 'pursue') and _dl['target']:",
            "        elif _dl['state'] == 'cross':", NEW_CAST))

# ============ CUT D: cross 路由块(删写锁,保留全部闸门/transit) ============
NEW_CROSS = '''        elif _dl['state'] == 'cross':
            # 同平台无够得着的怪→跨层:选梯/走台/爬梯动作全在主线(_try_platform_transition/_transit_step);B只给cross状态与候选
            self._combat_active = False
            # 到顶重识别保护期:旧帧可能把梯子下方旧怪判成cross把人又拉下去,窗内不启动跨层
            if now < getattr(self, '_arrival_relock_until', 0):
                self._release_combat_move()
                return
            _ccx, _ccy = t_cx, t_cy
            self._rlog_throttle('cross_need', "本层无够得着的怪,目标在%s%dpx(X差%+d),需走梯子/瞬移跨层" % (
                "上方" if _ccy < py_layer else "下方", abs(py_layer - _ccy), _ccx - px), 1500, log='behavior')
            # 空转达上限/弃梯回切后的防抖窗:窗内不启动cross走台
            if now < getattr(self, '_no_transit_until', 0):
                self._release_combat_move()
                return
            # 打怪区域·上下闸门(认平台绿线):只拦新发起的跨层
            _bound_vdir = 'up' if _ccy < py_layer else ('down' if _ccy > py_layer else None)
            if _bound_vdir and self._bound_blocked_vertical(_bound_vdir):
                self._release_combat_move()
                self._rlog_throttle('bound_v_gate', "打怪区域:已到%s边界,不%s跨层" % (
                    "上" if _bound_vdir == 'up' else "下", "向上" if _bound_vdir == 'up' else "向下"), 1000, log='behavior')
                return
            # 跳高打腾空余温窗:窗内即使实时Y把脚下怪误判成下方cross也不发起下台
            if _bound_vdir == 'down' and (now - getattr(self, '_slope_high_last_jump', 0)) < SLOPE_HIGH_DOWN_BLOCK_MS:
                self._release_combat_move()
                self._rlog_throttle('slope_no_down', '跳高打腾空窗内,暂不向下跨层(等落地重判)', 800, log='behavior')
                return
            _cross_cands = _dl.get('cross_candidates', [])
            if self._try_platform_transition(_cross_cands, now):
                self._transit_step()   # 启动跨层行进
            else:
                self._release_combat_move()   # 没有可去目标：松手等刷怪
            return
'''
CUT.append(("slim cross branch",
            "        elif _dl['state'] == 'cross':",
            "        elif _dl['state'] == 'switch':", NEW_CROSS))

# ============ CUT E: switch 路由块(翻探测侧归B) ============
NEW_SWITCH = '''        elif _dl['state'] == 'switch':
            # 本边没怪换边探测:翻探测侧归B决策(b_probe_side),主线只松键、不自己翻状态
            self._combat_active = False
            self._release_combat_move()
            return
'''
CUT.append(("slim switch branch",
            "        elif _dl['state'] == 'switch':",
            "        else:\n            # idle：无任何可打目标，恢复巡路", NEW_SWITCH))

# ====== 先做 CUT(按起始marker在文中位置倒序,避免位移) ======
cuts = []
for desc, sm, em, newmid in CUT:
    s = text.find(sm)
    e = text.find(em)
    assert s != -1, "CUT start not found: " + desc
    assert e != -1 and e > s, "CUT end not found/order: " + desc
    cuts.append((s, e, newmid, desc))
cuts.sort(key=lambda x: -x[0])
for s, e, newmid, desc in cuts:
    text = text[:s] + newmid + text[e:]

# ====== 再做 REP ======
for desc, old, new, cnt in REP:
    actual = text.count(old)
    assert actual == cnt, "REP count mismatch [%s] expect=%s actual=%s" % (desc, cnt, actual)
    text = text.replace(old, new)

# ====== 残留断言(旧机制必须清零) ======
for must_zero in ['_slope_high_blocked', '_publish_combat_intent', '_combat_intent_packet',
                  '_b_next_anchor', '_eff_up_band', '_slope_blocked']:
    z = text.count(must_zero)
    assert z == 0, "residual %s x%d" % (must_zero, z)
assert text.count('self._detect_damage_number(') == 1, "damage call sites != 1"
for must_one in ['def _publish_combat_decision', '_combat_decision_packet', '_combat_exec_feedback',
                 '_phantom_filter_readonly', 'self._b_lock']:
    assert text.count(must_one) >= 1, "missing new symbol: " + must_one

# ====== 写回 UTF-8 BOM + LF ======
assert '\r\n' not in text, "CRLF appeared before write"
with io.open(PATH, 'wb') as f:
    f.write(b"\xef\xbb\xbf" + text.encode('utf-8'))
print("STAGE2 APPLIED OK, chars=%d" % len(text))
