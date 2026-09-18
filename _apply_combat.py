# -*- coding: utf-8 -*-
"""阶段一脚本A:重构 combat_logic.py
1) 抽 build_buckets(分桶) / pick_from_buckets(无锁选新) 纯函数,B线程预选与主线选怪共用同一实现;
2) select_combat_target 改为 build_buckets→维持段→pick_from_buckets;脱检 in/out 按规则③落空重选(cross粘滞保留);
3) 新增 pick_next() 供B线程算预备怪(标准带分桶+排除current);
4) lock_status 真怪/空怪统一"出过手+出手后新帧+无血无伤=一帧drop"(规则②);
5) combat_step 加 fallback_next:current死/无锁同帧晋升(promoted),回传 drop_pos=旧怪坐标(善后用,防拉黑新怪)。
机械抽取部分(build_buckets/pick_from_buckets)与原 select 逐行等价,由离线对照单测验证。"""
import io, os, sys, py_compile

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "combat_logic.py")
raw = open(P, "rb").read()
had_bom = raw.startswith(b"\xef\xbb\xbf")
src = raw.decode("utf-8-sig")
src = src.replace("\r\n", "\n")

def rep1(old, new, tag):
    global src
    c = src.count(old)
    assert c == 1, "[%s] 期望唯一命中,实际 %d 处" % (tag, c)
    src = src.replace(old, new, 1)
    print("OK 替换:", tag)

# ============ 1) 整段替换 select_combat_target(110-369) → build_buckets + pick_from_buckets + select + pick_next ============
start = src.index("def select_combat_target(")
end = src.index("def decide_alive")
decision2_banner = (
    "# ==========================================================================\n"
    "# 决策2：怪物存活判定（规则4：血条 或 伤害数字，其一存在=没死）\n"
    "# 关键修正：只对\"从未确认活着\"的静止目标用1秒X判据；已被命中的真怪即使不动也不丢。\n"
    "# ==========================================================================\n"
)

new_block = '''def build_buckets(px, py, monsters, selected_platforms, skill_range,
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
    cand 优先（同层清空才取 cross）；群怪优先走最佳窗，单攻范围内按X近、范围外按Y近再X近。返回 _mk dict。"""
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
        # ===================== 单攻选怪(用户2026-09-10定稿:范围内按X、范围外按Y,排序键唯一不左右为难) =====================
        # ①技能范围内有能直打的:只按X近选(不看Y)→cast站定打;②全都在范围外:才按Y相近优先、再X近→pursue走过去
        if in_attack_rows:
            in_attack_rows.sort(key=lambda r: r[0])
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


''' + decision2_banner + "\n"
src = src[:start] + new_block + src[end:]
print("OK 整段替换: select_combat_target → build_buckets/pick_from_buckets/select/pick_next")

# ============ 2) lock_status：can_strike=True 真怪/空怪统一一帧 drop（规则②）============
old_ls = '''    drop = False
    if hp_confirmed and not has_hp:
        # 确认过血条+现在血条没了=怪死了/离开；伤害数字会残留0.5~1秒不算活着凭据
        # → 连续3帧没血条才弃锁定(用户2026-09-11:2→3,怪多/特效/掉帧时血条偶发漏检一两帧,连续2帧会把真怪误判死→清锁重选旁边怪=一圈怪间左右抖)
        gone_frames = gone_frames + 1
        if gone_frames >= 3:
            drop = True
    else:
        gone_frames = 0
    # 空怪丢弃(用户2026-09-11加 not hp_confirmed 守卫):只有【从没确认到血条】的目标,出手满反馈窗口仍"无血条且无伤害"
    # 才=空怪/背景/尸体→弃;曾见过血条(hp_confirmed=真怪)不走这条单帧丢弃,统一交给上面"血条连续3帧消失"判死,
    # 根治"真怪血条/伤害这一帧恰好漏检→单帧当空怪清掉→锁旁边另一只→又漏检→一圈怪轮流锁、方向左右横跳"。
    if attacked and (not hp_confirmed) and not has_hp and not has_dmg:
        drop = True
    # 首次检测到血条 = 攻击命中确认
    if has_hp and not hp_confirmed:
        hp_confirmed = True
    return {"alive": alive, "drop": drop, "hp_confirmed": hp_confirmed, "gone_frames": gone_frames}'''
