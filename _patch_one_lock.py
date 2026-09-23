# -*- coding: utf-8 -*-
"""锁怪开关"一套化"改造补丁(用户2026-09-23定稿)。
只认 _b_lock_enabled 一个总开关:
  - 上行:走向梯/选梯/对位(未起跳)B锁保持开,身边cast怪自然回打;发跳键前一刻关锁一心上;到顶/失败立刻开锁。
  - 下行:进descend只关B锁总开关、不闭怪识别;落地判据=三背景点静止 OR 满3s兜底(删光点Y180ms那条)。
  - 清理:删 _is_lock_frozen 对B门控影响(函数改名 _in_vertical_motion 只服务主线动作主权);
          删 _arrival_relock_until 全部赋值/判断;横跳侧跳方向改纯随机;删 DESCEND_RELOCK_DELAY_MS 死常量。
"""
import io, sys

p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
raw = io.open(p, 'rb').read()
bom = b'\xef\xbb\xbf'
has_bom = raw.startswith(bom)
s = raw.decode('utf-8-sig').replace('\r\n', '\n')

# (描述, old, new)  old 必须在文中恰好出现1次
EDITS = []

# 1) 删死常量 DESCEND_RELOCK_DELAY_MS(613)
EDITS.append((
    '删死常量DESCEND_RELOCK_DELAY_MS',
    'DESCEND_RELOCK_DELAY_MS = 1500  # 下跳(下台)【横跳(方式一第二跳/方式二侧跳离梯)后】多少ms才许B重新锁怪(用户2026-09-19定稿:不判落地,横跳起计时1.5秒,窗内B只清锁不出包、识别照开,到期用热怪表重锁;到顶/走台/边界仍只150ms)\n',
    ''
))

# 2) _enter_to_ladder_up 删进段即关锁(5722-5725)
EDITS.append((
    '进上梯段不再提前关锁',
    """        # 小地图上梯不经过白框蒙板建锁(旧关锁点随白框整套删除),进段即关【锁怪】并当场清已锁;
        # 识怪/怪表/血条快照照常跑(只停锁怪决策)。到顶_reset_lock_after_arrival、失败_decide_climb_fail_action
        # 都会_set_b_lock_enabled(True)用热怪表重锁(用户2026-09-21:识怪常开、锁怪可关、起跳一心上梯)。
        self._set_b_lock_enabled(False, '进上梯·关锁专心爬梯')""",
    """        # 用户2026-09-23定稿:走向梯/选梯/对位(未起跳)阶段B锁保持开,按"最近优先"自然选怪——
        # 身边攻击范围内刷出cast怪就停步松键回打,打完自然流转(同层近怪→空了自然又选到上层cross再走向梯),
        # 不钉旧上层目标、不特意回旧梯。关锁只在_ladder_mm_start_jump发跳键前一刻做(起跳一心上梯)。"""
))

# 3) _ladder_mm_start_jump 发跳键前关锁(5400-5402)
EDITS.append((
    '起跳前关锁',
    """        self._ladder_back_peak = 0.0
        self._ladder_back_seen_frames = 0
        self._press_game_key(jump_key, duration=120)""",
    """        self._ladder_back_peak = 0.0
        self._ladder_back_seen_frames = 0
        # 用户2026-09-23:起跳前关B锁(清已锁+决策包),一心上梯不抢怪;到顶/失败由reset重开。
        # 关锁在发跳键前一帧,_press_game_key阻塞120ms期间B线程已用热怪表清完包,不影响起跳。
        self._set_b_lock_enabled(False, '起跳前关锁一心上梯')
        self._press_game_key(jump_key, duration=120)"""
))

# 4) B门控只认总开关(16542)
EDITS.append((
    'B门控简化为只认总开关',
    """                        if (not getattr(self, '_b_lock_enabled', True)) or self._is_lock_frozen() or int(time.time() * 1000) < getattr(self, '_arrival_relock_until', 0):  # 锁怪总开关关=清锁不出包(识怪/怪表/血条照跑,与锁怪分开);或硬冻/到顶下跳重锁保护窗:窗内清锁不出包、怪表照刷,落稳零等待重锁
                            # 硬冻(已起跳/校准/爬梯/下跳):识别与怪表照刷(上面_raw已更新),但清锁定、不出打怪目标,
                            # 主线帧首硬闸一心爬梯绝不锁怪;到顶/失败解冻后B下一帧用一直热着的新层怪表立即重锁、零等待""",
    """                        if not getattr(self, '_b_lock_enabled', True):  # 用户2026-09-23:B出包只认一个总开关。关=清锁不出包(识怪/怪表/血条照跑);开=按最近选。已起跳/爬梯/下跳期间由主线帧首动作独占挡住打怪,不靠B门控
                            # 关锁期间识别与怪表照刷(上面_raw已更新),但清锁定、不出打怪目标;开锁后B下一帧用一直热着的新层怪表立即重锁、零等待"""
))

