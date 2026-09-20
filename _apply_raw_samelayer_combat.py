# -*- coding: utf-8 -*-
"""combat_logic 同层最原始化(无BOM/UTF-8/LF):C1超带不参选 + C2走近段每帧重选 + C3 freeze脱检cross守卫。
锚点一律用纯ASCII代码行,避开中文引号;每处唯一断言,失败不写回。"""
import io, py_compile

COMBAT = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"
MAPLE = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"

with io.open(COMBAT, "r", encoding="utf-8", newline="") as f:
    c = f.read()
assert "\r\n" not in c, "combat含CRLF,预期LF"

# ---- C1 build_buckets: 超带怪 allow_cross=False 时不参选 ----
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
assert c.count(c1_old) == 1, "C1锚点%d次" % c.count(c1_old)
c = c.replace(c1_old, c1_new)

# ---- C2 select: 删 locked_in 分支里 out 的"死咬pursue"(纯ASCII行锚定),保留cast锁死 ----
cast_line = "                return _mk('cast', (lx, ly), _dir_to(lx, px), ld, tier='in')\n"
pur_line = "                return _mk('pursue', (lx, ly), _dir_to(lx, px), ld, tier='out')\n"
assert c.count(cast_line) == 1, "cast_line %d" % c.count(cast_line)
assert c.count(pur_line) == 1, "pur_line %d" % c.count(pur_line)
_i = c.index(cast_line) + len(cast_line)
_j = c.index(pur_line) + len(pur_line)
assert _j > _i and "has_in_range" in c[_i:_j], "C2区间异常"
c = c[:_i] + ("            # 【out·最原始·用户2026-09-20】走近段(没进技能范围)不锁死,每帧用当帧最新怪表落pick重选最近,刷近立刻换;\n"
              "            # 技能范围内(上方cast)才锁到打死。\n") + c[_j:]

# ---- C3 freeze脱检的无条件return cross加allow_cross守卫(纯ASCII单行锚定) ----
cross_line = "            return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px), cross, tier='cross')\n"
assert c.count(cross_line) == 1, "cross_line %d" % c.count(cross_line)
cross_new = ("            if allow_cross:   # 同层调试期关cross:冻结脱检也不走梯,落pick/表空idle(用户2026-09-20)\n"
             "                return _mk('cross', (target_cx, target_cy), _dir_to(target_cx, px), abs(target_cx - px), cross, tier='cross')\n")
c = c.replace(cross_line, cross_new)

with io.open(COMBAT, "w", encoding="utf-8", newline="") as f:
    f.write(c)

py_compile.compile(COMBAT, doraise=True)
py_compile.compile(MAPLE, doraise=True)
print("COMBAT_RAW_SAMELAYER_OK")
