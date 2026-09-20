# -*- coding: utf-8 -*-
"""纯最近清理·第二批:删死参/死键+订正错注释(不改任何运行逻辑)。
combat(无BOM): build_buckets删target_cx/cy死形参+调用实参;删drop_pos死键;订正维持带/滞回/freeze/拉黑注释。
maple(带BOM): packet删drop_pos键;订正两处拉黑/黑名单注释。
freeze_lock/cur_cross/same_platform_fn 形参保留(跨层/绿线预留)只改注释。全内存+唯一断言,失败不写回。"""
import io, py_compile, re

CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"
MP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"

def apply(path, enc, repls, label):
    with io.open(path, "r", encoding=enc, newline="") as f:
        s = f.read()
    assert "\r\n" not in s
    for old, new in repls:
        n = s.count(old)
        assert n == 1, "[%s] 锚点命中%d次(应1): %r" % (label, n, old[:40])
        s = s.replace(old, new)
    with io.open(path, "w", encoding=enc, newline="") as f:
        f.write(s)
    py_compile.compile(path, doraise=True)
    print(label, "OK")

# ---------------- combat_logic.py (无BOM) ----------------
c_repls = []

# C1 删悬空"分类滞回带宽/维持带"注释块(常量LOCK_HOLD_Y_BAND已删,注释成尸体)
c_repls.append((
'# 分类滞回带宽(px,用户2026-09-10治cross/pursue逐帧横跳):已锁定目标/在途跨层目标/近身怪(进停步线)分桶时,\n'
'# 攻击Y带上、下各放宽这么多形成"维持带",吸收怪框脚Y与人物跳中基点在阈值两侧的边界抖动;新的远处怪仍用原窄带。\n'
'# 必须远小于层间Y差(LAYER_Y_GAP=150):真跨层怪Y差≈150,不会被这点放宽误纳同层。\n\n',
''))

# C2 CROSS_X_HYST 注释订正为跨层预留
c_repls.append((
'# 已锁定目标用 skill_range+本滞回 作为"维持cross"宽线,吸收射程边界逐帧抖动,不在pursue/cross间横跳。\n'
'CROSS_X_HYST = 30',
'# (跨层预留·当前纯最近未引用)未来跨层模式可作射程边界滞回,避免pursue/cross逐帧横跳。\n'
'CROSS_X_HYST = 30'))

# C3 build_buckets 删 target_cx/target_cy 死形参(same_platform_fn保留=绿线预留)
c_repls.append((
'                  allow_cross=True, metric=None, same_platform_fn=None,\n'
'                  target_cx=None, target_cy=None):',
'                  allow_cross=True, metric=None, same_platform_fn=None):'))

# C4 build docstring 删维持带那条,换成same_platform_fn说明
c_repls.append((
'    target_cx/cy 传当前锁定怪时，仅对它用更宽的"维持带"分桶（吸收边界抖动）；B预选无锁定传 None=全用标准带。\n',
'    same_platform_fn 为绿线选台预留,当前自由打怪传 None(函数体不使用)。\n'))

# C5 select 调 build_buckets 删 target_cx/target_cy 实参
c_repls.append((
'        attack_y_up, attack_y_down, group_priority, aoe_y_up, aoe_y_down,\n'
'        allow_cross, metric, same_platform_fn, target_cx, target_cy)',
'        attack_y_up, attack_y_down, group_priority, aoe_y_up, aoe_y_down,\n'
'        allow_cross, metric, same_platform_fn)'))

# C6 select docstring 整段改写为纯最近现状
c_repls.append((
'    维持规则（用户2026-09-07/10/18）：\n'
'      · freeze(爬梯/下跳/瞬移)：死锁当前目标，脱检也沿最后坐标续 cross；\n'
'      · in(技能范围内)：钉死站定打；out(同层范围外)：身边没出现能直打的近怪就死咬当前走过去；\n'
'      · cross：身边无可直打怪就维持跨层；\n'
'      · 让位：out/cross 途中身边刷出技能范围内能直打的怪 → 落 pick_from_buckets 改打近怪；\n'
'      · 【规则③ 2026-09-18】in/out 目标本帧从怪表脱检(B怪表已含2秒宽限+时序平滑,过了宽限=真没了)：\n'
'        不再沿旧坐标续 cast/pursue(那会钉着没了的怪空打/发呆)，落空到 pick 从本帧真实怪表重选，表空自然 idle；\n'
'        cross 例外(跨层怪本就在别的层/屏外,选梯进transit后归梯子状态机管),保留同层同侧粘滞续 cross。\n',
'    纯最近规则（用户2026-09-20定稿，同层 allow_cross=False）：\n'
'      · 每帧怪表/坐标/距离全用当帧最新，无冻结、无宽限续命、无黑名单、无预选next；\n'
'      · in(技能范围内 ld≤cast_range)：钉死站定打到判死；out(同层范围外)：不锁死，每帧落pick按(|Y差|,X差)重选最近，刷近立刻换；\n'
'      · 目标本帧脱检(漏帧/被剔)：一律落 pick 从当帧真实怪表重选最近，表空=idle，绝不沿旧坐标续命；\n'
'      · cross(跨层)：同层模式物理关闭(allow_cross=False 不产 cross)；仅未来跨层模式 allow_cross=True 且上帧 tier=cross 才续给梯子状态机。\n'
'    形参 freeze_lock/cur_cross/same_platform_fn 为跨层/绿线预留，同层传 False/None/None，函数体不据此续命。\n'))

