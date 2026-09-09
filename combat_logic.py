# -*- coding: utf-8 -*-
"""
打怪决策核心（纯逻辑，可脱离游戏用合成数据单元测试）。
只负责"选哪只 / 往哪走 / 什么状态"，不碰底层检测/移动/存活。
底层积木（检测/移动/跨层/平台判定）由调用方注入，本模块保持纯净、可测。

设计要点：
- 技能射程 skill_range = 走近/站定/施放的唯一主判据（法师按 COMBAT_NEAR_RANGE=350）。
- 一次只测一边（probe_side，1=右 -1=左）：某边有怪就去打，不是原地不停测。
- 同一层内：技能射程内(tier0)优先，其次500同平台(tier1)，每档内距离最近优先。
- 本层无怪才去跨层 / 待机。
- 已锁定目标【仍在本帧检测列表】就维持锁定（至少稳定 MIN_LOCK_HOLD_MS，不中途换、不被群攻抢）；
  锁定目标本帧脱检(列表里没有)绝不对旧坐标空打，立刻从列表重选真实存在的最近怪(用户2026-09-07)。
"""

# 锁定最短维持时长(ms)：锁定一只怪后至少稳定打这么久，不被其他怪抢目标(用户2026-09-07：锁定最少1秒一次)
MIN_LOCK_HOLD_MS = 1000

# === 群怪优先·换簇阈值(用户2026-09-09定稿,写死常量) ===
GROUP_SWITCH_NEAR = 200     # 当前簇与另一簇"到人物最近距离差"≤200 才允许换簇
GROUP_SWITCH_FAR = 300      # 距离差≥300 绝不换(201~299为死区也不换,锁谁是谁)
GROUP_SWITCH_MIN_MORE = 3   # 另一簇必须比当前簇【多≥3只】才算"更多",多1~2只不换


def _mk(state, target, direction, dist, cross_candidates=None, group=None):
    return {"state": state, "target": target, "direction": direction, "dist": dist,
            "cross_candidates": cross_candidates or [], "group": group}


def _dir_to(cx, px):
    """目标相对人物的水平方向：右/左/None(正对)"""
    if cx > px + 3:
        return "right"
    if cx < px - 3:
        return "left"
    return None


def _in_band(cy, py, y_up, y_down):
    """怪脚Y是否落在相对人物的[上容差,下容差]带内(向上为负)；y_up=None=不限制"""
    if y_up is None:
        return True
    return -y_up <= (cy - py) <= y_down


def best_group_window(px, py, rows, radius, dual):
    """群怪优先·在池内怪 rows=[(x_gap,cx,cy)] 中找"X跨度≤2*radius 能罩最多怪"的最佳窗。

    群攻框以人物为中心、左右各 radius(双向近身技能两侧同时出伤害)，故一簇的X跨度≤2R才存在站位一次罩住。
    选窗优先级：罩怪数多 → 窗内离人物最近距离小(省路) → Y更贴合 → X更靠左(确定性)。
      dual=True(双向技能): 走位点=窗X中点(人物站怪群正中间,两侧都罩进左右各R)，ty=窗内Y最贴的怪；
      dual=False(单向技能): 走位点=窗内离人物最近的那只怪(贴一侧打)。
    返回 (target=(tx,ty), size, near_d, side) ；rows空返回None。O(N²)，N=同池怪(通常<30)=微秒级。
    """
    if not rows or not radius or radius <= 0:
        return None
    pts = sorted(rows, key=lambda r: r[1])           # 按cx升序
    n = len(pts)
    best = None
    for i in range(n):
        j = i
        while j < n and pts[j][1] - pts[i][1] <= 2 * radius:
            j += 1
        win = pts[i:j]
        size = len(win)
        near = min(abs(w[1] - px) for w in win)      # 窗内离人物最近的X距离
        yfit = min(abs(w[2] - py) for w in win)      # 窗内最贴的Y差
        left_x = min(w[1] for w in win)
        key = (-size, near, yfit, left_x)
        if best is None or key < best[0]:
            best = (key, win, size, near)
    _, win, size, near = best
    if dual:
        # 双向：不强制几何正中心,直接选窗内【最靠近群X中心的真实怪】当锁定点(用户2026-09-09:选个在群中心的怪即可)。
        # 窗X跨度≤2R,中心怪到窗两端各≈半宽≤R,人物走到它处即站怪群中间、左右各R罩住整簇;且锁定点是真怪,血条/伤害/空怪判定照常。
        _mid = (min(w[1] for w in win) + max(w[1] for w in win)) // 2
        r = min(win, key=lambda w: (abs(w[1] - _mid), abs(w[2] - py), w[0]))
        target = (r[1], r[2])
    else:
        r = min(win, key=lambda w: (w[0], abs(w[2] - py)))            # 窗内离人物最近的怪
        target = (r[1], r[2])
    mean_x = sum(w[1] for w in win) // len(win)
    side = 'right' if mean_x > px + 3 else ('left' if mean_x < px - 3 else None)
    return target, size, near, side


