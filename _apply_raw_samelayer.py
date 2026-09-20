# -*- coding: utf-8 -*-
"""同层最原始化(用户2026-09-20):怪表当帧化(删2秒宽限/EMA续命)+技能范围锁死/走近段每帧重选最近+同层关cross。
maple=UTF-8带BOM/LF; combat_logic=UTF-8无BOM/LF。每处锚点必须唯一(count==1),否则报错不写回。"""
import io, sys, py_compile

MAPLE = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
COMBAT = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"

def load(path, bom):
    with io.open(path, "r", encoding="utf-8-sig", newline="") as f:
        s = f.read()
    assert "\r\n" not in s, path + " 含CRLF,预期LF,先停手核对"
    return s

def save(path, s, bom):
    with io.open(path, "w", encoding=("utf-8-sig" if bom else "utf-8"), newline="") as f:
        f.write(s)

def rep(s, old, new, tag):
    c = s.count(old)
    assert c == 1, "%s 锚点命中%d次(应为1),未写回" % (tag, c)
    return s.replace(old, new)

# ============ maple_route_ui.py (带BOM) ============
m = load(MAPLE, True)

# M1 删除 2秒宽限 + temporal时序平滑调用 -> 当帧怪表
m1_old = (
"                    if _merged:   # 怪2秒宽限:本轮空但2秒内有怪则保留,防偶发漏检闪没\n"
"                        self._detect_last_monsters = _merged\n"
"                        self._detect_last_monsters_time = time.time()\n"
"                    elif (time.time() - self._detect_last_monsters_time < 2.0\n"
"                          and self._detect_last_monsters):\n"
"                        _merged = self._detect_last_monsters\n"
"                    _merged = self._temporal_smooth_detections(_merged)  # 单帧漏检不清目标\n"
)
m1_new = (
"                    # 【最原始·用户2026-09-20】怪表只用当帧检出:删2秒宽限、删EMA/跨帧续命,\n"
"                    # 每帧最新怪+当帧人坐标算最新距离;在打(技能范围内)的怪由决策层锁到打死,不靠怪表续命。\n"
)
m = rep(m, m1_old, m1_new, "M1-宽限+temporal调用")

# M4 硬裁注释里"已含2秒宽限/时序平滑续命"措辞更新
m = rep(m, "最终怪表(已含2秒宽限/时序平滑续命)", "最终怪表(当帧检出)", "M4-硬裁注释")

# M3 combat_step 调用 allow_cross 位置参数 True -> False(同层调试期)
m = rep(m,
        "_attacked, _eff_up, _ydn, True, freeze_lock=_freeze,",
        "_attacked, _eff_up, _ydn, False, freeze_lock=_freeze,  # 同层调试期allow_cross=False:不上下梯,超跳高带怪不参选(用户2026-09-20)",
        "M3-allow_cross=False")

# M2 物理删除 _temporal_smooth_detections 方法定义(调用已在M1删除)
assert m.count("def _temporal_smooth_detections") == 1, "temporal定义数异常"
_st = m.index("    def _temporal_smooth_detections(self, merged):")
_ed = m.index("    def _filter_dropped_phantoms", _st)
m = m[:_st] + m[_ed:]
assert "_temporal_smooth_detections" not in m, "temporal仍有残留引用"

save(MAPLE, m, True)

# ============ combat_logic.py (无BOM) ============
c = load(COMBAT, False)