# C7 lock_status 注释订正(freeze无条件死锁分支已不存在)
c_repls.append((
'    # 目标当前打不到(跨层上/下层怪或射程外,can_strike=False)时无法靠血条验证死活,分两种(用户2026-09-10两类锁怪):\n'
'    #  ①起跳在途 freeze_lock=True:无条件死锁,哪怕空怪/背景也保到登顶或失败才解锁(用户:起跳后绝不换锁);\n'
'    #  ②平地未起跳:范围外真怪血条本就时有时无,不因"暂时没看到血条"判死(不涨gone,避免走到一半丢锁→横跳);\n'
'    #    但若【已经出手打过 attacked】仍无血条无伤害=确证空怪/背景/尸体,平地照样drop清掉\n'
'    #    (治:没起跳时死框/上层误检被永久保在锁定/cross里→钉空坐标碎步、拿死框选不到梯呆站)。\n',
'    # 目标当前打不到(射程外/走近中,can_strike=False)时无法靠血条验证死活:范围外真怪血条时有时无,\n'
'    # 不因暂时没看到血条判死(gone恒0,避免走到一半丢锁→横跳);但若【已出手 attacked】仍无血条无伤害=\n'
'    # 确证空怪/背景/尸体照样drop。(freeze_lock 为跨层起跳预留形参,同层恒False,本函数不据此无条件保锁)\n'))

# C8a 删 _drop_pos 计算行
c_repls.append((
'    _dropped = bool(lock and ls["drop"])\n'
'    _drop_pos = (lcx, lcy) if _dropped else None\n',
'    _dropped = bool(lock and ls["drop"])\n'))

# C8b 删 drop_pos 死键
c_repls.append((
"    d['drop'] = _dropped          # 旧current本帧是否被判死(善后判据)\n"
"    d['drop_pos'] = _drop_pos     # 被判死的旧current坐标(空怪拉黑/跳高降级必须用它,不能用新顶替的target)\n",
"    d['drop'] = _dropped          # 旧current本帧是否被判死(善后判据;纯最近只放手当帧重选,不再给坐标拉黑)\n"))

apply(CP, "utf-8", c_repls, "COMBAT")

# 改后断言: build_buckets 函数体内不得再引用 target_cx/target_cy; 全文无 _drop_pos/drop_pos
with io.open(CP, "r", encoding="utf-8", newline="") as f:
    cc = f.read()
bseg = cc[cc.index("def build_buckets"):cc.index("def pick_from_buckets")]
assert "target_cx" not in bseg and "target_cy" not in bseg, "build_buckets体内仍引用target_cx/cy"
assert "drop_pos" not in cc and "_drop_pos" not in cc, "combat仍残留drop_pos"

# ---------------- maple_route_ui.py (带BOM) ----------------
m_repls = []
# M1 packet 删 drop_pos 键
m_repls.append((
"            'drop': _drop, 'drop_pos': _dl.get('drop_pos'),\n",
"            'drop': _drop,\n"))
# M2 drop善后注释
m_repls.append((
"        # --- drop善后(动作层):B判死,主线把旧坐标拉黑1秒+清出手反馈+上屏;跳高打空也走这(=普通空怪,不降级cross) ---",
"        # --- drop善后(动作层):B判死,主线只清出手反馈+上屏+当帧重选(纯最近不拉黑位置);跳高打空也走这(=普通空怪,不降级cross) ---"))
# M3 B线程docstring黑名单注释
m_repls.append((
"        跳高打空(怪在面板跳高带内、出手后无血条无伤)=普通空怪drop、1秒黑名单换一只,绝不降级cross;",
"        跳高打空(怪在面板跳高带内、出手后无血条无伤)=普通空怪drop、当帧重选最近一只,绝不降级cross;"))

apply(MP, "utf-8-sig", m_repls, "MAPLE")

with io.open(MP, "r", encoding="utf-8-sig", newline="") as f:
    mm = f.read()
assert "drop_pos" not in mm, "maple仍残留drop_pos"
print("CLEANUP2_ALL_OK")
