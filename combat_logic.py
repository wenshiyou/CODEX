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
# 【2026-09-10停用·保留常量】用户定稿"锁了就钉死、只被技能范围内近怪替换",不再有"满1秒才允许换簇"的动态换簇,此常量当前无引用。
MIN_LOCK_HOLD_MS = 1000

# === 群怪换簇阈值(用户2026-09-09旧方案,2026-09-10停用·保留常量) ===
# 旧:锁簇满1秒后另一簇"更多≥3只且更近"就动态换过去。新定稿(用户2026-09-10):首次选定第一群后钉死,不管另一侧变得更多/更近
# 都不换,先打完第一群(该簇清空/drop)再重选;走向范围外怪途中仅被"技能范围内能直打近怪"替换。故下列阈值当前无引用。
GROUP_SWITCH_NEAR = 200     # (停用)当前簇与另一簇"到人物最近距离差"≤200 才允许换簇
GROUP_SWITCH_FAR = 300      # (停用)距离差≥300 绝不换
GROUP_SWITCH_MIN_MORE = 3   # (停用)另一簇比当前簇多≥3只才算"更多"

# 分类滞回带宽(px,用户2026-09-10治cross/pursue逐帧横跳):已锁定目标/在途跨层目标/近身怪(进停步线)分桶时,
# 攻击Y带上、下各放宽这么多形成"维持带",吸收怪框脚Y与人物跳中基点在阈值两侧的边界抖动;新的远处怪仍用原窄带。
# 必须远小于层间Y差(LAYER_Y_GAP=150):真跨层怪Y差≈150,不会被这点放宽误纳同层。
LOCK_HOLD_Y_BAND = 25

# 一个整层的屏幕Y差(用户2026-09-15):怪和人Y差达到这个值=铁定在上下另一层,哪怕绿线same_platform判成同平台也不许破格当同层
# (治"头顶整层怪被同录制平台破格→误cast原地空打、目标在左右横跳的抖动");缓坡/透视Y差小于此值仍可破格按同层走近打。
LAYER_Y_GAP = 150

# 跨层X滞回带宽(px,用户2026-09-11定稿"要不要上梯子必须走到X范围内再判,范围外先水平走过去"):
# 新怪:X差>技能射程一律先按同层走近(pursue),只有X进技能射程仍Y超带才落cross找梯子/下台;
# 已锁定目标用 skill_range+本滞回 作为"维持cross"宽线,吸收射程边界逐帧抖动,不在pursue/cross间横跳。
CROSS_X_HYST = 30

# 【用户2026-09-17定稿·跨层(要梯子/下跳)唯一条件;2026-09-18修正】cross高度线不写死,一律按面板自定义的
# "这套打法实际够得着的高度"判定,与主线执行层(high_slope跳高段/_below2下台段)同一口径:
# 上方=跳高打上限slope_jump_y_max(没开跳高/跳高打空降级=主攻上带attack_y_up),下方=attack_y_down;群攻再按aoe_y放宽。
# 超过该可达带=原地/跳高都够不到=cross走梯子/下跳;X差>=CROSS_X_MAX再高也先水平走近,靠近后仍超可达带才跨层。
CROSS_X_MAX = 300    # 跨层最大X差:X差>=300先pursue水平走近,靠近后仍超面板可达带才跨层(用户:X差<300)


def _mk(state, target, direction, dist, cross_candidates=None, group=None, tier=None):
    return {"state": state, "target": target, "direction": direction, "dist": dist,
            "cross_candidates": cross_candidates or [], "group": group, "tier": tier}


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