# C1 build_buckets: 超跳高/技能带的怪, allow_cross=False 时不参选(而非塞进cand)
c1_old = (
"        if x_gap >= CROSS_X_MAX:\n"
"            cand.append((x_gap, cx, cy))   # X还很远,先水平走近,不判跨层\n"
"        elif allow_cross and (\n"
"                (_pool_y_up is not None and dy < -_pool_y_up) or      # 怪在上方、超过面板上可达高度=跳高也够不到\n"
"                (_pool_y_down is not None and dy > _pool_y_down)):    # 怪在下方、超过面板下方技能带=够不到\n"
"            cross.append((x_gap, cx, cy))  # 实际够不着、X<300=走梯子/下跳\n"
"        else:\n"
"            cand.append((x_gap, cx, cy))   # 在面板可达带内:原地打/跳高打/走近\n"
)
c1_new = (
"        _too_high = (_pool_y_up is not None and dy < -_pool_y_up)\n"
"        _too_low = (_pool_y_down is not None and dy > _pool_y_down)\n"
"        if x_gap >= CROSS_X_MAX:\n"
"            cand.append((x_gap, cx, cy))   # X还很远,先水平走近,不判跨层\n"
"        elif _too_high or _too_low:\n"
"            if allow_cross:\n"
"                cross.append((x_gap, cx, cy))   # 跳高/技能够不着、X<300=走梯子/下跳(接入跨层时才开)\n"
"            # 同层调试期 allow_cross=False:够不着的高/低层怪本帧不参选、不上梯不下跳(用户2026-09-20)\n"
"        else:\n"
"            cand.append((x_gap, cx, cy))   # 在面板可达带内:原地打/跳高打/走近\n"
)
c = rep(c, c1_old, c1_new, "C1-超带不参选")

# C2 select: 技能范围内cast锁死; 走近段out删除"死咬pursue",落pick每帧重选最近
c2_old = (
"        if locked_in is not None:\n"
"            ld, lx, ly = locked_in\n"
"            if ld <= cast_range:\n"
"                # 【in】本帧确在技能范围内(X近且Y在带):钉死站定打,打死(drop)/脱检才换,不被任何远处怪带走\n"
"                return _mk('cast', (lx, ly), _dir_to(lx, px), ld, tier='in')\n"
"            # 【out】同层但在范围外:仅当身边刷新“技能范围内能直打”的怪才落下方pick让位(唯一合法换锁);\n"
"            if has_in_range:\n"
"                pass   # 让位：落 pick_from_buckets 改打技能范围内近怪\n"
"            else:\n"
"                # 没有能直打的近怪 → 死咬当前目标走过去,绝不换成另一只范围外怪/另一侧(治左右横跳)\n"
"                return _mk('pursue', (lx, ly), _dir_to(lx, px), ld, tier='out')\n"
)
c2_new = (
"        if locked_in is not None:\n"
"            ld, lx, ly = locked_in\n"
"            if ld <= cast_range:\n"
"                # 【in·用户2026-09-20】怪进技能范围=正在打,锁到打死为止,不被任何怪顶掉(判死/脱检才换)\n"
"                return _mk('cast', (lx, ly), _dir_to(lx, px), ld, tier='in')\n"
"            # 【out·最原始】还在走近段(没进技能范围)不锁死:每帧用当帧最新怪表落pick重选最近,\n"
"            # 身边/前方刷出更近的怪立刻换最近(用户:每帧最新,除技能范围内在打的怪外不维持)。\n"
)
c = rep(c, c2_old, c2_new, "C2-out每帧重选")

# C3 freeze脱检: 同层关cross时不硬返回cross,落pick/表空idle
c3_old = (
"            # 冻结目标本帧脱检：沿最后已知坐标继续cross(跨层目标本就在别的层),不落到重选、不左右横跳\n"
"            return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px), cross, tier='cross')\n"
)
c3_new = (
"            # 冻结目标本帧脱检:跨层期(allow_cross)沿最后坐标续cross;同层期关cross则落pick重选/表空idle,不走梯\n"
"            if allow_cross:\n"
"                return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px), cross, tier='cross')\n"
)
c = rep(c, c3_old, c3_new, "C3-freeze脱检cross守卫")

save(COMBAT, c, False)

# ============ 编译验证 ============
py_compile.compile(MAPLE, doraise=True)
py_compile.compile(COMBAT, doraise=True)
print("RAW_SAMELAYER_APPLY_OK")