# 5) _is_lock_frozen 改名 _in_vertical_motion + docstring(14527-14542)
EDITS.append((
    '锁冻结函数改名为动作主权',
    '''    def _is_lock_frozen(self):
        """锁怪冻结硬信号(用户2026-09-09定稿)：以"我们自己的抓梯/垂直动作阶段"为唯一判据,不靠画面Y/X(镜头会滚、对齐会抖)。
        ·to_ladder平地走向梯子、还没跳=不冻,身边有更该打的怪允许换(换了重新选梯)；
        ·一旦跳起来进入抓梯流程(post_jump)、或已在climbing爬梯/jump_down下跳/teleport瞬移=锁死,
         一直到到顶/到底_reset_lock_after_arrival才解冻重识别。信号只有冻/不冻两种,明确稳定。
        【用户2026-09-11定稿·跨层怪=范围外怪,分两档】平地走向梯子/走台子(还没起跳,_climb_state=none/to_ladder未post_jump)
        =软冻结:锚点坐标固定保存不丢,但套用"范围外锁定"规则——技能范围内刷出能直打的本层怪允许解绑回主线先打(三步走在移动权
        裁决处做);一旦起跳抓梯(post_jump)/climbing/jump_down/teleport/descend=硬冻结,近身怪也不换,一心到登顶/失败。
        故这里【不能】再因_combat_transit=True就硬冻(transit走平地去梯时也是True,那会让近身怪打不了、和用户最新规则冲突);
        硬冻只认"自己的垂直爬梯动作阶段"。掉台归位的爬梯同理按_climb_state判。"""
        cs = getattr(self, '_climb_state', 'none')
        if cs in ('climbing', 'jump_down', 'jump_up', 'teleport', 'descend'):
            return True
        if cs == 'to_ladder' and getattr(self, '_ladder_jump_phase', None) in ('post_jump', 'realign'):
            return True
        return False''',
    '''    def _in_vertical_motion(self):
        """动作主权(用户2026-09-23改名,原_is_lock_frozen)：以"我们自己的抓梯/垂直动作阶段"为唯一判据,
        不靠画面Y/X(镜头会滚、对齐会抖)。只服务主线帧首动作独占——已起跳/爬梯/下跳阶段,主线帧首只走跨层状态机,
        打怪/走位/战斗瞬移/巡游全不碰、松战斗移动键,从源头独占防两个司机抢键。
        【与锁怪解耦】它不再控制B出包(B出包只认_b_lock_enabled总开关);也不是第二套锁。
        平地走向梯子/走台子(还没起跳,to_ladder未post_jump)=软态,不在此拦,身边攻击范围内cast怪允许回打。"""
        cs = getattr(self, '_climb_state', 'none')
        if cs in ('climbing', 'jump_down', 'jump_up', 'teleport', 'descend'):
            return True
        if cs == 'to_ladder' and getattr(self, '_ladder_jump_phase', None) in ('post_jump', 'realign'):
            return True
        return False'''
))

# 6) 边界拉回调用点改名(15120)
EDITS.append((
    '边界拉回调用点改名',
    '        if side is None or self._is_lock_frozen() or getattr(self, \'_climb_state\', \'none\') != \'none\':',
    '        if side is None or self._in_vertical_motion() or getattr(self, \'_climb_state\', \'none\') != \'none\':'
))

# 7) 主线帧首调用点改名+注释(16989-16992)
EDITS.append((
    '主线帧首硬闸调用点改名',
    """        # === 唯一硬闸(用户2026-09-19两档合并):已起跳/校准/爬梯/下跳/瞬移(_is_lock_frozen硬态)=本帧只走跨层状态机, ===
        # 打怪/走位/战斗瞬移/巡游全不碰、松战斗移动键,从决策最源头独占,根治"爬一半被打怪侧抢键/两个司机拉扯"。
        # 平地走向梯子还没起跳(to_ladder未post_jump)=软态,不在此拦(下面软分流放行近身站定怪cast先打)。
        if self._is_lock_frozen():""",
    """        # === 唯一硬闸(用户2026-09-23改名_in_vertical_motion):已起跳/校准/爬梯/下跳/瞬移=本帧只走跨层状态机, ===
        # 打怪/走位/战斗瞬移/巡游全不碰、松战斗移动键,从决策最源头独占,根治"爬一半被打怪侧抢键/两个司机拉扯"。
        # 平地走向梯子还没起跳(to_ladder未post_jump)=软态,不在此拦(下面软分流放行近身站定怪cast先打)。这层只管动作主权,不碰锁怪。
        if self._in_vertical_motion():"""
))