def build_buckets(px, py, monsters, selected_platforms, skill_range,
                  get_monster_platform, attack_y_up, attack_y_down,
                  group_priority=False, aoe_y_up=None, aoe_y_down=None,
                  allow_cross=True, metric=None, same_platform_fn=None,
                  target_cx=None, target_cy=None):
    """分桶（阶段一从 select_combat_target 机械抽出，B线程预选与主线选怪共用同一实现，保证同一套口径）。
    返回 (cand, cross, cast_range)：
      cand  = 同层这套打法够得着的怪 (x_gap,cx,cy)：站定打 / 走近打 / 跳高打；
      cross = 面板可达高度带之外、X<CROSS_X_MAX、要梯子/下跳才够得到的怪；
      cast_range = 停步出手线 = 技能射程 4/5。
    target_cx/cy 传当前锁定怪时，仅对它用更宽的"维持带"分桶（吸收边界抖动）；B预选无锁定传 None=全用标准带。
    """
    # 停步出手距离=技能射程的4/5（与主线 stop_range 同一口径）
    cast_range = max(1, int(skill_range * 4 // 5))
    cand = []    # 可锁定/聚簇池 [(x_gap,cx,cy)]：近怪优先=主攻Y带；群怪优先=群攻Y带(略高略低也进池)
    cross = []   # 连聚簇池Y带都超出=真跨层,走梯子/瞬移

    # 可锁定/聚簇池Y带=这套打法"实际够得着"的上/下高度,普通与群攻一套口径(用户2026-09-11:群攻跳高打和普通一套,
    # 跳得够就原地跳打、不找梯子)。基线=传入attack_y_up(启用跳高打时=跳高上限_sj_max,区间高处怪进cand走high_slope;
    # 未启用=主攻带);群攻技能本身打得更高(aoe_y)时再取更宽,保证没开跳高打时群攻"略高略低也能群"的原行为不变。
    _pool_y_up = attack_y_up
    _pool_y_down = attack_y_down
    if group_priority and aoe_y_up is not None:
        _pool_y_up = max(_pool_y_up, aoe_y_up)
        if aoe_y_down is not None:
            _pool_y_down = max(_pool_y_down, aoe_y_down)

    for (x1, y1, x2, y2, _score) in monsters:
        # 几何(中心cx/脚cy/X差/Y差)优先用B识别线程同帧算好的metric(与怪框同帧原子包),主线程不再重复算距离;读不到(人物点丢失/兜底)才现算
        _mt = metric.get((x1, y1, x2, y2)) if metric else None
        if _mt is not None:
            cx, cy, x_gap, dy = _mt
        else:
            cx = (x1 + x2) // 2
            cy = y2  # 脚位置
            x_gap = abs(cx - px)
            dy = cy - py  # 怪脚Y - 人物脚Y（负=怪在人物上方，正=怪在人物下方）
        # 平台过滤：只打选中平台上的怪（空列表=全图模式）
        if selected_platforms:
            pf = get_monster_platform(cx, cy)
            if pf:
                if (pf.get('id', 0) + 1) not in selected_platforms:
                    continue
            else:
                continue
        # 【分类滞回·用户2026-09-10治cross/pursue逐帧横跳】只对"当前锁定目标target"用更宽"维持带"分桶,
        # 吸收怪框脚Y、人物跳中py在攻击Y带边界的抖动;一切新怪仍走原窄带,纳入标准一寸不变。
        # 注意【不能放宽cur_cross】:它是已判跨层、正在走梯子的目标,必须稳定留在cross(由select维持段负责)。
        _is_hold = (target_cx is not None and abs(cx - target_cx) <= 40 and abs(cy - target_cy) <= 50)
        if _is_hold and _pool_y_up is not None:
            _b_up = _pool_y_up + LOCK_HOLD_Y_BAND
            _b_down = (_pool_y_down + LOCK_HOLD_Y_BAND) if _pool_y_down is not None else _pool_y_down
        else:
            _b_up, _b_down = _pool_y_up, _pool_y_down
        y_ok = _in_band(cy, py, _b_up, _b_down)
        # 同录制平台破格（绿线 same_platform_fn；自由打怪主线传 None=纯Y分层）
        _same_pf = False
        if same_platform_fn is not None:
            try:
                _same_pf = bool(same_platform_fn(cx, cy))
            except Exception:
                _same_pf = False
        # 【用户2026-09-17定稿cross条件;2026-09-18修正:高度线读面板实际可达带】
        # ①X差>=300:再高也先pursue水平走近;②X<300且Y超这套打法面板可达高度=cross梯子/下跳;③可达带内一律cand。
        if x_gap >= CROSS_X_MAX:
            cand.append((x_gap, cx, cy))   # X还很远,先水平走近,不判跨层
        elif allow_cross and (
                (_pool_y_up is not None and dy < -_pool_y_up) or      # 怪在上方、超过面板上可达高度=跳高也够不到
                (_pool_y_down is not None and dy > _pool_y_down)):    # 怪在下方、超过面板下方技能带=够不到
            cross.append((x_gap, cx, cy))  # 实际够不着、X<300=走梯子/下跳
        else:
            cand.append((x_gap, cx, cy))   # 在面板可达带内:原地打/跳高打/走近

    return cand, cross, cast_range


def pick_from_buckets(px, py, cand, cross, cast_range,
                      group_priority=False, group_radius=0, aoe_dual=False, cur_cross=None):
    """无锁定时从分桶结果选一只最优怪（阶段一从 select_combat_target 的选新段机械抽出，B预选/主线重选共用）。
    cand 优先（同层清空才取 cross）；群怪优先走最佳窗，单攻射程内外统一按 Y近优先、Y同档再X近。返回 _mk dict。"""
    # === 聚簇池有怪：群怪优先走"怪群"路线，否则走"Y近+X近"近怪路线(用户2026-09-09定稿,两路线二选一不混) ===
    if cand:
        # 技能范围内能直打=X进停步线即可(同层已由进cand的Y分类保证,用户2026-09-10:范围内只按X/数量,不看Y)
        in_attack_rows = [r for r in cand if r[0] <= cast_range]
        if group_priority and group_radius and group_radius > 0:
            # ===================== 群怪优先路线 =====================
            if in_attack_rows:
                # 最高铁律：射程内已有主攻能直打的怪,原地打,不被任何远处怪群带走
                if aoe_dual:
                    # 双向群攻(近身两侧同时出伤害)：不选边,射程内怪取最佳窗、人物站窗X中点,主攻打中心、群攻两侧同时清
                    _bg = best_group_window(px, py, in_attack_rows, group_radius, True)
                    _tx, _ty = _bg[0]
                    return _mk('cast', (_tx, _ty), _dir_to(_tx, px), abs(_tx - px),
                               group=(_bg[1], 'dual'), tier='in')
                # 单向群攻：左右分桶,哪侧怪多先打哪侧
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
                bucket.sort(key=lambda r: r[0])   # 已选数量多的这一侧,桶内按X近(用户2026-09-10:范围内不看Y)
                _d, _cx, _cy = bucket[0]
                return _mk('cast', (_cx, _cy), _dir_to(_cx, px), _d,
                           group=(len(bucket), 'left' if _cx < px else 'right'), tier='in')
            # 射程内无主攻怪(全要走位)：整池聚簇找罩最多的窗。≥3只才走群怪(用户:1~2只用单攻不管群攻/双向)
            _bg = best_group_window(px, py, cand, group_radius, aoe_dual)
            if _bg is not None and _bg[1] >= 3:
                _tx, _ty = _bg[0]
                _d = abs(_tx - px)
                _st = 'cast' if _d <= cast_range else 'pursue'   # 双向站窗中心/单向贴窗内最近怪,走近到停步线(4/5)即站定群攻
                _tag = 'dual' if aoe_dual else (_bg[3] or 'side')
                return _mk(_st, (_tx, _ty), _dir_to(_tx, px), _d,
                           group=(_bg[1], _tag), tier='in' if _st == 'cast' else 'out')
            # 最佳簇不足3只 → 回退近怪单攻(用户:1~2只还是用单攻)
        # ===================== 单攻选怪(用户2026-09-18定稿:射程内外统一Y近优先、Y同档再X近,排序键唯一不左右为难) =====================
        # ①技能范围内有能直打的:按Y差最近优先、Y同档再X近→cast站定打(不再纯X近,避免Y差更大的同X怪被先锁);
        # ②全都在范围外:同一排序键Y近→X近→pursue走过去。两段口径完全一致。
        if in_attack_rows:
            in_attack_rows.sort(key=lambda r: (abs(r[2] - py), r[0]))
            pick = in_attack_rows[0]
        else:
            cand.sort(key=lambda r: (abs(r[2] - py), r[0]))
            pick = cand[0]
        d, cx, cy = pick
        st = 'cast' if (d <= cast_range) else 'pursue'
        return _mk(st, (cx, cy), _dir_to(cx, px), d, tier='in' if st == 'cast' else 'out')

    # === 本层无怪 → 跨层 / 待机 ===
    if cross:
        # 跨层也先选Y差最小(高度最接近当前层)的目标，避免刚上平台就锁到脚下更低层又跳下去(用户2026-09-09)
        cross.sort(key=lambda r: (abs(r[2] - py), r[0]))
        # 维持已选跨层目标(用户2026-09-10治"上层多个误检框X漂移致逐帧横跳"):按【同一层Y(±40)+同一侧方向】强粘,
        # 不再要求X也±40像素吻合——只要还是这一层、这一侧的框就钉住同一个cross,彻底脱检(这层一个框都没了)才用cross[0]重选。
        if cur_cross is not None:
            _ccx, _ccy = cur_cross
            _cside = _dir_to(_ccx, px)
            for (d, cx, cy) in cross:
                _same_layer = abs(cy - _ccy) <= 40
                _same_side = (_cside is None) or (_dir_to(cx, px) == _cside) or (_dir_to(cx, px) is None)
                if _same_layer and _same_side:
                    return _mk('cross', (cx, cy), _dir_to(cx, px), d, cross, tier='cross')
        _, fx, fy = cross[0]
        return _mk('cross', (fx, fy), _dir_to(fx, px), cross[0][0], cross, tier='cross')
    return _mk('idle', None, None, None, tier=None)


def select_combat_target(px, py, monsters, selected_platforms, skill_range, far_range,
                         target_cx, target_cy, target_alive, is_on_platform,
                         get_monster_platform, probe_side, probe_switched, cur_cross=None,
                         attack_y_up=None, attack_y_down=None, allow_cross=True,
                         now=0, lock_time=0, freeze_lock=False, lock_tier=None,
                         group_priority=False, group_radius=0,
                         aoe_y_up=None, aoe_y_down=None, aoe_dual=False,
                         same_platform_fn=None, metric=None):
    """决策核心（阶段一重构）：build_buckets 分桶 → 维持当前锁定 → pick_from_buckets 选新。

    维持规则（用户2026-09-07/10/18）：
      · freeze(爬梯/下跳/瞬移)：死锁当前目标，脱检也沿最后坐标续 cross；
      · in(技能范围内)：钉死站定打；out(同层范围外)：身边没出现能直打的近怪就死咬当前走过去；
      · cross：身边无可直打怪就维持跨层；
      · 让位：out/cross 途中身边刷出技能范围内能直打的怪 → 落 pick_from_buckets 改打近怪；
      · 【规则③ 2026-09-18】in/out 目标本帧从怪表脱检(B怪表已含2秒宽限+时序平滑,过了宽限=真没了)：
        不再沿旧坐标续 cast/pursue(那会钉着没了的怪空打/发呆)，落空到 pick 从本帧真实怪表重选，表空自然 idle；
        cross 例外(跨层怪本就在别的层/屏外,选梯进transit后归梯子状态机管),保留同层同侧粘滞续 cross。
    """
    cand, cross, cast_range = build_buckets(
        px, py, monsters, selected_platforms, skill_range, get_monster_platform,
        attack_y_up, attack_y_down, group_priority, aoe_y_up, aoe_y_down,
        allow_cross, metric, same_platform_fn, target_cx, target_cy)

    if target_cx is not None:
        # 【冻结锁定·用户2026-09-09】爬梯/上下跳/瞬移期间禁止换锁，死咬当前(跨层)目标，到位解冻才解绑重锁。
        if freeze_lock:
            for (d, cx, cy) in cross:   # 冻结目标仍Y差大(还没到同层) → 维持cross继续走梯子/瞬移
                if abs(cx - target_cx) <= 40 and abs(cy - target_cy) <= 50:
                    return _mk('cross', (cx, cy), _dir_to(cx, px), d, cross, tier='cross')
            for (d, cx, cy) in cand:    # 冻结目标已Y相近(爬到同层) → 维持它,按距离cast/pursue,不被别的近身怪顶掉
                if abs(cx - target_cx) <= 40 and abs(cy - target_cy) <= 50:
                    return _mk(('cast' if d <= cast_range else 'pursue'), (cx, cy), _dir_to(cx, px), d,
                               tier='in' if d <= cast_range else 'out')
            # 冻结目标本帧脱检：沿最后已知坐标继续cross(跨层目标本就在别的层),不落到重选、不左右横跳
            return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px), cross, tier='cross')

        # === 非冻结·按"锁定类别 in/out/cross"维持 ===
        locked_in = None        # 本帧仍在同层桶cand里
        locked_cross = None     # 本帧落到跨层桶cross里
        for row in cand:
            if abs(row[1] - target_cx) <= 40 and abs(row[2] - target_cy) <= 50:
                locked_in = row
                break
        for row in cross:
            if abs(row[1] - target_cx) <= 40 and abs(row[2] - target_cy) <= 50:
                locked_cross = row
                break
        in_range_rows = [r for r in cand if r[0] <= cast_range]
        has_in_range = bool(in_range_rows)

        if locked_in is not None:
            ld, lx, ly = locked_in
            if ld <= cast_range:
                # 【in】本帧确在技能范围内(X近且Y在带):钉死站定打,打死(drop)/脱检才换,不被任何远处怪带走
                return _mk('cast', (lx, ly), _dir_to(lx, px), ld, tier='in')
            # 【out】同层但在范围外:仅当身边刷新"技能范围内能直打"的怪才落下方pick让位(唯一合法换锁);
            if has_in_range:
                pass   # 让位：落 pick_from_buckets 改打技能范围内近怪
            else:
                # 没有能直打的近怪 → 死咬当前目标走过去,绝不换成另一只范围外怪/另一侧(治左右横跳)
                return _mk('pursue', (lx, ly), _dir_to(lx, px), ld, tier='out')
        elif locked_cross is not None:
            if has_in_range:
                pass   # 跨层途中身边刷出能直打真怪 → 落 pick 先打(两类规则唯一合法换锁,对称out分支)
            else:
                # 【cross】本帧锁定目标Y仍超带=真跨层且身边无可直打怪:维持cross走梯子,不退化成pursue空走乱跳
                _d, cx, cy = locked_cross
                return _mk('cross', (cx, cy), _dir_to(cx, px), _d, cross, tier='cross')
        else:
            # 锁定目标本帧从怪表脱检。cross 例外保留同层同侧粘滞(跨层怪屏外是常态、选梯后归梯子状态机);
            # 【规则③】in/out 脱检不再沿旧坐标续 cast/pursue——B怪表过了2秒宽限仍没有=真没了,
            # 落空到函数尾 pick_from_buckets 从本帧真实怪表重选(表空=idle),由主线同帧晋升预备怪,不钉旧坐标发呆。
            if lock_tier == 'cross' or (cur_cross is not None and
                                        abs(cur_cross[0] - target_cx) <= 40 and abs(cur_cross[1] - target_cy) <= 50):
                return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px),
                           cross, tier='cross')

    # 无锁定 / 让位 / in·out脱检：统一交给 pick_from_buckets 选一只当前最优怪
    return pick_from_buckets(px, py, cand, cross, cast_range,
                             group_priority, group_radius, aoe_dual, cur_cross)


