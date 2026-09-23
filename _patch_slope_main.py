# -*- coding: utf-8 -*-
"""第二步根因修复(2/2) maple_route_ui.py 主线:让B三档分档真正驱动,一个脑子一套动作做完。
 A. B发布_publish_combat_decision:
    attack_y_up 改传主攻同层上沿_yup(不再_eff_up抬到跳高上限致混池);新增slope_y_up=跳高上限;
    跳高腾空窗(起跳后SLOPE_AIR_MS)py用起跳落地锚点Y、metric作废(不拿空中Y重算分档/换锁/血条B区)。
 B. 主线combat tick:
    state='slope'进战斗分支;pursue通用块对state=slope放行(落high_slope自管走近+跳打);
    瞬移闸门tier!=slope(跳高流程含走近段不瞬移插队);
    high_slope 唯一由B state='slope'驱动,参照怪=B锁定点,物理删旧sticky/就近另找/platforms门控"第二脑子";
    起跳写锚点Y/腾空窗。init与解卡放弃处初始化/清零锚点。"""
import io, ast

p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
raw = io.open(p, 'rb').read()
assert raw.startswith(b'\xef\xbb\xbf'), "maple应为utf-8-sig BOM"
cc = raw.decode('utf-8-sig').replace('\r\n', '\n')
NL = '\r\n'

def rep(old, new, n=1):
    global cc
    c = cc.count(old)
    assert c == n, "锚点命中%d次(期望%d): %r" % (c, n, old[:60])
    cc = cc.replace(old, new)

# ---- P1(先P2再P1) 解卡放弃目标处清腾空锚点(15399-15400,_debug_log串唯一) ----
rep(
"        self._slope_high_last_jump = 0\n"
"        _debug_log(\"[防卡死] 连续移动受阻(%s)，判定目标(%d,%d)打不到→放弃，下帧纯最近重选\" % (why or \"卡住\", cx, cy))",
"        self._slope_high_last_jump = 0\n"
"        self._slope_anchor_y = None\n"
"        self._slope_air_until = 0\n"
"        _debug_log(\"[防卡死] 连续移动受阻(%s)，判定目标(%d,%d)打不到→放弃，下帧纯最近重选\" % (why or \"卡住\", cx, cy))")

# ---- P2 init 腾空锚点字段(用1553行尾注释串锚定,避开等号对齐空格) ----
rep(
"治腾空误判;用户2026-09-18)\n",
"治腾空误判;用户2026-09-18)\n"
"        self._slope_anchor_y = None                # 跳高打起跳落地锚点Y:腾空窗内B锁怪/分档用它,防空中Y污染(用户2026-09-23)\n"
"        self._slope_air_until = 0                  # 腾空窗截止时刻ms=起跳时刻+SLOPE_AIR_MS\n")

# ---- P3 B发布:px,py=ch 后接腾空锚点替换 ----
rep(
"        px, py = ch\n"
"        _skr = int(fc.get(\"atk1_distance\", 150) or 150)",
"        px, py = ch\n"
"        # 跳高腾空窗(起跳后SLOPE_AIR_MS):B用起跳落地锚点Y算分档/距离/血条B区,不拿空中Y重算换锁(治腾空时同层/上层分类错乱、刚起跳就换锁)\n"
"        _slope_air = now_ms < getattr(self, '_slope_air_until', 0)\n"
"        if _slope_air and getattr(self, '_slope_anchor_y', None) is not None:\n"
"            py = self._slope_anchor_y\n"
"        _skr = int(fc.get(\"atk1_distance\", 150) or 150)")

# ---- P4 删 _eff_up 死定义(attack_y_up不再抬到跳高上限;_sjmax/_yup改在P5直接用) ----
rep(
"        _eff_up = _sjmax if _slope_on else _yup   # 面板跳高带内=cand可跳高打;永不因打空收回(删旧slope_blocked降级)\n",
"")

# ---- P5 combat_step 实参:attack_y_up传主攻带;腾空metric作废;新增slope_y_up ----
rep(
"            _attacked, _eff_up, _ydn, True, freeze_lock=False,  # 跨层已开allow_cross=True(用户2026-09-21):超跳高带怪产cross走上梯/下跳;cur_cross仍传None防续命恒真漏帧误cross呆住",
"            _attacked, _yup, _ydn, True, freeze_lock=False,  # attack_y_up传主攻同层上沿(跳高段改走slope_y_up分档,不再抬到跳高上限致同层/跳高混池);allow_cross=True超跳高带产cross")
rep(
"            same_platform_fn=None, metric=metric)",
"            same_platform_fn=None, metric=(None if _slope_air else metric),  # 腾空窗:用空中Y算的metric作废,改以锚点Y现算\n"
"            slope_y_up=(_sjmax if _slope_on else None))  # 跳高上限:主攻带之上~此高度=slope跳高档,同层档清空才选")