new_ls = '''    # 【规则②·用户2026-09-18定稿，真怪/空怪统一"一帧就换"】只要已经出手(attacked已在调用方含"出手后新帧+
    # POST_STRIKE反馈窗"双门,用的不是出手前旧帧)且这一帧【血条、伤害数字都没有】=怪打死了/空怪/背景,立刻drop,
    # 不再做"连续3帧没血条"计数(用户:没有血条也没有数字,一帧就换,要不会一直空打)。
    # 没出手(attacked=False:刚锁/还在走近/出手前摇)绝不丢——既不会误杀真怪,也不会钉着空框(走近到能出手自然会判)。
    drop = bool(attacked and not has_hp and not has_dmg)
    # 首次检测到血条 = 攻击命中确认
    if has_hp and not hp_confirmed:
        hp_confirmed = True
    return {"alive": alive, "drop": drop, "hp_confirmed": hp_confirmed, "gone_frames": 0}'''
rep1(old_ls, new_ls, "lock_status-can_strike True 一帧drop")

# ============ 3) combat_step 形参加 fallback_next ============
old_sig = '''                same_platform_fn=None, metric=None):
    """组合 select_combat_target + lock_status + decide_attack'''
new_sig = '''                same_platform_fn=None, metric=None, fallback_next=None):
    """组合 select_combat_target + lock_status + decide_attack'''
rep1(old_sig, new_sig, "combat_step 形参 fallback_next")

# ============ 4) combat_step 内 eff_lock → 同帧晋升 next ============
old_eff = '''    # 若判定放弃锁定（真怪死了/假怪）→ 本轮重新选目标
    eff_lock = lock if not ls["drop"] else None
    d = select_combat_target(px, py, monsters, selected_platforms, skill_range, far_range,
                            (eff_lock[0] if eff_lock else None),
                            (eff_lock[1] if eff_lock else None),
                            ls["alive"], is_on_platform, get_monster_platform,
                            probe_side, probe_switched, cur_cross, attack_y_up, attack_y_down,
                            allow_cross, now, lock_time, freeze_lock, lock_tier, group_priority, group_radius,
                            aoe_y_up, aoe_y_down, aoe_dual, same_platform_fn=same_platform_fn, metric=metric)'''
new_eff = '''    # 【阶段一·同帧晋升】旧current被判死(_dropped)或根本没锁 → 同帧用B线程预备怪 fallback_next 顶替(promoted),
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
                            aoe_y_up, aoe_y_down, aoe_dual, same_platform_fn=same_platform_fn, metric=metric)'''
rep1(old_eff, new_eff, "combat_step 同帧晋升 fallback_next")

# ============ 5) combat_step 回存 drop/drop_pos/promoted ============
old_save = '''    d['alive'] = ls['alive']
    d['drop'] = ls['drop']
    d['hp_confirmed'] = ls['hp_confirmed']'''
new_save = '''    d['alive'] = ls['alive']
    d['drop'] = _dropped          # 旧current本帧是否被判死(善后判据)
    d['drop_pos'] = _drop_pos     # 被判死的旧current坐标(空怪拉黑/跳高降级必须用它,不能用新顶替的target)
    d['promoted'] = _promoted     # 本帧是否已用预备怪next同帧顶替(调用方据此重置新目标生死字段)
    d['hp_confirmed'] = ls['hp_confirmed']'''
rep1(old_save, new_save, "combat_step 回存 drop_pos/promoted")

# ============ 写回（保持原 BOM 状态，纯 LF）============
out = src.encode("utf-8")
if had_bom:
    out = b"\xef\xbb\xbf" + out
assert b"\r\n" not in out, "出现 CRLF"
with open(P, "wb") as f:
    f.write(out)
py_compile.compile(P, doraise=True)
print("py_compile OK; BOM=%s; 字节数=%d" % (had_bom, len(out)))