def pick_next(px, py, monsters, selected_platforms, skill_range, get_monster_platform,
              attack_y_up, attack_y_down, group_priority=False, group_radius=0,
              aoe_y_up=None, aoe_y_down=None, aoe_dual=False, allow_cross=True,
              metric=None, same_platform_fn=None, exclude=None, cur_cross=None):
    """B识别线程专用：算"假设当前怪没了，下一只打谁"的预备怪 next（不画锁定框、不发键，纯后台备胎）。
    标准带分桶(无锁定、不放宽)，先把 current(exclude，容差±40X/±50Y)剔除，再按与主线完全相同的 pick 规则选最优。
    返回 select 同款 _mk dict（target/state/tier/group/cross_candidates）；无备胎时 target=None。"""
    cand, cross, cast_range = build_buckets(
        px, py, monsters, selected_platforms, skill_range, get_monster_platform,
        attack_y_up, attack_y_down, group_priority, aoe_y_up, aoe_y_down,
        allow_cross, metric, same_platform_fn, None, None)
    if exclude is not None:
        _ex, _ey = exclude
        cand = [r for r in cand if abs(r[1] - _ex) > 40 or abs(r[2] - _ey) > 50]
        cross = [r for r in cross if abs(r[1] - _ex) > 40 or abs(r[2] - _ey) > 50]
    return pick_from_buckets(px, py, cand, cross, cast_range,
                             group_priority, group_radius, aoe_dual, cur_cross)