# 8) _reset_lock_after_arrival 删150ms窗(15561-15567)
EDITS.append((
    '到顶reset删重锁保护窗',
    """        # 重锁保护窗(用户2026-09-19定稿):下跳不判落地,1.5秒窗在"横跳(方式一第二跳/方式二侧跳离梯)"那一刻已起算;
        # 此处落地reset只清锁、用max保留横跳窗剩余(不被落地时刻缩短),横跳窗已过才给150ms短兜底;到顶/走台/边界一律150ms挡旧帧cross。
        _now_relock = time.time() * 1000
        if source in ('下行自由落', '借梯侧跳落下', '下跳落地'):
            self._arrival_relock_until = max(getattr(self, '_arrival_relock_until', 0), _now_relock + 150)   # 保留横跳起算的1.5秒窗剩余
        else:
            self._arrival_relock_until = _now_relock + 150
        _debug_log("[跨层] 到达新平台(来源=%s):清旧锁定+寻怪范围立刻重扫重锁" % (source or '?'))""",
    """        # 用户2026-09-23:到顶/落地立刻开锁重锁,不等任何保护窗(B锁上方15554已开)。
        _debug_log("[跨层] 到达新平台(来源=%s):清旧锁定+寻怪范围立刻重扫重锁" % (source or '?'))"""
))

# 9) _enter_descend 不关怪识别、只关B锁(5750-5752)
EDITS.append((
    '进下跳只关B锁不闭怪识别',
    """        self._climb_state = 'descend'
        self._climb_direction = -1
        self._ladder_precise_mode = True   # 用户2026-09-15:第一次下跳就关怪物识别,横跳离梯+1秒/落地由_reset_climb重开""",
    """        self._climb_state = 'descend'
        self._climb_direction = -1
        self._ladder_precise_mode = True   # 高帧档(下跳/方式二选梯加快截图);不闭怪物识别
        # 用户2026-09-23:进下跳不关怪识别,只关B锁总开关(与上梯起跳关锁同一套)。
        # 落地_reset_lock_after_arrival重开,B用一直热着的怪表重锁,零等待。
        self._set_b_lock_enabled(False, '进下跳·关锁')"""
))

# 10) fall 删光点Y180ms判据+超时改3s(6149-6161)
EDITS.append((
    'fall落地判据删Y稳定+超时3s',
    """                elif _n_valid >= 1:
                    self._climb_still_since = 0   # 还在下落(背景在动),清零
                # n_valid==0空帧:保持计时不打断
            # 【Y稳定并行判据·用户2026-09-10】小地图光点Y连续180ms不再增大=落到底,与背景静止取"或",
            # 不被落地特效/怪撞干扰,先到先落地(治死按↓、背景判不出静止→人到底还压着↓扑倒在地)
            if py > self._desc_land_y + 3:
                self._desc_land_y = py
                self._desc_land_t = now_ms
            elif not _arrived and now_ms - self._desc_land_t >= JUMP_DOWN_LAND_STABLE_MS:
                _arrived = True
                _why = "光点Y稳定%.0fms不再下降=落地" % JUMP_DOWN_LAND_STABLE_MS
            _cdur_d = getattr(self, '_climb_ladder_duration', None)  # 下行不爬录制梯,正常None→回退12s;万一有值也按+2s
            _climb_to_d = int((float(_cdur_d) + 2.0) * 1000) if isinstance(_cdur_d, (int, float)) and float(_cdur_d) >= 1.0 else CLIMB_TOTAL_TIMEOUT_MS""",
    """                elif _n_valid >= 1:
                    self._climb_still_since = 0   # 还在下落(背景在动),清零
                # n_valid==0空帧:保持计时不打断
            # 用户2026-09-23:落地判据只留①三背景点连续静止;②下行总超时3s兜底(删旧"光点Y180ms不下降"判据)。
            _cdur_d = getattr(self, '_climb_ladder_duration', None)  # 下行不爬录制梯,正常None→回退3s;有值按+2s
            _climb_to_d = int((float(_cdur_d) + 2.0) * 1000) if isinstance(_cdur_d, (int, float)) and float(_cdur_d) >= 1.0 else 3000"""
))

