# -*- coding: utf-8 -*-
"""combat_logic 纯最近锁怪清理(无BOM/UTF-8/LF):
删 MIN_LOCK_HOLD_MS/LOCK_HOLD_Y_BAND死常量、build_buckets维持偏袒_is_hold、select冻结选锁段、
lock_status冻结特例、pick_next预备怪函数、combat_step的fallback_next晋升/promoted。
全部内存操作+唯一断言,任一失败不写回。freeze_lock形参链路保留占位(调用方恒传False)。"""
import io, py_compile, re

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"
with io.open(P, "r", encoding="utf-8", newline="") as f:
    c = f.read()
assert "\r\n" not in c

def cut(s, start_anchor, end_anchor, tag, count_anchor=True):
    global c
    assert c.count(start_anchor) == 1, "%s 起点锚点%d次" % (tag, c.count(start_anchor))
    assert c.count(end_anchor) >= 1, "%s 终点锚点0次" % tag
    si = c.index(start_anchor)
    ei = c.index(end_anchor, si)
    c = c[:si] + c[ei:]

def rep(old, new, tag):
    global c
    assert c.count(old) == 1, "%s 锚点%d次" % (tag, c.count(old))
    c = c.replace(old, new)

# 1. 死常量
rep("MIN_LOCK_HOLD_MS = 1000\n", "", "删MIN_LOCK_HOLD_MS")
rep("LOCK_HOLD_Y_BAND = 25\n", "", "删LOCK_HOLD_Y_BAND")

# 2. build_buckets 维持偏袒段(分类滞回/_is_hold/_b_up/_b_down/y_ok/_same_pf死计算)整段删,保留cross分类
_s2 = "        # 【分类滞回"
_e2 = "        _too_high = "
assert c.count(_s2) == 1 and c.count(_e2) >= 1, "维持段锚点异常"
_si, _ei = c.index(_s2), c.index(_e2)
_repl2 = "        # 【cross条件(用户2026-09-17定稿;高度读面板)】X差>=300先水平走近;X<300且Y超面板可达带=cross(同层关);可达带内cand。\n"
c = c[:_si] + _repl2 + c[_ei:]

# 3. select 冻结选锁段整段删,到"非冻结"维持段前
cut(c, "        # 【冻结锁定", "        # === 非冻结", "删select冻结段")

# 4. lock_status 去掉 freeze_lock 特例(恒不冻结后等价 attacked 直接判)
rep("        if (not freeze_lock) and attacked and (not hp_confirmed) and not has_hp and not has_dmg:",
    "        if attacked and (not hp_confirmed) and not has_hp and not has_dmg:",
    "lock_status去freeze特例")

# 5. 删 pick_next 整个函数(def 到其后第一条分隔线)
si = c.index("def pick_next(")
assert c.count("def pick_next(") == 1
ei = c.index("# ==========================================================================", si)
c = c[:si] + c[ei:]

# 6. combat_step 签名去 fallback_next
rep("                same_platform_fn=None, metric=None, fallback_next=None):",
    "                same_platform_fn=None, metric=None):",
    "combat_step签名去fallback_next")

# 7. 晋升段(旧注释+if/else)整段切片替换为纯最近:判死/无锁→本帧无锁落select当帧重选
_s7 = "    # 【阶段一·同帧晋升】"
_e7 = "    d = select_combat_target("
assert c.count(_s7) == 1 and c.count(_e7) == 1, "晋升段边界异常"
_si7, _ei7 = c.index(_s7), c.index(_e7)
_repl7 = ("    # 纯最近(用户2026-09-20):判死/无锁→本帧无锁落select,select内pick当帧最新怪表选最近,同帧0等待,不再预备怪顶替\n"
          "    _dropped = bool(lock and ls[\"drop\"])\n"
          "    _drop_pos = (lcx, lcy) if _dropped else None\n"
          "    eff_lock = None if (_dropped or lock is None) else lock\n")
c = c[:_si7] + _repl7 + c[_ei7:]

# 8. 删 d['promoted'] 输出整行
pk = "    d['promoted'] = _promoted"
assert c.count(pk) == 1, "promoted行%d次" % c.count(pk)
pi = c.index(pk); pe = c.index("\n", pi) + 1
c = c[:pi] + c[pe:]

# ==== 残留断言(黑科技必须清零) ====
# 死常量名在代码引用删净后,只剩模块docstring注释行,按行清扫
_lines = c.split("\n")
_lines = [ln for ln in _lines if ("MIN_LOCK_HOLD_MS" not in ln and "LOCK_HOLD_Y_BAND" not in ln)]
c = "\n".join(_lines)
for bad in ["pick_next", "fallback_next", "_promoted", "LOCK_HOLD_Y_BAND",
            "MIN_LOCK_HOLD_MS", "_is_hold", "_b_up", "if freeze_lock:"]:
    assert bad not in c, "残留未清: %s" % bad
# freeze_lock 仅允许作为(恒False的)形参/传参占位,不得再有分支逻辑
assert "freeze_lock" in c, "freeze_lock形参链路应保留占位"

with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(c)
py_compile.compile(P, doraise=True)
print("COMBAT_PURE_NEAREST_OK")