def select_combat_target(px, py, monsters, selected_platforms, skill_range, far_range,
                         target_cx, target_cy, target_alive, is_on_platform,
                         get_monster_platform, probe_side, probe_switched, cur_cross=None,
                         attack_y_up=None, attack_y_down=None, allow_cross=True,
                         now=0, lock_time=0, freeze_lock=False,
                         group_priority=False, group_radius=0,
                         aoe_y_up=None, aoe_y_down=None, aoe_dual=False):
    """决策核心。

    参数:
      px, py            人物屏幕坐标
      monsters          [(x1,y1,x2,y2,score), ...]
      selected_platforms 选中平台编号列表（空=全图模式，不按平台过滤）
      skill_range       技能射程（主判据）
      far_range         同平台探测带（COMBAT_FAR_RANGE=500）
      target_cx, target_cy, target_alive  当前锁定目标 + 是否存活(血条/伤害确认过)
      is_on_platform(cx,cy)->bool    是否与人物同平台（游戏用绿线判定）
      get_monster_platform(cx,cy)->dict|None  怪所在平台（平台过滤用）
      probe_side        探测方向 1=右 -1=左（一次只测一边）
      probe_switched    本轮是否已换过边
      cur_cross         正在去跨层的目标 (cx,cy)|None：还在候选里就维持它，避免左右摇摆
      attack_y_band     技能Y范围：怪脚Y与人物Y差>此值=够不着(上/下方台子)，不原地攻击，改为靠近。
                        None=不限制(仅测试用)，实际传LAYER_Y_NEAR。
      now/lock_time     当前时间与本次锁定起始时间(ms)，用于"锁定最少维持1秒"；默认0=不做时长保护(测试用)

    返回 dict:
      state: 'idle'|'switch'|'pursue'|'cast'|'cross'
      target: (cx,cy)|None（cross时为目标平台/怪的估算位置）
      direction: 'left'|'right'|None
      dist: 目标距离(int)
    """
    cand = []    # 可锁定/聚簇池 [(x_gap,cx,cy)]：近怪优先=主攻Y带；群怪优先=群攻Y带(略高略低也进池)
    cross = []   # 连聚簇池Y带都超出=真跨层,走梯子/瞬移

    # 群怪优先：聚簇池Y带放宽到群攻Y(圈群唯一判据=群攻X+Y)；未开/未传回退主攻Y带,与老行为等价
    _pool_y_up = attack_y_up
    _pool_y_down = attack_y_down
    if group_priority and aoe_y_up is not None:
        _pool_y_up = aoe_y_up
        _pool_y_down = aoe_y_down if aoe_y_down is not None else attack_y_down

    for (x1, y1, x2, y2, _score) in monsters:
        cx = (x1 + x2) // 2
        cy = y2  # 脚位置
        # 平台过滤：只打选中平台上的怪（空列表=全图模式）
        if selected_platforms:
            pf = get_monster_platform(cx, cy)
            if pf:
                if (pf.get('id', 0) + 1) not in selected_platforms:
                    continue
            else:
                continue
        # X差和Y差分开算
        x_gap = abs(cx - px)
        dy = cy - py  # 怪脚Y - 人物脚Y（负=怪在人物上方，正=怪在人物下方）
        # 【用户2026-09-07：找怪不分层，锁定和攻击分开】
        # 锁定只看Y差：Y在攻击范围内(y_ok)=同层怪，进cand优先锁定；Y差大=跨层怪，进cross。
        # 不再用is_on_platform判断本层/别的层（Y差≤150易误判上层怪为同层→标pursue靠近不了→不跨层）。
        # 攻击在选目标后再判断：x_gap<=skill_range→cast，否则→pursue靠近。
        y_ok = _in_band(cy, py, _pool_y_up, _pool_y_down)
        if y_ok:
            cand.append((x_gap, cx, cy))   # 进可锁定/聚簇池(群怪优先=群攻Y带,否则主攻Y带)
        elif allow_cross:
            cross.append((x_gap, cx, cy))   # 连聚簇池Y带都超=真跨层候选

    # === 维持已有锁定（用户2026-09-07：锁定和攻击分开；攻击中不换目标，追怪中出现能直打的立刻换）===
    # 规则：锁定怪必须【仍在本帧检测列表 cand 里】才维持——绝不对脱检旧坐标 cast 空打。
    # ①锁定怪在技能范围内(正在攻击中/cast) → 一直维持，直到死亡/脱检/drop，不被别的怪抢(稳定打死)；
    # ②锁定怪在技能范围外(走路追怪中/pursue)：只要身边出现任意能直打的怪(x_gap<=skill_range)，【立刻】让位给最近的近身怪——
    #   不管锁了多久、不管是否正在移动；身边没有可打近怪时才继续追锁定目标；
    # ③【范围外粘性】锁定的范围外怪，只能被"范围内能直打的怪"替换，绝不能换成另一只范围外怪——
    #   第一次锁范围外时选的就是最近的,范围内一直没怪就死咬这一只；哪怕它本帧瞬时漏检,也沿最后已知坐标继续追,
    #   不落到"选最近"而跳到另一侧(治"一下子左一下子右、锁不稳")；
    # ④原【范围内】锁定怪本帧脱检(多半刚被打死) → 不粘,落到下方从cand立刻重选最近怪(打完快速锁下一只,不等)。
    if target_cx is not None:
        # 【冻结锁定·用户2026-09-09】需要梯子上下的巡路(攀爬)期间禁止换锁：哪怕身边刷出技能范围内的怪也不替换，
        # 死咬当前(跨层)目标继续巡路，等调用方上/下到位解冻、下一帧重新识别时才解绑重锁。
        if freeze_lock:
            for (d, cx, cy) in cross:   # 冻结目标仍Y差大(还没到同层) → 维持cross继续走梯子/瞬移
                if abs(cx - target_cx) <= 40 and abs(cy - target_cy) <= 50:
                    return _mk('cross', (cx, cy), _dir_to(cx, px), d, cross)
            for (d, cx, cy) in cand:    # 冻结目标已Y相近(爬到同层) → 维持它,按距离cast/pursue,不被别的近身怪顶掉
                if abs(cx - target_cx) <= 40 and abs(cy - target_cy) <= 50:
                    return _mk(('cast' if d <= skill_range else 'pursue'), (cx, cy), _dir_to(cx, px), d)
            # 冻结目标本帧脱检：沿最后已知坐标继续cross(跨层目标本就在别的层),不落到重选、不左右横跳
            return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px), cross)
        locked_row = None
        for row in cand:
            _d, cx, cy = row
            if abs(cx - target_cx) <= 40 and abs(cy - target_cy) <= 50:
                locked_row = row
                break
        # 能"原地主攻直打"=X进主攻射程 且 Y在主攻带(群怪优先池放宽到群攻Y后,略高/略低怪不算能主攻直打,避免站定空打)
        in_range_rows = [r for r in cand if r[0] <= skill_range and _in_band(r[2], py, attack_y_up, attack_y_down)]
        has_in_range = bool(in_range_rows)
        if locked_row is not None:
            ld, lx, ly = locked_row
            if ld <= skill_range:
                return _mk('cast', (lx, ly), _dir_to(lx, px), ld)  # 攻击中：维持锁定(稳定打死)
            # 追怪中(范围外)：身边有能直打的怪就立刻让位(落到下方重选)，没有才继续追这只
            if not has_in_range:
                # 群怪优先·范围外动态换簇(用户2026-09-09定稿)：锁簇满1秒后,出现另一簇
                # "到人物最近距离差≤200 且 比当前簇多≥3只"才放行重选；距离差≥300死咬、201~299死区不换、
                # 多1~2只不换。非群怪优先=范围外粘性,绝不换另一只范围外怪(老行为,治左右横跳)。
                _do_switch = False
                if group_priority and group_radius and group_radius > 0 and now - lock_time >= MIN_LOCK_HOLD_MS:
                    _bg = best_group_window(px, py, cand, group_radius, aoe_dual)
                    if _bg is not None:
                        _bt, _bsize, _bnear, _ = _bg
                        _cur_size = sum(1 for (_cd, _ccx, _ccy) in cand if abs(_ccx - target_cx) <= group_radius)
                        _cur_d = abs(target_cx - px)
                        _other = abs(_bt[0] - target_cx) > 40 or abs(_bt[1] - target_cy) > 50
                        if _other and _bsize - _cur_size >= GROUP_SWITCH_MIN_MORE \
                                and abs(_bnear - _cur_d) <= GROUP_SWITCH_NEAR:
                            _do_switch = True
                if not _do_switch:
                    return _mk('pursue', (lx, ly), _dir_to(lx, px), ld)
                # _do_switch=True：不return,落到下方"本层选怪"按群怪规则重选最佳簇
            # 有近身可打怪 → 落到下方重选最近能直打的（范围内替换范围外，合法）
        else:
            # 锁定目标本帧脱检：判断它上一刻是不是"范围内能直打的怪"
            _locked_was_in = (abs(target_cx - px) <= skill_range)
            if _locked_was_in:
                pass  # 原范围内怪脱检=大概率刚死 → 落下方立刻重选最近(快速换锁)
            elif has_in_range:
                pass  # 范围外锁定漏检,但此刻出现了范围内怪 → 允许范围内替换,落下方选最近能直打的
            else:
                # 范围外锁定瞬时漏检、且范围内也没怪
                # 【用户2026-09-08】如果锁定目标在cross候选里（Y差大=上层/下层怪），返回cross走梯子，不是pursue走过去。
                # 之前直接返回pursue导致上层怪被当成追怪走过去，走不动→频繁卡住重按+跳→小碎步→只锁定不打怪。
                for (d, cx, cy) in cross:
                    if abs(cx - target_cx) <= 40 and abs(cy - target_cy) <= 50:
                        return _mk('cross', (cx, cy), _dir_to(cx, px), d, cross)
                # 不在cross候选里=真的脱检了，沿最后已知坐标继续追(防左右摇摆)；
                # 是否彻底放弃由调用方的2秒宽限/空怪drop裁决，本函数只保证"不左右横跳"
                return _mk('pursue', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px))

    # === 聚簇池有怪：群怪优先走"怪群"路线，否则走"Y近+X近"近怪路线(用户2026-09-09定稿,两路线二选一不混) ===
    if cand:
        # 真正能原地主攻直打=X进主攻射程 且 Y在主攻带(群怪池放宽后,略高/略低怪不算主攻能直打)
        in_attack_rows = [r for r in cand if r[0] <= skill_range and _in_band(r[2], py, attack_y_up, attack_y_down)]
        if group_priority and group_radius and group_radius > 0:
            # ===================== 群怪优先路线 =====================
            if in_attack_rows:
                # 最高铁律：射程内已有主攻能直打的怪,原地打,不被任何远处怪群带走
                if aoe_dual:
                    # 双向群攻(近身两侧同时出伤害)：不选边,射程内怪取最佳窗、人物站窗X中点,主攻打中心、群攻两侧同时清
                    _bg = best_group_window(px, py, in_attack_rows, group_radius, True)
                    _tx, _ty = _bg[0]
                    return _mk('cast', (_tx, _ty), _dir_to(_tx, px), abs(_tx - px), group=(_bg[1], 'dual'))
                # 单向群攻：左右分桶,哪侧怪多先打哪侧；当前锁定那只cast中已在上面维持段稳住(打死才换),这里=重选取多侧
                _left = [r for r in in_attack_rows if r[1] < px - 3]
                _right = [r for r in in_attack_rows if r[1] > px + 3]
                _mid = [r for r in in_attack_rows if not (r[1] < px - 3 or r[1] > px + 3)]
                _buckets = []
                if _left:
                    _buckets.append((len(_left), min(r[0] for r in _left), _left))
                if _right:
                    _buckets.append((len(_right), min(r[0] for r in _right), _right))
                if _buckets:
                    _buckets.sort(key=lambda b: (-b[0], b[1]))   # 数量多优先 → 桶内最近更近
                    bucket = _buckets[0][2]
                else:
                    bucket = _mid or in_attack_rows
                bucket.sort(key=lambda r: (abs(r[2] - py), r[0]))
                _d, _cx, _cy = bucket[0]
                _side = 'left' if _cx < px else 'right'
                return _mk('cast', (_cx, _cy), _dir_to(_cx, px), _d, group=(len(bucket), _side))
            # 射程内无主攻怪(全要走位)：整池聚簇找罩最多的窗。≥3只才走群怪(用户:1~2只用单攻不管群攻/双向)
            _bg = best_group_window(px, py, cand, group_radius, aoe_dual)
            if _bg is not None and _bg[1] >= 3:
                _tx, _ty = _bg[0]
                _d = abs(_tx - px)
                _st = 'cast' if _d <= skill_range else 'pursue'   # 双向站窗中心/单向贴窗内最近怪,走近到射程即站定群攻
                _tag = 'dual' if aoe_dual else (_bg[3] or 'side')
                return _mk(_st, (_tx, _ty), _dir_to(_tx, px), _d, group=(_bg[1], _tag))
            # 最佳簇不足3只 → 回退近怪单攻(用户:1~2只还是用单攻)
        # ===================== 近怪优先路线(老行为,先|Y差|再X近) =====================
        cand.sort(key=lambda r: (abs(r[2] - py), r[0]))
        pick = cand[0]
        d, cx, cy = pick
        st = 'cast' if (d <= skill_range) else 'pursue'
        return _mk(st, (cx, cy), _dir_to(cx, px), d)

    # === 本层无怪 → 跨层 / 待机 ===
    if cross:
        # 跨层也先选Y差最小(高度最接近当前层)的目标，避免刚上平台就锁到脚下更低层又跳下去(用户2026-09-09)
        cross.sort(key=lambda r: (abs(r[2] - py), r[0]))
        # 维持已选跨层目标（避免"人物站中间"时左右摇摆）：该目标还在候选里就用它
        if cur_cross is not None:
            for (d, cx, cy) in cross:
                if abs(cx - cur_cross[0]) <= 40 and abs(cy - cur_cross[1]) <= 50:
                    return _mk('cross', (cx, cy), _dir_to(cx, px), d, cross)
        _, fx, fy = cross[0]
        return _mk('cross', (fx, fy), _dir_to(fx, px), cross[0][0], cross)
    return _mk('idle', None, None, None)


