# -*- coding: utf-8 -*-
"""第二步根因修复(1/2) combat_logic.py:候选池分三档(同层直打plane/跳高slope/跨层cross)。
根因:开跳高时 attack_y_up 被抬到跳高上限200,同层站直能打(Y<=主攻带100)和必须跳高(Y100~200)
的怪混进同一个cand按Y近逐帧重排,同层/上层来回换锁,主线high_slope每次new_target被重置起跳节奏,
跳-打-跳从没做完→钉地空打发呆。
改法(用户2026-09-23拍板):
 1) build_buckets 新增 slope_y_up(跳高上限);attack_y_up 回归"主攻同层上沿"(100)。
    返回 (cand,cross,cast_range,slope_rows):cand=同层档(含X>=300先走近的远处怪);
    slope_rows=主攻上沿<高度<=跳高上限且X<300的上层怪(cand坐标子集,标记用);cross=跳高都够不着/下方超带。
 2) pick:同层档非空只在同层档选(群怪/单攻原逻辑);同层档清空才选slope(state='slope',tier='slope',
    X<=skill_range原地跳打,否则pursue走近);slope也空才cross;再空idle。
 3) select维持:slope锁钉死不被同层新怪打断(判死/脱检才放);plane锁让位只看同层档近身;
    cross维持中同层或slope任一可达即落pick(不必爬梯);脱检按上帧tier续(slope续slope)。
纯函数切片替换,row三元组结构不变(只多返回一个并行slope列表),最小波及。"""
import io, sys, ast

p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py'
raw = io.open(p, 'rb').read()
crlf = b'\r\n' in raw
has_bom = raw.startswith(b'\xef\xbb\xbf')
cc = raw.decode('utf-8-sig')
NL = '\r\n' if crlf else '\n'

def seg(a, b):
    i = cc.index(a); j = cc.index(b)
    return i, j, cc[i:j]

# ---------- 新 build_buckets ----------
new_build = '''def build_buckets(px, py, monsters, selected_platforms, skill_range,
                  get_monster_platform, attack_y_up, attack_y_down,
                  group_priority=False, aoe_y_up=None, aoe_y_down=None,
                  allow_cross=True, metric=None, same_platform_fn=None,
                  slope_y_up=None):
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
    for (x1, y1, x2, y2, _score) in monsters:
        _mt = metric.get((x1, y1, x2, y2)) if metric else None
        if _mt is not None:
            cx, cy, x_gap, dy = _mt
        else:
            cx = (x1 + x2) // 2
            cy = y2
            x_gap = abs(cx - px)
            dy = cy - py
        if selected_platforms:
            pf = get_monster_platform(cx, cy)
            if pf:
                if (pf.get('id', 0) + 1) not in selected_platforms:
                    continue
            else:
                continue
        if x_gap >= CROSS_X_MAX:
            # X差超300:不管Y在哪一层都先pursue水平走近,靠近后仍超可达带才落cross(用户:X差>=300先走过去)
            cand.append((x_gap, cx, cy))
            continue
        if dy < 0:
            _ay = -dy
            if _pool_y_up is not None and _ay <= _pool_y_up:
                cand.append((x_gap, cx, cy))                          # 同层:主攻带内站直/走近能打
            elif slope_y_up is not None and _ay <= slope_y_up:
                cand.append((x_gap, cx, cy))                          # 同层档占位(供维持匹配)
                slope_rows.append((x_gap, cx, cy))                    # 跳高:主攻够不到、跳高够得到
            else:
                if allow_cross:
                    cross.append((x_gap, cx, cy))                     # 跨层:跳高都够不着→梯子
        else:
            if _pool_y_down is None or dy <= _pool_y_down:
                cand.append((x_gap, cx, cy))
            else:
                if allow_cross:
                    cross.append((x_gap, cx, cy))                     # 下方超下带→下跳/下梯
    return cand, cross, cast_range, slope_rows


'''

# ---------- 新 pick_from_buckets ----------
new_pick = '''def pick_from_buckets(px, py, cand, cross, cast_range,
                       group_priority=False, group_radius=0, aoe_dual=False, cur_cross=None,
                       slope_rows=None, skill_range=None):
    """无锁定/需要让位时选一只当前最优怪。严格分档优先级(用户2026-09-23):
       同层直打档plane(技能范围内>走近) → 跳高档slope(同层清空才选) → 跨层cross → idle。
    slope_rows: build_buckets 返回的跳高怪(坐标是cand子集);为空=没开跳高/无跳高怪,退化为纯同层逻辑。"""
    _skeys = set((r[1], r[2]) for r in (slope_rows or []))
    plane = [r for r in cand if (r[1], r[2]) not in _skeys] if _skeys else list(cand)
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
        d, cx, cy = plane[0]
        return _mk('pursue', (cx, cy), _dir_to(cx, px), d, tier='out')
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
        d, cx, cy = cross[0]
        return _mk('cross', (cx, cy), _dir_to(cx, px), d, cross, tier='cross')
    return _mk('idle', None, None, None)


'''