# ==========================================================================
# 决策2：怪物存活判定（规则4：血条 或 伤害数字，其一存在=没死）
# 关键修正：只对"从未确认活着"的静止目标用1秒X判据；已被命中的真怪即使不动也不丢。
# ==========================================================================

def decide_alive(has_hp, has_dmg):
    """当前帧怪是否活着：血条 or 伤害数字，其一=True"""
    return bool(has_hp or has_dmg)


def lock_status(has_hp, has_dmg, hp_confirmed, gone_frames, attacked=False, can_strike=True, freeze_lock=False):
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
    # 目标当前打不到(跨层上/下层怪或射程外,can_strike=False)时无法靠血条验证死活,分两种(用户2026-09-10两类锁怪):
    #  ①起跳在途 freeze_lock=True:无条件死锁,哪怕空怪/背景也保到登顶或失败才解锁(用户:起跳后绝不换锁);
    #  ②平地未起跳:范围外真怪血条本就时有时无,不因"暂时没看到血条"判死(不涨gone,避免走到一半丢锁→横跳);
    #    但若【已经出手打过 attacked】仍无血条无伤害=确证空怪/背景/尸体,平地照样drop清掉
    #    (治:没起跳时死框/上层误检被永久保在锁定/cross里→钉空坐标碎步、拿死框选不到梯呆站)。
    if not can_strike:
        if has_hp and not hp_confirmed:
            hp_confirmed = True
        if (not freeze_lock) and attacked and (not hp_confirmed) and not has_hp and not has_dmg:
            return {"alive": False, "drop": True, "hp_confirmed": hp_confirmed, "gone_frames": 0}
        return {"alive": alive, "drop": False, "hp_confirmed": hp_confirmed, "gone_frames": 0}
    # 【规则②·用户2026-09-18定稿，真怪/空怪统一"一帧就换"】只要已经出手(attacked已在调用方含"出手后新帧+
    # POST_STRIKE反馈窗"双门,用的不是出手前旧帧)且这一帧【血条、伤害数字都没有】=怪打死了/空怪/背景,立刻drop,
    # 不再做"连续3帧没血条"计数(用户:没有血条也没有数字,一帧就换,要不会一直空打)。
    # 没出手(attacked=False:刚锁/还在走近/出手前摇)绝不丢——既不会误杀真怪,也不会钉着空框(走近到能出手自然会判)。
    drop = bool(attacked and not has_hp and not has_dmg)
    # 首次检测到血条 = 攻击命中确认
    if has_hp and not hp_confirmed:
        hp_confirmed = True
    return {"alive": alive, "drop": drop, "hp_confirmed": hp_confirmed, "gone_frames": 0}


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
                aoe_y_up=None, aoe_y_down=None, aoe_dual=False, can_strike=True, lock_tier=None,
                same_platform_fn=None, metric=None, fallback_next=None):
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
        ls = lock_status(has_hp, has_dmg, hp_confirmed, gone_frames, attacked, can_strike, freeze_lock)
    # 停步出手线=技能射程4/5(与select_combat_target内一致):主攻走到这条线内才施放,(4/5,满射程]继续走近不站定空打
    cast_range = max(1, int(skill_range * 4 // 5))
    # 【阶段一·同帧晋升】旧current被判死(_dropped)或根本没锁 → 同帧用B线程预备怪 fallback_next 顶替(promoted),
    # current一死0等待立刻接手,不等下一检测帧、不靠重置节流(治"打完一波发呆几秒")。
    # drop善后(空怪拉黑/跳高降级)由调用方拿 drop_pos=【旧怪坐标】处理——绝不能把刚顶替上来的next当空怪拉黑。
    _dropped = bool(lock and ls["drop"])
    _drop_pos = (lcx, lcy) if _dropped else None
    if _dropped or lock is None:
        eff_lock = fallback_next
        _promoted = bool(fallback_next)
    else:
        eff_lock = lock
        _promoted = False
    d = select_combat_target(px, py, monsters, selected_platforms, skill_range, far_range,
                            (eff_lock[0] if eff_lock else None),
                            (eff_lock[1] if eff_lock else None),
                            ls["alive"], is_on_platform, get_monster_platform,
                            probe_side, probe_switched, cur_cross, attack_y_up, attack_y_down,
                            allow_cross, now, lock_time, freeze_lock, lock_tier, group_priority, group_radius,
                            aoe_y_up, aoe_y_down, aoe_dual, same_platform_fn=same_platform_fn, metric=metric)
    # 技能施放决策
    skill = 'none'
    if d['target'] is not None and d['dist'] is not None:
        aoe_count = 0
        for (x1, y1, x2, y2, _s) in monsters:
            mcx = (x1 + x2) // 2
            mcy = y2
            if abs(mcx - px) <= aoe_range and abs(mcy - py) <= aoe_range:
                aoe_count += 1
        skill = decide_attack(d['dist'], cast_range, aoe_range, aoe_count,
                              main_cd_ok, aoe_cd_ok)
    d['alive'] = ls['alive']
    d['drop'] = _dropped          # 旧current本帧是否被判死(善后判据)
    d['drop_pos'] = _drop_pos     # 被判死的旧current坐标(空怪拉黑/跳高降级必须用它,不能用新顶替的target)
    d['promoted'] = _promoted     # 本帧是否已用预备怪next同帧顶替(调用方据此重置新目标生死字段)
    d['hp_confirmed'] = ls['hp_confirmed']
    d['gone_frames'] = ls['gone_frames']
    d['skill'] = skill
    d['cross_candidates'] = d.get('cross_candidates', [])
    d['tier'] = d.get('tier')   # in=技能范围内/out=同层范围外/cross=跨层,调用方回传作下一帧维持依据
    return d