# 11) 方式一横跳后删1.5s窗(5986-5989)
EDITS.append((
    '方式一横跳后删重锁窗',
    """                    self._desc_phase = 'check_drop'
                    self._desc_phase_t = now_ms
                    self._arrival_relock_until = now_ms + DESCEND_RELOCK_DELAY_MS   # 横跳(第二跳)起1.5秒:窗内B只清锁不出包、识别照开,到期热怪表重锁(用户2026-09-19:不判落地,横跳后计时)
                    self._key_up(VK_LEFT)""",
    """                    self._desc_phase = 'check_drop'
                    self._desc_phase_t = now_ms
                    self._key_up(VK_LEFT)"""
))

# 12) 方式二侧跳后删1.5s窗(6094-6097)
EDITS.append((
    '方式二侧跳后删重锁窗',
    """                self._desc_phase = 'lad_fall_wait'
                self._desc_phase_t = now_ms
                self._arrival_relock_until = now_ms + DESCEND_RELOCK_DELAY_MS   # 侧跳离梯(横跳)起1.5秒:窗内B只清锁不出包、识别照开,到期热怪表重锁(用户2026-09-19:不判落地,横跳后计时)
                _debug_log("[下行·方式二] 侧向%dms+跳离梯,固定%dms后回主线" % (DESC_LAD_LEAP_SIDE_MS, DESC_LAD_FALL_WAIT_MS))""",
    """                self._desc_phase = 'lad_fall_wait'
                self._desc_phase_t = now_ms
                _debug_log("[下行·方式二] 侧向%dms+跳离梯,固定%dms后回主线" % (DESC_LAD_LEAP_SIDE_MS, DESC_LAD_FALL_WAIT_MS))"""
))

# 13) _pick_desc_side 纯随机(5871-5919)
old_pick = '''    def _pick_desc_side(self, px=None, py=None):
        """下行横跳方向(用户2026-09-22改):第一优先【错开梯子】。横跳是为下穿平台,朝梯子跳会抓住梯=没跳下去还误转方式二。
        用小地图光点(px,py)与录制蓝梯self.ladders([{x,y_top,y_bottom}]):统计左右两侧 DESC_AVOID_LADDER_MM 内、
        梯身竖向覆盖光点Y 的最近梯距;仅一侧有梯->跳无梯侧;两侧都无->按怪方向、无怪参照随机;两侧都有->跳梯距更远侧。
        实心台真跳不下仍由check_drop两次失败后自动转方式二走到梯子位置下去,不在动作中途判。px/py必须是小地图坐标。"""
        try:
            if px is None or py is None:
                _mp = getattr(self, '_player_map_pos', None)
                if _mp:
                    px = _mp[0] if px is None else px
                    py = _mp[1] if py is None else py
            lds = getattr(self, 'ladders', None)
            left_gap = right_gap = None
            if lds and px is not None and py is not None:
                _pfx, _pfy = float(px), float(py)
                for _t in lds:
                    try:
                        tx = float(_t['x']); tt = float(_t['y_top']); tb = float(_t['y_bottom'])
                    except Exception:
                        continue
                    # 只看梯身竖向覆盖光点当前高度的梯(同层台边能被抓住的),别层梯不参与
                    if not (tt - DESC_AVOID_LADDER_MM <= _pfy <= tb + DESC_AVOID_LADDER_MM):
                        continue
                    if tx < _pfx:
                        g = _pfx - tx
                        left_gap = g if left_gap is None else min(left_gap, g)
                    else:
                        g = tx - _pfx
                        right_gap = g if right_gap is None else min(right_gap, g)
            l_near = left_gap is not None and left_gap <= DESC_AVOID_LADDER_MM
            r_near = right_gap is not None and right_gap <= DESC_AVOID_LADDER_MM
            if l_near and not r_near:
                _d = 1; _why = '左侧%.0f有梯,错开跳右' % left_gap
            elif r_near and not l_near:
                _d = -1; _why = '右侧%.0f有梯,错开跳左' % right_gap
            elif l_near and r_near:
                _d = 1 if right_gap >= left_gap else -1
                _why = '两侧皆有梯(左%.0f/右%.0f),跳更远的%s侧' % (left_gap, right_gap, '右' if _d > 0 else '左')
            else:
                tx = getattr(self, '_target_monster_x', None)
                if tx is not None and px is not None:
                    _d = 1 if tx > float(px) else -1
                    _why = '两侧无梯,按怪方向跳%s' % ('右' if _d > 0 else '左')
                else:
                    _d = random.choice([-1, 1]); _why = '两侧无梯无怪参照,随机'
            _debug_log('[下行·避梯] 横跳方向=%s (%s)' % ('右' if _d > 0 else '左', _why))
            return _d
        except Exception:
            return random.choice([-1, 1])'''