# ==========================================================================
# 决策2：怪物存活判定（规则4：血条 或 伤害数字，其一存在=没死）
# 关键修正：只对"从未确认活着"的静止目标用1秒X判据；已被命中的真怪即使不动也不丢。
# ==========================================================================

def decide_alive(has_hp, has_dmg):
    """当前帧怪是否活着：血条 or 伤害数字，其一=True"""
    return bool(has_hp or has_dmg)


def lock_status(has_hp, has_dmg, hp_confirmed, gone_frames, attacked=False):
    """根据存活证据决定锁定状态。

    返回 dict:
      alive: bool         当前帧是否认为怪活着（血条 or 伤害数字 其一）
      drop:  bool         是否应立即放弃锁定（换目标）
      hp_confirmed: bool  是否已确认过血条（命中过）
      gone_frames: int    连续"无血条"帧数
    attacked=True 表示 bot 已经对该目标出过手(且已过反馈窗口)；打了一下仍无血条无伤害 = 空怪/假怪 → 直接放弃。

    【2026-09-07 删除"锁满2.5秒无反馈就丢"的超时兜底】：进了可打范围直接打、由"出手后无反馈"判空怪，
    真怪打死由"血条连续2帧消失"判；射程外到不到得了归执行层防卡(不动→跳→放弃压侧)。任何按时间丢目标的
    逻辑都会让远怪"走到一半到点被丢→锁另一侧→来回横跳不打"，故不再保留任何锁定时长丢弃。
    """
    alive = decide_alive(has_hp, has_dmg)
    drop = False
    if hp_confirmed and not has_hp:
        # 确认过血条+现在血条没了=怪死了/离开；伤害数字会残留0.5~1秒不算活着凭据
        # → 连续2帧没血条即弃锁定(治"怪打死后还一直按攻击键空打")
        gone_frames = gone_frames + 1
        if gone_frames >= 2:
            drop = True
    else:
        gone_frames = 0
    # 用户定稿：打了一下(过反馈窗口)仍"无血条且无伤害" = 空怪/背景/尸体 → 放弃换下一只；任一凭据在就不换
    if attacked and not has_hp and not has_dmg:
        drop = True
    # 首次检测到血条 = 攻击命中确认
    if has_hp and not hp_confirmed:
        hp_confirmed = True
    return {"alive": alive, "drop": drop, "hp_confirmed": hp_confirmed, "gone_frames": gone_frames}


