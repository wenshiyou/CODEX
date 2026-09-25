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
  锁定目标本帧脱检(列表里没有)绝不对旧坐标空打，立刻从列表重选真实存在的最近怪(用户2026-09-07)。
"""

# 锁定最短维持时长(ms)：锁定一只怪后至少稳定打这么久，不被其他怪抢目标(用户2026-09-07：锁定最少1秒一次)
# 【2026-09-10停用·保留常量】用户定稿"锁了就钉死、只被技能范围内近怪替换",不再有"满1秒才允许换簇"的动态换簇,此常量当前无引用。

# === 群怪换簇阈值(用户2026-09-09旧方案,2026-09-10停用·保留常量) ===
# 旧:锁簇满1秒后另一簇"更多≥3只且更近"就动态换过去。新定稿(用户2026-09-10):首次选定第一群后钉死,不管另一侧变得更多/更近
# 都不换,先打完第一群(该簇清空/drop)再重选;走向范围外怪途中仅被"技能范围内能直打近怪"替换。故下列阈值当前无引用。
GROUP_SWITCH_NEAR = 200     # (停用)当前簇与另一簇"到人物最近距离差"≤200 才允许换簇
GROUP_SWITCH_FAR = 300      # (停用)距离差≥300 绝不换
GROUP_SWITCH_MIN_MORE = 3   # (停用)另一簇比当前簇多≥3只才算"更多"

# 一个整层的屏幕Y差(用户2026-09-15):怪和人Y差达到这个值=铁定在上下另一层,哪怕绿线same_platform判成同平台也不许破格当同层
# (治"头顶整层怪被同录制平台破格→误cast原地空打、目标在左右横跳的抖动");缓坡/透视Y差小于此值仍可破格按同层走近打。
LAYER_Y_GAP = 150

# 跨层X滞回带宽(px,用户2026-09-11定稿"要不要上梯子必须走到X范围内再判,范围外先水平走过去"):
# 新怪:X差>技能射程一律先按同层走近(pursue),只有X进技能射程仍Y超带才落cross找梯子/下台;
# (跨层预留·当前纯最近未引用)未来跨层模式可作射程边界滞回,避免pursue/cross逐帧横跳。
CROSS_X_HYST = 30

# 【用户2026-09-17定稿·跨层(要梯子/下跳)唯一条件;2026-09-18修正】cross高度线不写死,一律按面板自定义的
# "这套打法实际够得着的高度"判定,与主线执行层(high_slope跳高段/_below2下台段)同一口径:
# 上方=跳高打上限slope_jump_y_max(没开跳高/跳高打空降级=主攻上带attack_y_up),下方=attack_y_down;群攻再按aoe_y放宽。
# 超过该可达带=原地/跳高都够不到=cross走梯子/下跳;X差>=CROSS_X_MAX再高也先水平走近,靠近后仍超可达带才跨层。
CROSS_X_MAX = 300    # 跨层最大X差:X差>=300先pursue水平走近,靠近后仍超面板可达带才跨层(用户:X差<300)
LOCK_GRACE_MS = 500   # 同层范围外旧锁连续脱检宽限:此时间内沿用旧锁走近,抗YOLO漏帧全屏横跳

# 平台模式(单台single+多台multi同一分支)同台Y容差(用户2026-09-26 50->40):只锁与人物|Y差|<40的同台怪,
# 超40=别的台一律不锁(单台cross全关;多台仅对选中台方向走cross跨台);自由random模式不用此值、不受限。
MANUAL_SINGLE_Y_GAP = 40


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
                  slope_y_up=None, combat_mode='random',
                  manual_same_y=MANUAL_SINGLE_Y_GAP,
                  allow_cross_up=True, allow_cross_down=True,
                  manual_x_band=None):
    """按"这套打法实际够得着的高度"把怪分三档(用户2026-09-23定稿,与主线high_slope同一口径):
      · 同层档 cand(元素(x_gap,cx,cy)):站直/走近/原地主攻够得到——
          上方 |dy|<=attack_y_up(主攻上沿,开跳高也只给主攻带100,不含跳高段);
          下方 dy<=attack_y_down;以及 X差>=CROSS_X_MAX 的远处怪(先水平走近,走近前不判档,用户:X>=300先走过去)。
      · 跳高档 slope_rows(是cand坐标的子集标记):开跳高(slope_y_up非None)且 attack_y_up<|dy|<=slope_y_up、
          X差<CROSS_X_MAX 的上层怪——必须high_slope跳-打-跳,站着主攻够不到但跳高够得到。
      · 跨层 cross:跳高都够不着(|dy|>slope_y_up,或没开跳高却超主攻带)、下方超下带、X差<CROSS_X_MAX——走梯子/下跳。
    同层档非空时上层怪一律不参选(用户:同层清空才去跳高/跨层),从根上杜绝同层/上层混池逐帧抢锁。
    返回 (cand, cross, cast_range, slope_rows)。"""
    cast_range = max(1, int(skill_range * 4 // 5))
    cand = []
    cross = []
    slope_rows = []
    _pool_y_up = attack_y_up
    _pool_y_down = attack_y_down
    if group_priority and aoe_y_up is not None:
        _pool_y_up = max(_pool_y_up, aoe_y_up)
        if aoe_y_down is not None:
            _pool_y_down = max(_pool_y_down, aoe_y_down)
    # === 两套打怪规则(用户2026-09-24):同一套分桶代码按 combat_mode 收窄同层Y带/跨层方向,random逐行等价现状 ===
    #  random 自由全图:同层带=面板(群攻放宽)、双向可跨层、跳高照开,不受manual_same_y限制;
    #  single(单台)/multi(多台)=平台模式同一分支(用户2026-09-26):同台Y带统一=manual_same_y(40)、跳高全关;
    #    唯一区别是跨台cross——single全关(上下层怪都不锁),multi仅放行"还有更高/更低选中台"的方向(allow_cross_up/down)。
    if combat_mode in ('single', 'multi'):
        eff_up, eff_down = manual_same_y, manual_same_y
        eff_slope = None
        if combat_mode == 'single':
            cross_up = cross_down = False
        else:
            cross_up, cross_down = bool(allow_cross_up), bool(allow_cross_down)
    else:
        eff_up, eff_down = _pool_y_up, _pool_y_down
        cross_up = cross_down = bool(allow_cross)
        eff_slope = slope_y_up
    for (x1, y1, x2, y2, _score) in monsters:
        _mt = metric.get((x1, y1, x2, y2)) if metric else None
        if _mt is not None:
            cx, cy, x_gap, dy = _mt
        else:
            cx = (x1 + x2) // 2
            cy = y2
            x_gap = abs(cx - px)
            dy = cy - py
        # 平台台界X带门(用户2026-09-26):manual_x_band=(屏幕xlo,xhi),主线以人物屏幕点+光点绿线数据界按
        # 瞬移实测X比例反算;平台(单台/多台同一分支)只锁带内怪,带外=本台绿线外(相邻台/屏外)一律不进任何桶,
        # 从源头不锁/不追/不瞬移台外怪(治同高异台远怪把人拉出台、越线回退拉锯)。自由random不传(None)=不过滤。
        if combat_mode in ('single', 'multi') and manual_x_band is not None:
            _bxlo, _bxhi = manual_x_band
            if cx < _bxlo or cx > _bxhi:
                continue
        if selected_platforms:
            pf = get_monster_platform(cx, cy)
            if pf:
                if (pf.get('id', 0) + 1) not in selected_platforms:
                    continue
            else:
                continue
        if x_gap >= CROSS_X_MAX:
            # X差超300先pursue水平走近(用户:X>=300先走过去);平台模式(单台/多台)远处怪也要Y在同台40带内才走近,否则=别台丢弃
            if combat_mode in ('single', 'multi'):
                if (dy < 0 and -dy < eff_up) or (dy >= 0 and dy < eff_down):
                    cand.append((x_gap, cx, cy))
                continue
            cand.append((x_gap, cx, cy))
            continue
        if dy < 0:
            _ay = -dy
            if combat_mode in ('single', 'multi'):
                _within = _ay < eff_up
            else:
                _within = eff_up is not None and _ay <= eff_up
            if _within:
                cand.append((x_gap, cx, cy))                          # 同层:主攻带内站直/走近能打
            elif eff_slope is not None and _ay <= eff_slope:
                cand.append((x_gap, cx, cy))                          # 同层档占位(供维持匹配)
                slope_rows.append((x_gap, cx, cy))                    # 跳高:主攻够不到、跳高够得到
            else:
                if cross_up:
                    cross.append((x_gap, cx, cy))                     # 跨层上层→梯子(单台关/多台仅上方还有选中台)
        else:
            if combat_mode in ('single', 'multi'):
                _within = dy < eff_down
            else:
                _within = (eff_down is None or dy <= eff_down)
            if _within:
                cand.append((x_gap, cx, cy))
            else:
                if cross_down:
                    cross.append((x_gap, cx, cy))                     # 下方超下带→下跳/下梯(单台关/多台仅下方还有选中台)
    return cand, cross, cast_range, slope_rows, eff_up, eff_down


def pick_from_buckets(px, py, cand, cross, cast_range,
                       group_priority=False, group_radius=0, aoe_dual=False, cur_cross=None,
                       slope_rows=None, skill_range=None, side_anchor_x=None,
                       allow_switch=True):
    """无锁定/需要让位时选一只当前最优怪。严格分档优先级(用户2026-09-23):
       同层直打档plane(技能范围内>走近) → 跳高档slope(同层清空才选) → 跨层cross → idle。
    slope_rows: build_buckets 返回的跳高怪(坐标是cand子集);为空=没开跳高/无跳高怪,退化为纯同层逻辑。"""
    _skeys = set((r[1], r[2]) for r in (slope_rows or []))
    plane = [r for r in cand if (r[1], r[2]) not in _skeys] if _skeys else list(cand)
    def _side(rows):
        # 方向锚点同侧过滤(治drop/脱检后全局pick无方向横穿):近身cast在外层先选,走到这里的都是要移动
        # 的out/cross怪。同侧有怪只在同侧延续;同侧当帧空(YOLO漏检/特效遮挡常见、下帧常恢复)且换向宽限
        # 未满(allow_switch=False)时返回[]->本轮不横穿、站住idle等恢复;只有持续一个宽限窗同侧真空
        # (allow_switch=True)才全量换向,旧方向真清空,既不左右抢也不呆住。
        if side_anchor_x is None:
            return rows
        _want_right = side_anchor_x > px
        _ss = [r for r in rows if (r[1] > px) == _want_right]
        if _ss:
            return _ss
        return rows if allow_switch else []
    if plane:
        in_attack_rows = [r for r in plane if r[0] <= cast_range]
        if group_priority and group_radius and group_radius > 0:
            gw = best_group_window(px, py, plane, group_radius, aoe_dual)
            if gw is not None:
                (tx, ty), gsize, gnear, gside = gw
                in_win = [r for r in in_attack_rows
                          if abs(r[1] - tx) <= group_radius and abs(r[2] - ty) <= group_radius]
                if in_win:
                    return _mk('cast', (tx, ty), gside, min(r[0] for r in in_win),
                               group=(tx, ty, gsize), tier='in')
                near_plane = [r for r in plane if r[0] <= cast_range]
                if not near_plane:
                    return _mk('pursue', (tx, ty), gside, gnear,
                               group=(tx, ty, gsize), tier='out')
        if in_attack_rows:
            in_attack_rows.sort(key=lambda r: (abs(r[2] - py), r[0]))
            d, cx, cy = in_attack_rows[0]
            return _mk('cast', (cx, cy), _dir_to(cx, px), d, tier='in')
        plane.sort(key=lambda r: (abs(r[2] - py), r[0]))
        _po = _side(plane)
        if _po:
            d, cx, cy = _po[0]
            return _mk('pursue', (cx, cy), _dir_to(cx, px), d, tier='out')
        # 同侧空且换向宽限未满:不横穿,落到slope/cross(同样门控),都空则idle站住等漏检恢复
    # 同层档清空 → 选跳高档(开跳高且有跳高怪):X<=技能射程原地high_slope跳打,否则先水平走近
    if slope_rows:
        _sl = sorted(slope_rows, key=lambda r: (abs(r[2] - py), r[0]))
        d, cx, cy = _sl[0]
        if skill_range is not None and d <= skill_range:
            return _mk('slope', (cx, cy), _dir_to(cx, px), d, tier='slope')
        return _mk('pursue', (cx, cy), _dir_to(cx, px), d, tier='slope')
    if cross:
        if cur_cross:
            for row in cross:
                if abs(row[1] - cur_cross[0]) <= 40 and abs(row[2] - cur_cross[1]) <= 50:
                    d, cx, cy = row
                    return _mk('cross', (cx, cy), _dir_to(cx, px), d, cross, tier='cross')
        cross.sort(key=lambda r: (abs(r[2] - py), r[0]))
        _co = _side(cross)
        if _co:
            d, cx, cy = _co[0]
            return _mk('cross', (cx, cy), _dir_to(cx, px), d, cross, tier='cross')
        # 同侧cross空且宽限未满:不横穿到异侧梯子,idle站住
    return _mk('idle', None, None, None)


def select_combat_target(px, py, monsters, selected_platforms, skill_range, far_range,
                         target_cx, target_cy, target_alive, is_on_platform,
                         get_monster_platform, probe_side, probe_switched, cur_cross=None,
                         attack_y_up=None, attack_y_down=None, allow_cross=True,
                         now=0, lock_time=0, freeze_lock=False, lock_tier=None,
                         group_priority=False, group_radius=0,
                         aoe_y_up=None, aoe_y_down=None, aoe_dual=False,
                         same_platform_fn=None, metric=None, slope_y_up=None,
                         combat_mode='random', manual_same_y=MANUAL_SINGLE_Y_GAP,
                         allow_cross_up=True, allow_cross_down=True,
                         lock_grace_ms=10**9,
                         side_anchor_x=None,
                         manual_x_band=None):
    """决策核心:build_buckets 三档分桶 → 维持当前锁定 → pick_from_buckets 选新。

    分档(用户2026-09-23定稿,治同层/跳高混池逐帧换锁):
      · plane 同层档(Y在主攻带,站直/走近能打)非空:一切决策只在plane档,跳高/跨层怪不参选;
      · plane 清空才进 slope 跳高档;slope 锁定后【钉死】——本帧仍在怪表就一心跳打,不被同层新刷怪打断,
        判死(无血无伤drop)/脱检才放手(让high_slope跳-打-跳完整做完,不再刚起跳就被换锁重置);
      · slope 也空才 cross 走梯子。
    每帧怪表/坐标/距离全用当帧最新,无冻结、无宽限续命、无黑名单、无预选next。
    """
    cand, cross, cast_range, slope_rows, eff_up, eff_down = build_buckets(
        px, py, monsters, selected_platforms, skill_range, get_monster_platform,
        attack_y_up, attack_y_down, group_priority, aoe_y_up, aoe_y_down,
        allow_cross, metric, same_platform_fn, slope_y_up,
        combat_mode, manual_same_y, allow_cross_up, allow_cross_down,
        manual_x_band=manual_x_band)

    _skeys = set((r[1], r[2]) for r in slope_rows)
    plane = [r for r in cand if (r[1], r[2]) not in _skeys]
    plane_in_range = [r for r in plane if r[0] <= cast_range]
    _anchor_x = target_cx if target_cx is not None else side_anchor_x  # drop当帧target清空,用上一锁X做方向锚

    if target_cx is not None:
        locked_in = None        # 本帧仍在同层/跳高桶cand里
        locked_is_slope = False
        locked_cross = None     # 本帧落到跨层桶cross里
        for row in cand:
            if abs(row[1] - target_cx) <= 40 and abs(row[2] - target_cy) <= 50:
                locked_in = row
                locked_is_slope = (row[1], row[2]) in _skeys
                break
        for row in cross:
            if abs(row[1] - target_cx) <= 40 and abs(row[2] - target_cy) <= 50:
                locked_cross = row
                break

        if locked_in is not None:
            ld, lx, ly = locked_in
            if locked_is_slope:
                # 【slope钉死】跳高目标本帧仍在:X进技能射程就一心slope跳打,否则pursue走近;
                # 不看同层档有没有新怪(同层怪等这只跳打判死/脱检后再选),high_slope动作不被打断。
                if skill_range is not None and ld <= skill_range:
                    return _mk('slope', (lx, ly), _dir_to(lx, px), ld, tier='slope')
                return _mk('pursue', (lx, ly), _dir_to(lx, px), ld, tier='slope')
            if ld <= cast_range:
                # 【plane·in】本帧确在技能范围内:钉死站定打,判死(drop)/脱检才换,不被任何远处怪带走
                return _mk('cast', (lx, ly), _dir_to(lx, px), ld, tier='in')
            # 【plane·out】走近段锁死:同层档近身(技能范围内)没怪就不换方向,避免左右各一怪来回抢;
            # 只有同层档刷出技能范围内近身怪才让位(跳高slope怪不算,同层未清空不转跳高)。
            if not plane_in_range:
                return _mk('pursue', (lx, ly), _dir_to(lx, px), ld, tier='out')
        elif locked_cross is not None:
            # 跨层途中:同层档或跳高档任一可达就落pick先打(不必爬梯);两者都空才维持cross走梯子
            if plane or slope_rows:
                pass
            else:
                _d, cx, cy = locked_cross
                return _mk('cross', (cx, cy), _dir_to(cx, px), _d, cross, tier='cross')
        else:
            _gdy0 = target_cy - py
            # 平台模式(单台/多台同一分支):旧锁本帧已掉出同台Y带(人物跨层/掉台/越线回退后,目标在别的台),
            # 不管它是否还活着都不许续cast/pursue对别台空打、更不许瞬移出台——立即落pick按当帧怪表重选:
            # 同台plane空、跨台cross也空->idle/巡游;多台cross有选中台怪才走跨台。自由模式不受此限。
            if combat_mode in ('single', 'multi') and not (-eff_up < _gdy0 < eff_down):
                return pick_from_buckets(px, py, cand, cross, cast_range,
                                         group_priority, group_radius, aoe_dual, cur_cross,
                                         slope_rows=slope_rows, skill_range=skill_range,
                                         side_anchor_x=_anchor_x,
                                         allow_switch=(_anchor_x is None or lock_grace_ms >= LOCK_GRACE_MS))
            # 锁定目标本帧从怪表脱检(YOLO漏帧/特效遮挡/硬裁)。
            # 仍活着(target_alive=血条或伤害数字在)就按上帧档位续锁续打,跳打/原地打都不打断;
            # 真死了(血条、伤害都没)才落pick重选最近(表空=idle),绝不沿旧坐标空打。
            if target_alive:
                if lock_tier == 'slope':
                    return _mk('slope', (target_cx, target_cy), _dir_to(target_cx, px),
                               abs(target_cx - px), tier='slope')
                return _mk('cast', (target_cx, target_cy), _dir_to(target_cx, px),
                           abs(target_cx - px), tier='in')
            # 判死/无反馈脱检(用户2026-09-24定稿,治"锁背景/旧cross钉死呆住"):
            #  旧坐标仍在同层可出手位(X进停步线、Y在本模式同层带)→照原位补打一次("先打了再说"),
            #  出手满窗仍无血无伤由lock_status判drop换怪,最多空打一下、不连打背景;
            #  上层cross/超远/超同层带→不补;旧"判死cross无条件续旧坐标"已物理删(自我续命根因),
            #  落pick按当帧最新怪表重选:身边同层怪立刻接管,同层空且cross桶有怪重选一只cross,全空idle。
            _gdy = target_cy - py
            if combat_mode in ('single', 'multi'):
                _gin_y = (-eff_up < _gdy < eff_down)
            else:
                _gin_y = _in_band(target_cy, py, eff_up, eff_down)
            # 怪表完全空(这帧一只怪都没识别到)=真没怪/整帧漏检,落pick待机找怪、绝不凭空打;
            # 仅当帧怪表非空(周围有怪/锁定目标漏检或锁到背景)且旧坐标在同层技能位,才照原位补打一下确认。
            if monsters and abs(target_cx - px) <= cast_range and _gin_y:
                return _mk('cast', (target_cx, target_cy), _dir_to(target_cx, px),
                           abs(target_cx - px), tier='in')
            # 【脱检宽限·短记忆】近身档空、旧锁同层范围外、连续脱检未满LOCK_GRACE_MS时,沿用旧锁坐标继续
            # 走近(pursue只走不打,不会空打/钉尸体):滤掉YOLO单帧/几帧漏检、特效遮挡造成的全屏横跳,不呆;
            # 持续脱检超宽限(旧怪真消失)才落到下面同侧滞回/全局pick重选。近身档刷怪由末尾pick选cast优先接管;
            # cross跨层锁不粘(跨层维持另走locked_cross)。
            if (lock_tier != 'cross' and not plane_in_range
                    and abs(target_cx - px) > cast_range
                    and lock_grace_ms < LOCK_GRACE_MS):
                return _mk('pursue', (target_cx, target_cy), _dir_to(target_cx, px),
                           abs(target_cx - px), tier='out')
            # 【方向滞回·用户定稿规则】旧锁是同层范围外(pursue)且本帧脱检、技能范围内又无怪可直打时,
            # 不许横穿到屏幕另一侧、仅因那边远怪Y差小几px就换锁(用户:范围外锁只被近身怪替换,不换另一方向
            # 仅近一点点的远怪;没近身怪就不换锁,免得左右抢)。只在旧目标【同侧】当帧范围外怪里选X最接近旧
            # 目标的一只延续走近;同侧一只不剩(旧方向真清空)才放给末尾pick全局重选。延续的仍是当帧真实怪,
            # 不冻结坐标、不沿旧坐标续命、不sleep,YOLO单帧漏检/换框被同侧连续性滤掉。
            if not plane_in_range and abs(target_cx - px) > cast_range:
                _old_right = target_cx > px
                _same_side = [r for r in plane
                              if r[0] > cast_range and (r[1] > px) == _old_right]
                if _same_side:
                    _same_side.sort(key=lambda r: abs(r[1] - target_cx))
                    _sd, _scx, _scy = _same_side[0]
                    return _mk('pursue', (_scx, _scy), _dir_to(_scx, px), _sd, tier='out')

    # 无锁定 / 让位 / 脱检判死:统一交 pick 按 同层→跳高→跨层 优先级选当前最优怪
    return pick_from_buckets(px, py, cand, cross, cast_range,
                             group_priority, group_radius, aoe_dual, cur_cross,
                             slope_rows=slope_rows, skill_range=skill_range,
                             side_anchor_x=_anchor_x,
                             allow_switch=(_anchor_x is None or lock_grace_ms >= LOCK_GRACE_MS))


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
    # 目标当前打不到(射程外/走近中,can_strike=False)时无法靠血条验证死活:范围外真怪血条时有时无,
    # 不因暂时没看到血条判死(gone恒0,避免走到一半丢锁→横跳);但若【已出手 attacked】仍无血条无伤害=
    # 确证空怪/背景/尸体照样drop。(freeze_lock 为跨层起跳预留形参,同层恒False,本函数不据此无条件保锁)
    if not can_strike:
        if (has_hp or has_dmg) and not hp_confirmed:
            hp_confirmed = True
        if attacked and (not hp_confirmed) and not has_hp and not has_dmg:
            return {"alive": False, "drop": True, "hp_confirmed": hp_confirmed, "gone_frames": 0}
        return {"alive": alive, "drop": False, "hp_confirmed": hp_confirmed, "gone_frames": 0}
    # 【规则②·用户2026-09-18定稿，真怪/空怪统一"一帧就换"】只要已经出手(attacked已在调用方含"出手后新帧+
    # POST_STRIKE反馈窗"双门,用的不是出手前旧帧)且这一帧【血条、伤害数字都没有】=怪打死了/空怪/背景,立刻drop,
    # 不再做"连续3帧没血条"计数(用户:没有血条也没有数字,一帧就换,要不会一直空打)。
    # 没出手(attacked=False:刚锁/还在走近/出手前摇)绝不丢——既不会误杀真怪,也不会钉着空框(走近到能出手自然会判)。
    drop = bool(attacked and not has_hp and not has_dmg)
    # 首次见到血条或伤害数字 = 攻击命中确认(用户2026-09-21:二者出一即真怪)
    if (has_hp or has_dmg) and not hp_confirmed:
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
                same_platform_fn=None, metric=None, slope_y_up=None,
                combat_mode='random', manual_same_y=MANUAL_SINGLE_Y_GAP,
                allow_cross_up=True, allow_cross_down=True,
                lock_grace_ms=10**9, manual_x_band=None):
    """组合 select_combat_target + lock_status + decide_attack，得到本tick完整的战斗决策。

    参数: 见各部分；now/lock_time 单位ms。
    返回 dict:
      state: 'idle'|'switch'|'pursue'|'cast'|'slope'|'cross'
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
    # 用户2026-09-20定稿:判活血条区域=两部分并集。A=怪物基点X±35(Y在人物上方180px内,血条在怪头顶);
    # B=人物技能范围(人物X±skill_range,Y向上180px)。血条落A或B任一=打着怪/怪活着。垂直范围2026-09-20由150改180。
    has_hp = False
    if lock:
        for (bx, by, bw, bh) in hp_bars:
            bxc = bx + bw / 2
            byc = by + bh / 2
            in_a = (lcx - 35) <= bxc <= (lcx + 35) and (lcy - 150) <= byc <= (lcy - 55)   # A:怪物基点X前35~后35,Y基点上方55~150(排怪身体/近头顶背景)
            in_b = abs(bxc - px) <= skill_range and (py - 150) <= byc <= (py - 55)  # B:血条中心X离人物基点X不超过技能范围,Y基点上方55~150
            if in_a or in_b:
                has_hp = True
                break
    # 存活/空怪判定（仅已锁定）：血条连续2帧消失=打死；出手后无血条无伤害=空怪。不再有任何"锁定时长到点丢弃"。
    ls = {"alive": bool(lock), "drop": False, "hp_confirmed": hp_confirmed,
          "gone_frames": gone_frames}
    if lock:
        ls = lock_status(has_hp, has_dmg, hp_confirmed, gone_frames, attacked, can_strike, freeze_lock)
    # 停步出手线=技能射程4/5(与select_combat_target内一致):主攻走到这条线内才施放,(4/5,满射程]继续走近不站定空打
    cast_range = max(1, int(skill_range * 4 // 5))
    # 纯最近(用户2026-09-20):判死/无锁→本帧无锁落select,select内pick当帧最新怪表选最近,同帧0等待,不再预备怪顶替
    _dropped = bool(lock and ls["drop"])
    eff_lock = None if (_dropped or lock is None) else lock
    d = select_combat_target(px, py, monsters, selected_platforms, skill_range, far_range,
                            (eff_lock[0] if eff_lock else None),
                            (eff_lock[1] if eff_lock else None),
                            ls["alive"], is_on_platform, get_monster_platform,
                            probe_side, probe_switched, cur_cross, attack_y_up, attack_y_down,
                            allow_cross, now, lock_time, freeze_lock, lock_tier, group_priority, group_radius,
                            aoe_y_up, aoe_y_down, aoe_dual, same_platform_fn=same_platform_fn,
                            metric=metric, slope_y_up=slope_y_up,
                            combat_mode=combat_mode, manual_same_y=manual_same_y,
                            allow_cross_up=allow_cross_up, allow_cross_down=allow_cross_down,
                            lock_grace_ms=lock_grace_ms,
                            side_anchor_x=(lock[0] if lock else None),
                            manual_x_band=manual_x_band)
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
    d['drop'] = _dropped          # 旧current本帧是否被判死(善后判据;纯最近只放手当帧重选,不再给坐标拉黑)
    d['hp_confirmed'] = ls['hp_confirmed']
    d['gone_frames'] = ls['gone_frames']
    d['skill'] = skill
    d['cross_candidates'] = d.get('cross_candidates', [])
    d['tier'] = d.get('tier')   # in=技能范围内/out=同层范围外/cross=跨层,调用方回传作下一帧维持依据
    return d