# ---------- 新 select_combat_target ----------
new_select = '''def select_combat_target(px, py, monsters, selected_platforms, skill_range, far_range,
                         target_cx, target_cy, target_alive, is_on_platform,
                         get_monster_platform, probe_side, probe_switched, cur_cross=None,
                         attack_y_up=None, attack_y_down=None, allow_cross=True,
                         now=0, lock_time=0, freeze_lock=False, lock_tier=None,
                         group_priority=False, group_radius=0,
                         aoe_y_up=None, aoe_y_down=None, aoe_dual=False,
                         same_platform_fn=None, metric=None, slope_y_up=None):
    """决策核心:build_buckets 三档分桶 → 维持当前锁定 → pick_from_buckets 选新。

    分档(用户2026-09-23定稿,治同层/跳高混池逐帧换锁):
      · plane 同层档(Y在主攻带,站直/走近能打)非空:一切决策只在plane档,跳高/跨层怪不参选;
      · plane 清空才进 slope 跳高档;slope 锁定后【钉死】——本帧仍在怪表就一心跳打,不被同层新刷怪打断,
        判死(无血无伤drop)/脱检才放手(让high_slope跳-打-跳完整做完,不再刚起跳就被换锁重置);
      · slope 也空才 cross 走梯子。
    每帧怪表/坐标/距离全用当帧最新,无冻结、无宽限续命、无黑名单、无预选next。
    """
    cand, cross, cast_range, slope_rows = build_buckets(
        px, py, monsters, selected_platforms, skill_range, get_monster_platform,
        attack_y_up, attack_y_down, group_priority, aoe_y_up, aoe_y_down,
        allow_cross, metric, same_platform_fn, slope_y_up)

    _skeys = set((r[1], r[2]) for r in slope_rows)
    plane = [r for r in cand if (r[1], r[2]) not in _skeys]
    plane_in_range = [r for r in plane if r[0] <= cast_range]

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
            # 锁定目标本帧从怪表脱检(YOLO漏帧/特效遮挡/硬裁)。
            # 仍活着(target_alive=血条或伤害数字在)就按上帧档位续锁续打,跳打/原地打都不打断;
            # 真死了(血条、伤害都没)才落pick重选最近(表空=idle),绝不沿旧坐标空打。
            if target_alive:
                if lock_tier == 'slope':
                    return _mk('slope', (target_cx, target_cy), _dir_to(target_cx, px),
                               abs(target_cx - px), tier='slope')
                return _mk('cast', (target_cx, target_cy), _dir_to(target_cx, px),
                           abs(target_cx - px), tier='in')
            if allow_cross and lock_tier == 'cross':
                return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px),
                           abs(target_cx - px), cross, tier='cross')

    # 无锁定 / 让位 / 脱检判死:统一交 pick 按 同层→跳高→跨层 优先级选当前最优怪
    return pick_from_buckets(px, py, cand, cross, cast_range,
                             group_priority, group_radius, aoe_dual, cur_cross,
                             slope_rows=slope_rows, skill_range=skill_range)


'''

# 切片替换 build / pick / select
i1, j1, _ = seg('def build_buckets', 'def pick_from_buckets')
i2, j2, _ = seg('def pick_from_buckets', 'def select_combat_target')
i3, j3, _ = seg('def select_combat_target', 'def decide_alive')
cc = cc[:i1] + new_build + cc[j1:i2] + new_pick + cc[j2:i3] + new_select + cc[j3:]

# ---------- combat_step:签名/调用/docstring 透传 slope_y_up ----------
old_sig = "        same_platform_fn=None, metric=None):\n"
# combat_step 结尾签名(文件里 combat_step 的 metric=None):,select 的已带 slope_y_up。精确锚 combat_step 段
assert cc.count("same_platform_fn=None, metric=None):") == 1, "combat_step签名锚不唯一"
cc = cc.replace("same_platform_fn=None, metric=None):",
                "same_platform_fn=None, metric=None, slope_y_up=None):", 1)

old_doc = "      state: 'idle'|'switch'|'pursue'|'cast'|'cross'"
assert cc.count(old_doc) == 1, "state docstring 锚丢失"
cc = cc.replace(old_doc, "      state: 'idle'|'switch'|'pursue'|'cast'|'slope'|'cross'", 1)

old_call = "                            aoe_y_up, aoe_y_down, aoe_dual, same_platform_fn=same_platform_fn, metric=metric)"
assert cc.count(old_call) == 1, "combat_step→select调用锚丢失"
cc = cc.replace(old_call,
                "                            aoe_y_up, aoe_y_down, aoe_dual, same_platform_fn=same_platform_fn,\n"
                "                            metric=metric, slope_y_up=slope_y_up)", 1)

# AST 自检
ast.parse(cc)
out = cc.replace('\n', NL)
data = out.encode('utf-8')
if has_bom:
    data = b'\xef\xbb\xbf' + data
io.open(p, 'wb').write(data)
print("OK combat_logic 三档分桶+slope状态 已落盘; CRLF=%s BOM=%s" % (crlf, has_bom))