# ==========================================================================
# 决策3：这次放什么技能（主攻锁定目标优先；群攻=补充溅射，不抢主攻）
# ==========================================================================

def decide_attack(t_dist, skill_range, aoe_range, aoe_count, main_cd_ok, aoe_cd_ok):
    """决定本次技能动作。

    返回: 'main' 主攻 | 'aoe' 群攻 | 'none' 不施放
    规则：主攻只对"锁定目标在技能射程内且冷却OK"施放，绝不因群攻可放而放弃主攻；
          群攻仅当"范围内≥3只且冷却OK"时作为补充溅射。
    """
    if main_cd_ok and t_dist <= skill_range:
        return 'main'          # 主攻锁定目标优先，不被群攻抢占
    if aoe_cd_ok and aoe_count >= 3:
        return 'aoe'           # 群攻补充溅射（主攻冷却/目标拉远时才替补）
    return 'none'


# ==========================================================================
# 决策4：完整战斗tick编排（组合上面三块，输出这一刻该做什么）
# ==========================================================================

def combat_step(now, px, py, monsters, selected_platforms, skill_range, aoe_range, far_range,
                lock, hp_bars, has_dmg, main_cd_ok, aoe_cd_ok,
                probe_side, probe_switched, is_on_platform, get_monster_platform,
                lock_time, hp_confirmed, gone_frames, cur_cross=None,
                attacked=False, attack_y_up=None, attack_y_down=None, allow_cross=True,
                freeze_lock=False, group_priority=False, group_radius=0,
                aoe_y_up=None, aoe_y_down=None, aoe_dual=False):
    """组合 select_combat_target + lock_status + decide_attack，得到本tick完整的战斗决策。

    参数: 见各部分；now/lock_time 单位ms。
    返回 dict:
      state: 'idle'|'switch'|'pursue'|'cast'|'cross'
      target: (cx,cy)|None
      direction: 'left'|'right'|None
      dist: int|None
      alive: bool          当前锁定目标是否存活
      drop: bool           是否应放弃当前锁定（怪已死/假怪）
      hp_confirmed: bool   是否已确认命中(见过血条)
      gone_frames: int     连续无反馈帧数
      skill: 'main'|'aoe'|'none'   本次要施放的技能
    """
    lcx, lcy = (lock if lock else (None, None))
    # 存活证据：目标附近是否有血条（收紧贴近度，避免附近怪的血条被算成目标的，导致空怪不drop）
    has_hp = False
    if lock:
        for (bx, by, bw, bh) in hp_bars:
            if abs((bx + bw / 2) - lcx) < 35 and abs((by + bh / 2) - lcy) < 45:
                has_hp = True
                break
    # 存活/空怪判定（仅已锁定）：血条连续2帧消失=打死；出手后无血条无伤害=空怪。不再有任何"锁定时长到点丢弃"。
    ls = {"alive": bool(lock), "drop": False, "hp_confirmed": hp_confirmed,
          "gone_frames": gone_frames}
    if lock:
        ls = lock_status(has_hp, has_dmg, hp_confirmed, gone_frames, attacked)
    # 若判定放弃锁定（真怪死了/假怪）→ 本轮重新选目标
    eff_lock = lock if not ls["drop"] else None
    d = select_combat_target(px, py, monsters, selected_platforms, skill_range, far_range,
                            (eff_lock[0] if eff_lock else None),
                            (eff_lock[1] if eff_lock else None),
                            ls["alive"], is_on_platform, get_monster_platform,
                            probe_side, probe_switched, cur_cross, attack_y_up, attack_y_down,
                            allow_cross, now, lock_time, freeze_lock, group_priority, group_radius,
                            aoe_y_up, aoe_y_down, aoe_dual)
    # 技能施放决策
    skill = 'none'
    if d['target'] is not None and d['dist'] is not None:
        aoe_count = 0
        for (x1, y1, x2, y2, _s) in monsters:
            mcx = (x1 + x2) // 2
            mcy = y2
            if abs(mcx - px) <= aoe_range and abs(mcy - py) <= aoe_range:
                aoe_count += 1
        skill = decide_attack(d['dist'], skill_range, aoe_range, aoe_count,
                              main_cd_ok, aoe_cd_ok)
    d['alive'] = ls['alive']
    d['drop'] = ls['drop']
    d['hp_confirmed'] = ls['hp_confirmed']
    d['gone_frames'] = ls['gone_frames']
    d['skill'] = skill
    d['cross_candidates'] = d.get('cross_candidates', [])
    return d