new_pick = '''    def _pick_desc_side(self, px=None, py=None):
        """下行横跳/离梯侧跳方向(用户2026-09-23定稿):纯随机。
        旧"错开梯子"系误判——人都在梯子上了不可能跳回另一把梯;侧跳只为带初速度离台,方向随机即可,
        抓不住/没甩开由check_drop/lad_fall_wait的后脑观察兜底,不在选向上纠结。px/py保留签名兼容调用。"""
        _d = random.choice([-1, 1])
        _debug_log('[下行] 侧跳方向随机=%s' % ('右' if _d > 0 else '左'))
        return _d'''
EDITS.append(('侧跳方向纯随机', old_pick, new_pick))

# 14) 主线无目标软分流删窗(17021-17027)
EDITS.append((
    '无目标软分流删保护窗',
    """            if _cs0 == 'to_ladder' or (self._combat_transit and _cs0 == 'none'):
                # 软态跨层路(走向梯子未起跳/走台子):没锁到怪也一心继续走,不巡游;到顶保护窗内松键防旧帧
                if now >= getattr(self, '_arrival_relock_until', 0):
                    self._transit_step()
                else:
                    self._release_combat_move()
                return""",
    """            if _cs0 == 'to_ladder' or (self._combat_transit and _cs0 == 'none'):
                # 软态跨层路(走向梯子未起跳/走台子):没锁到怪也一心继续走,不巡游(用户2026-09-23删保护窗)
                self._transit_step()
                return"""
))

# 15) 主线B无锁删窗(17091-17105)
EDITS.append((
    'B无锁分支删保护窗',
    """            if _cs1 == 'to_ladder' or (self._combat_transit and _cs1 == 'none'):
                if now >= getattr(self, '_arrival_relock_until', 0):
                    self._transit_step()
                else:
                    self._release_combat_move()
                return
            self._combat_active = False
            self._combat_had_target = False
            self._combat_last_target_pos = None
            self._combat_locked_target = None
            if now < getattr(self, '_arrival_relock_until', 0):
                # 到顶/下跳落地重锁保护期(下跳=进descend+2秒):松键站等、不巡游不跨层,落稳B立刻重锁(用户2026-09-19),杜绝保护期内乱走/拿空中旧Y锁错层
                self._release_combat_move()
                return
            if self._roam_tick(now):""",
    """            if _cs1 == 'to_ladder' or (self._combat_transit and _cs1 == 'none'):
                self._transit_step()
                return
            self._combat_active = False
            self._combat_had_target = False
            self._combat_last_target_pos = None
            self._combat_locked_target = None
            if self._roam_tick(now):"""
))

# 16) 软分流cast前删窗(17191-17193)
EDITS.append((
    '软分流cast前删保护窗',
    """            if now < getattr(self, '_arrival_relock_until', 0):
                self._release_combat_move()
                return
            if _dl.get('state') != 'cast':
                self._transit_step()
                return""",
    """            if _dl.get('state') != 'cast':
                self._transit_step()
                return"""
))

# 17) cross启动前删窗(17209-17212)
EDITS.append((
    'cross启动前删保护窗',
    """            # 到顶重识别保护期:旧帧可能把梯子下方旧怪判成cross把人又拉下去,窗内不启动跨层
            if now < getattr(self, '_arrival_relock_until', 0):
                self._release_combat_move()
                return
            _ccx, _ccy = t_cx, t_cy""",
    """            _ccx, _ccy = t_cx, t_cy"""
))

# 执行
fails = []
for desc, old, new in EDITS:
    c = s.count(old)
    if c != 1:
        fails.append((desc, c, old[:80]))
        continue
    s = s.replace(old, new)

if fails:
    print('=== 锚点未命中(count!=1),未写盘 ===')
    for desc, c, head in fails:
        print(' [%s] count=%d  %s' % (desc, c, head))
    sys.exit(1)

out = s.replace('\n', '\r\n')
data = (bom if has_bom else b'') + out.encode('utf-8')
io.open(p, 'wb').write(data)
print('OK: %d 处全部替换成功,已写盘(UTF-8 BOM+CRLF)' % len(EDITS))
for desc, _, _ in EDITS:
    print('  -', desc)