# ---- P6 主线战斗分支收 state=slope ----
rep(
"        if _dl['state'] in ('cast', 'pursue') and _dl['target']:",
"        if _dl['state'] in ('cast', 'pursue', 'slope') and _dl['target']:")

# ---- P7 通用pursue走近块对 state=slope 放行(落high_slope自管) ----
rep(
"        if not in_attack_range:   # 架构B:走近还是站定统一听仲裁(实控=R-50进/R+25出迟滞;关时in_attack_range=t_dist<=stop_range,等价原t_dist>stop_range走近)",
"        if not in_attack_range and _dl.get('state') != 'slope':   # state=slope(X进射程)跳过通用pursue/瞬移,落high_slope自管走近+跳打;slope走近段(state=pursue/tier=slope,X250~300)仍由此走近")

# ---- P8 瞬移闸门:跳高slope流程(含走近段)不瞬移插队 ----
rep(
"            _tp_ready = (bool(_tp_key) and self._climb_state == 'none'\n"
"                         and getattr(self, '_locked_ladder', None) is None\n"
"                         and not _tp_blk and now - self._combat_last_h_teleport > TP_COOLDOWN_MS)",
"            _tp_ready = (bool(_tp_key) and self._climb_state == 'none'\n"
"                         and getattr(self, '_locked_ladder', None) is None\n"
"                         and _dl.get('tier') != 'slope'   # 跳高slope流程(含X250~300走近段)不瞬移插队,防白闪打断跳-打-跳(用户2026-09-23)\n"
"                         and not _tp_blk and now - self._combat_last_h_teleport > TP_COOLDOWN_MS)")

# ---- P9 参照怪/门控整段(17376 _sref 起 至 17406"下方够不着"注释前)换成 state 驱动 ----
i9a = cc.index("        _sref = getattr(self, '_slope_ref', None)")
i9b = cc.index("        # 下方够不着：怪脚Y-人脚Y 超出下方攻击范围")
new9 = (
"        # 跳高打唯一由B决策state='slope'驱动(B是锁怪唯一脑子,用户2026-09-23):B已保证同层档清空、怪Y在跳高带、\n"
"        # X≤技能射程。参照怪=B锁定点本身;物理删旧sticky/就近另找/platforms门控这个\"第二脑子\"——它曾和B锁不是同一只、\n"
"        # 又每帧被new_target重置起跳节奏,致跳-打-跳从没做完、钉地空打(08:47日志实锤)。state非slope一律不自行起跳。\n"
"        if _dl.get('state') == 'slope':\n"
"            _ref_x, _ref_y = t_cx, t_cy\n"
"            self._slope_ref = (t_cx, t_cy)\n"
"            high_slope = True\n"
"        else:\n"
"            _ref_x, _ref_y = t_cx, t_cy\n"
"            high_slope = False\n"
"        _above2 = py_layer - _ref_y   # 怪在人物实时Y上方多少px(正=上方;仅high_slope分支用)\n"
)
cc = cc[:i9a] + new9 + cc[i9b:]

# ---- P10 起跳写落地锚点Y/腾空窗(17455 wait_jump起跳) ----
rep(
"                if jump_key:\n"
"                    self._press_game_key(jump_key, duration=120)\n"
"                    self._combat_last_jump = now\n"
"                    self._slope_phase = 'wait_attack'",
"                if jump_key:\n"
"                    self._press_game_key(jump_key, duration=120)\n"
"                    self._combat_last_jump = now\n"
"                    self._slope_anchor_y = py_layer      # 起跳落地锚点Y:腾空SLOPE_AIR_MS窗内B用它分档/算距,不被空中Y污染\n"
"                    self._slope_air_until = now + SLOPE_AIR_MS\n"
"                    self._slope_phase = 'wait_attack'")

# ---- 自检 ----
assert "_eff_up" not in cc, "仍残留 _eff_up"
assert cc.count("high_slope = True") == 1 and cc.count("high_slope = False") >= 1
ast.parse(cc)
out = cc.replace('\n', NL)
io.open(p, 'wb').write(b'\xef\xbb\xbf' + out.encode('utf-8'))
print("OK maple 主线 slope 主权改造落盘; 替换10处, AST通过")
