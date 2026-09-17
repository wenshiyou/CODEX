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

# 【用户2026-09-17定稿·跨层(要梯子/下跳)唯一条件】跳高也够不到 且 X差不远:
# abs(Y差)>=CROSS_DY_MIN 且 X差<CROSS_X_MAX 才判cross;X差>=CROSS_X_MAX 再高也先水平走近;Y差<CROSS_DY_MIN(攻击带~跳高可达)原地/跳高打。
CROSS_DY_MIN = 200   # 跨层最小Y差:超过跳高上限、必须梯子/下跳(用户:Y差>=200)
CROSS_X_MAX = 300    # 跨层最大X差:X差>=300先pursue水平走近,靠近后仍Y>=200才跨层(用户:X差<300)


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


def select_combat_target(px, py, monsters, selected_platforms, skill_range, far_range,
                         target_cx, target_cy, target_alive, is_on_platform,
                         get_monster_platform, probe_side, probe_switched, cur_cross=None,
                         attack_y_up=None, attack_y_down=None, allow_cross=True,
                         now=0, lock_time=0, freeze_lock=False, lock_tier=None,
                         group_priority=False, group_radius=0,
                         aoe_y_up=None, aoe_y_down=None, aoe_dual=False,
                         same_platform_fn=None, metric=None):
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
    # 【用户2026-09-10】停步出手距离=技能射程的4/5(如250→200):怪在(cast_range,skill_range]判pursue一直按住走过去,
    # 只有≤cast_range才站定cast开打。治"大圈内(如184/250)被判cast站定、不持续走、只靠转身短按一点点蹭=原地碎步"。
    # skill_range 仍作索敌/纳入圈(决定哪些怪进候选),cast_range 才是"走到这停步出手"线。
    cast_range = max(1, int(skill_range * 4 // 5))
    cand = []    # 可锁定/聚簇池 [(x_gap,cx,cy)]：近怪优先=主攻Y带；群怪优先=群攻Y带(略高略低也进池)
    cross = []   # 连聚簇池Y带都超出=真跨层,走梯子/瞬移

    # 可锁定/聚簇池Y带=这套打法"实际够得着"的上/下高度,普通与群攻一套口径(用户2026-09-11:群攻跳高打和普通一套,
    # 跳得够就原地跳打、不找梯子)。基线=传入attack_y_up(启用跳高打时=跳高上限_sj_max,区间高处怪进cand走high_slope;
    # 未启用=主攻带);群攻技能本身打得更高(aoe_y)时再取更宽,保证没开跳高打时群攻"略高略低也能群"的原行为不变。
    # 【根因】旧写法群攻直接用aoe_y覆盖:开跳高打时aoe(如80)<跳高上限(如150),反把Y差80~150本该跳打的高处怪
    # 划进cross去找梯子=群攻模式跳高打经常检测不到、不跳。取max后开跳高=150(和普通一致),没开=max(60,80)=80(原样)。
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
        # 吸收怪框脚Y、人物跳中py在攻击Y带边界的抖动;一切新怪仍走原窄带,纳入标准一寸不变:
        # 锁定怪不会一帧落cand(pursue)一帧落cross,从根消除两套移动键对消。注意【不能放宽cur_cross】:它是已判跨层、
        # 正在走梯子的目标,必须稳定留在cross(由后面cur_cross维持段负责),放宽会把它拉回cand半路变pursue/cast。
        # 真跨层怪Y差≈层高150,实际攻击Y带60+维持25=85仍远小于150,照样进cross;能否站定直打仍由后面窄带in_range判。
        _is_hold = (target_cx is not None and abs(cx - target_cx) <= 40 and abs(cy - target_cy) <= 50)
        if _is_hold and _pool_y_up is not None:
            _b_up = _pool_y_up + LOCK_HOLD_Y_BAND
            _b_down = (_pool_y_down + LOCK_HOLD_Y_BAND) if _pool_y_down is not None else _pool_y_down
        else:
            _b_up, _b_down = _pool_y_up, _pool_y_down
        # 【用户2026-09-07：找怪不分层，锁定和攻击分开】
        # 锁定只看Y差：Y在攻击范围内(y_ok)=同层怪，进cand优先锁定；Y差大=跨层怪，进cross。
        # 不再用is_on_platform判断本层/别的层（Y差≤150易误判上层怪为同层→标pursue靠近不了→不跨层）。
        # 攻击在选目标后再判断：x_gap<=skill_range→cast，否则→pursue靠近。
        y_ok = _in_band(cy, py, _b_up, _b_down)
        # 【同录制平台破格·用户2026-09-11治"同层缓坡/透视远怪Y差70~180超攻击带→误判cross→无梯子站桩不锁不打"】
        # 怪和人经录制绿线判定属同一条平台(比平台id,非猜Y)→哪怕Y差超攻击带也按同层进cand走过去打;
        # 真在另一条平台上的怪same_pf=False,仍按y_ok落cross走梯子。回调判不出(没录平台/估算不到)返回False=退回纯Y现状,不臆断。
        _same_pf = False
        if same_platform_fn is not None:
            try:
                _same_pf = bool(same_platform_fn(cx, cy))
            except Exception:
                _same_pf = False
        # 【用户2026-09-17定稿·cross唯一条件,固定阈值百分百死守,不再用攻击Y带/X射程线/锁定滞回分桶】
        # ①X差>=300:再高也先pursue水平走近(走近后仍Y>=200才跨层);②abs(Y差)>=200且X<300:跳高也够不到=cross梯子/下跳;
        # ③其余(Y在攻击带~跳高可达,<200):原地打/跳高打/走近,一律cand。选定阶段cand优先、cand空才取cross=同层清空才上梯。
        if x_gap >= CROSS_X_MAX:
            cand.append((x_gap, cx, cy))   # X还很远,先水平走近,不判跨层
        elif abs(dy) >= CROSS_DY_MIN and allow_cross:
            cross.append((x_gap, cx, cy))  # 跳高也够不到、X<300=真要梯子/下跳
        else:
            cand.append((x_gap, cx, cy))   # Y差<200(攻击带/跳高可达):原地打或跳高打或走近

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
                    return _mk('cross', (cx, cy), _dir_to(cx, px), d, cross, tier='cross')
            for (d, cx, cy) in cand:    # 冻结目标已Y相近(爬到同层) → 维持它,按距离cast/pursue,不被别的近身怪顶掉
                if abs(cx - target_cx) <= 40 and abs(cy - target_cy) <= 50:
                    return _mk(('cast' if d <= cast_range else 'pursue'), (cx, cy), _dir_to(cx, px), d,
                               tier='in' if d <= cast_range else 'out')
            # 冻结目标本帧脱检：沿最后已知坐标继续cross(跨层目标本就在别的层),不落到重选、不左右横跳
            return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px), cross, tier='cross')

        # === 非冻结·按"锁定类别 in/out/cross"维持(用户2026-09-10两类锁怪定稿) ===
        # 类别含义:in=技能范围内(Y在带且X≤停步线)可站定直打;out=同层但范围外要走过去;cross=Y超带要跨层。
        # 关键:本帧锁定目标落在哪个桶,就按哪个桶的规则维持,绝不再"只看X"把X近Y远的空框误当范围内钉cast。
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
        # 技能范围内能直打的真怪=同层(Y在带,已进cand)且X进停步出手线
        in_range_rows = [r for r in cand if r[0] <= cast_range]
        has_in_range = bool(in_range_rows)

        if locked_in is not None:
            ld, lx, ly = locked_in
            if ld <= cast_range:
                # 【in】本帧确在技能范围内(X近且Y在带):钉死站定打,打死(drop)/脱检才换,不被任何远处怪带走
                return _mk('cast', (lx, ly), _dir_to(lx, px), ld, tier='in')
            # 【out】同层但在范围外:移动途中,仅当身边刷新"技能范围内能直打"的怪才落下方重选(唯一合法换锁);
            if has_in_range:
                pass
            else:
                # 没有能直打的近怪 → 死咬当前目标走过去,绝不换成另一只范围外怪/另一侧(治左右横跳)
                return _mk('pursue', (lx, ly), _dir_to(lx, px), ld, tier='out')
        elif locked_cross is not None:
            if has_in_range:
                # 跨层途中身边刷出Y在带、X进停步线的能直打真怪 → 落下方重选先打(两类规则唯一合法换锁,对称out分支);
                # 治真机:锁着X近Y远的错层空框(cross)、身边明明有同层真怪却钉着空框不打
                pass
            else:
                # 【cross】本帧锁定目标Y仍超带=真跨层且身边无可直打怪:维持cross走梯子,不退化成pursue空走乱跳
                _d, cx, cy = locked_cross
                return _mk('cross', (cx, cy), _dir_to(cx, px), _d, cross, tier='cross')
        else:
            # 锁定目标本帧完全脱检(检测闪断/被挡/死亡):真死已在combat_step判drop清锚走不到这,这里只处理闪断。
            if lock_tier == 'in':
                # 历史是技能范围内、正在站定输出:单帧闪断也续锁旧目标cast,绝不为身边另一只范围内怪扭头(站定不横跳);
                # "范围内出新怪才换"只针对范围外(out)移动途中。能走到这说明combat_step没判drop=不是真死。
                return _mk('cast', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px), tier='in')
            if has_in_range:
                pass   # out/cross移动途中,身边刷出Y在带、X进停步线的真怪 → 落下方重选(两类规则唯一合法换锁口)
            elif lock_tier == 'cross' or (cur_cross is not None and
                                          abs(cur_cross[0] - target_cx) <= 40 and abs(cur_cross[1] - target_cy) <= 50):
                # 历史就是跨层(或cur_cross吻合):沿最后坐标续cross,不左右横跳、不退化成pursue
                return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px),
                           cross, tier='cross')
            else:
                # 历史是范围外(out)/未知:沿最后坐标续pursue走过去——【绝不cast】,Y没在带就不站定空打(治X近Y远碎步)
                return _mk('pursue', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px), tier='out')

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
                bucket.sort(key=lambda r: r[0])   # 已选数量多的这一侧,桶内按X近(用户2026-09-10:范围内不看Y)
                _d, _cx, _cy = bucket[0]
                _side = 'left' if _cx < px else 'right'
                return _mk('cast', (_cx, _cy), _dir_to(_cx, px), _d,
                           group=(len(bucket), _side), tier='in')
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
        #  (范围外Y近X远也选Y近这只——Y远的多半在别的层,同层迟早走到;确定性排序+锁定钉死,杜绝两只之间反复切换)。
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
        # 维持已选跨层目标(用户2026-09-10治"上层多个误检框X漂移致逐帧横跳"):跨层目标的层Y很稳、X会因不同框跳,
        # 故按【同一层Y(±40)+同一侧方向】强粘,不再要求X也±40像素吻合——只要还是这一层、这一侧的框就钉住同一个cross,
        # 彻底脱检(这一层一个框都没了)才用cross[0]重选。
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
    drop = False
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
                aoe_y_up=None, aoe_y_down=None, aoe_dual=False, can_strike=True, lock_tier=None,
                same_platform_fn=None, metric=None):
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
    # 若判定放弃锁定（真怪死了/假怪）→ 本轮重新选目标
    eff_lock = lock if not ls["drop"] else None
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
    d['drop'] = ls['drop']
    d['hp_confirmed'] = ls['hp_confirmed']
    d['gone_frames'] = ls['gone_frames']
    d['skill'] = skill
    d['cross_candidates'] = d.get('cross_candidates', [])
    d['tier'] = d.get('tier')   # in=技能范围内/out=同层范围外/cross=跨层,调用方回传作下一帧维持依据
    return d
