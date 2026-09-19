# -*- coding: utf-8 -*-
"""
2026-09-19 误向下跳治理(用户拍板"不锁Y"方案) 原子修改脚本
- 甲: 物理删除Y钉地面基线(常量/字段/两函数/调用/3处刷出手; py_layer=py; B线程用实时Y)
- B1: 删pursue正下方直接按↓+跳落层旁路 + 腾空死变量; 保留下限平台保护/斜下水平走近
- 配套: combat_logic 锁定目标"下方维持带"去掉(dy>面板下方带立即cross, 消除30~55发呆缝)
- 腾空窗 600->2000ms
- 下跳落地: 进descend+2秒才许B重锁(B门控+主线保护期不巡游); 到顶仍150ms
- 改动3: 坐标不冻结, 特征+黑框双丢返回None不停旧点(保留内部局部窗中心last)
二进制 utf-8-sig 读写保BOM/LF; 每处 assert 命中唯一; 任一不过不写任何文件。
"""
import sys, py_compile

MAPLE = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
LOGIC = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py"


def load(path):
    with open(path, "rb") as f:
        raw = f.read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    txt = raw.decode("utf-8-sig")  # utf-8-sig 对有无BOM都能解
    return txt, bom


def save(path, txt, bom):
    # 保持原文件BOM风格(maple带BOM/combat_logic无BOM); 统一LF
    data = ((b"\xef\xbb\xbf") if bom else b"") + txt.encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)


def apply(txt, edits, tag):
    for label, old, new, cnt in edits:
        c = txt.count(old)
        if c != cnt:
            print("[FAIL] %s 命中%d次(期望%d): %s" % (tag, c, cnt, label))
            sys.exit(1)
        txt = txt.replace(old, new)
        print("[OK]   %s %s" % (tag, label))
    return txt


# ============ maple_route_ui.py ============
E = []

# M1 新增下跳重锁延迟常量(挂在ARRIVAL_RESET_COOLDOWN_MS行后)
E.append(("M1新增DESCEND_RELOCK_DELAY_MS",
"ARRIVAL_RESET_COOLDOWN_MS = 500 # 到顶/落地/走台\"到达新平台\"重扫冷却(2026-09-10再提效1200→500:到顶发呆主因之一;两次真实换台必>500ms仍挡得住\"到达连发→清空重锁左右横跳\",又能更快重锁本层怪)",
"ARRIVAL_RESET_COOLDOWN_MS = 500 # 到顶/落地/走台\"到达新平台\"重扫冷却(2026-09-10再提效1200→500:到顶发呆主因之一;两次真实换台必>500ms仍挡得住\"到达连发→清空重锁左右横跳\",又能更快重锁本层怪)\n"
"DESCEND_RELOCK_DELAY_MS = 2000  # 下跳(下台)后进descend起多少ms才许B重新锁怪(用户2026-09-19定稿:人落稳、Y回地面再锁,杜绝空中/下落旧Y锁错层又把人带下去;到顶/走台仍只150ms)", 1))

# M2 腾空窗 600 -> 2000
E.append(("M2腾空窗600→2000",
"SLOPE_HIGH_DOWN_BLOCK_MS = 600  # 跳高打最后一次起跳后多少ms内禁向下跳/向下cross(腾空360+落地缓冲;治腾空实时Y抬高把脚下怪误判成下方乱下跳;只拦向下,向上cross不拦;法师落地才打窗过期自然恢复;用户2026-09-18)",
"SLOPE_HIGH_DOWN_BLOCK_MS = 2000  # 跳高打最后一次起跳后多少ms内禁向下跳/向下cross(用户2026-09-19定稿600→2000:覆盖连续跳+落地站稳,人跳起Y变小期间绝不把脚下/同层怪误判成下方而下台;只拦向下,向上cross不拦;窗过期自然恢复)", 1))

# M3 删Y钉常量(整块, 含尾换行)
E.append(("M3删Y钉常量",
"# === 人物Y地面基线两态(用户2026-09-19):最近1秒出过攻击键=打怪态,取2秒窗人名中心Y最大值(屏幕最靠下=脚踩地面),\n"
"#     治跳起Y变小误判\"怪在下方\"乱下跳;连续1秒没出手=移动/巡路/上梯态,关窗Y实时;X永远实时、不进窗 ===\n"
"GROUND_Y_WINDOW_MS = 2000\n"
"STRIKE_ACTIVE_MS = 1000\n", "", 1))

# M4 删Y钉字段(整块, 含尾换行)
E.append(("M4删Y钉字段",
"        # === 人物Y地面基线两态(用户2026-09-19) ===\n"
"        self._last_strike_ms = 0           # 最近一次真正发攻击键(主攻/群攻/跳高打)时间ms,每次出手都刷;1秒内有=打怪态\n"
"        self._char_y_hist = []            # 打怪态人名中心Y滚动样本[(y,t_ms)],取GROUND_Y_WINDOW_MS窗内最大值=脚踩地面\n"
"        self._char_ground_y = None        # 分层用Y基线(打怪态=窗内最大;移动态=None=回退实时Y);X永远实时不进窗\n"
"        self._char_y_attacking = False    # 上一帧是否打怪态(移动→打怪上升沿清窗重采,不带入上一层旧Y)\n", "", 1))

# M5 新增 _descend_enter_t 字段
E.append(("M5新增_descend_enter_t字段",
"        self._raw_char_t = 0                # 后台线程最近一次发布人物脚位置的时间戳(ms)",
"        self._raw_char_t = 0                # 后台线程最近一次发布人物脚位置的时间戳(ms)\n"
"        self._descend_enter_t = 0          # 进下跳(descend)时刻ms:落地重锁保护期=此刻+DESCEND_RELOCK_DELAY_MS(用户2026-09-19)", 1))

# M7 人物线程删 _update_char_ground_y 调用(整行)
E.append(("M7人物线程删Y钉调用",
"                self._update_char_ground_y(_ch)          # Y地面基线两态(打怪态2秒窗最大/移动态实时),X不处理\n", "", 1))

# M8 B线程删 _layer_y 包裹
E.append(("M8 B线程Y实时",
"                    _ch = self._raw_char_pos   # 用A最新人物点做范围裁剪(差一个A周期,寻怪范围有余量,不影响)\n"
"                    if _ch is not None:\n"
"                        _ch = (_ch[0], self._layer_y(_ch[1]))  # Y用地面基线(打怪态2秒窗最大/移动态实时),X实时;裁剪/metric/锁怪分层全链路一致",
"                    _ch = self._raw_char_pos   # 用A最新人物点做范围裁剪(差一个A周期,寻怪范围有余量,不影响);Y实时不冻结(用户2026-09-19删地面Y钉:裁剪/metric/锁怪分层全用当帧真实Y,下跳落地靠2秒重锁保护期)", 1))

# M9 主线 py_layer=py
E.append(("M9主线py_layer=py",
"        py_layer = self._layer_y(py)  # Y两态地面基线(打怪态=2秒窗最大脚踩地面/移动态=实时);X仍用px实时,治跳起Y变小误判怪在下方乱下跳",
"        py_layer = py  # Y实时不冻结(用户2026-09-19定稿删地面Y钉:跳起/下落/下跳一律用当帧真实Y);误下跳改由\"跳高腾空窗2秒+下行必经cross(X<300且超面板Y带)+下跳落地2秒重锁\"根治,X仍用px实时", 1))

# M10 三处刷出手时间删行
E.append(("M10a删跳高打刷last_strike",
"                    self._last_strike_ms = now  # 刷最近出手时间(跳高打):1秒内有出手=打怪态\n", "", 1))
E.append(("M10b删群攻刷last_strike",
"                self._last_strike_ms = now  # 刷最近出手时间(群攻)\n", "", 1))
E.append(("M10c删主攻刷last_strike",
"                self._last_strike_ms = now  # 刷最近出手时间(主攻),供人物Y两态判定:1秒内有出手=打怪态、Y钉地面基线\n", "", 1))

# M11 删 pursue 腾空死变量
E.append(("M11删pursue腾空变量",
"        _slope_high_air = (now - getattr(self, '_slope_high_last_jump', 0)) < SLOPE_HIGH_DOWN_BLOCK_MS  # 跳高打腾空余温窗:窗内禁向下跳(不冻结Y只做状态门控,用户2026-09-18)\n", "", 1))

# M12 not _below2 块删 _below_down_since 清值行
E.append(("M12删_below_down_since清值(not块)",
"        if not _below2:\n"
"            self._release_combat_key(VK_DOWN)  # 不在下方贴近时松开下方向键,避免残留影响走位\n"
"            self._below_down_since = 0         # 离开下方状态:清下跳按住计时,下次重新等50ms",
"        if not _below2:\n"
"            self._release_combat_key(VK_DOWN)  # 不在下方贴近时松开下方向键,避免残留影响走位", 1))

# M13 下方块条件去掉腾空项 + 注释
E.append(("M13下方块条件去腾空",
"        if _below2 and not high_slope and not _slope_high_air:",
"        if _below2 and not high_slope:   # 仅保留\"下限平台保护(松↓水平走)/斜下水平走近\";正下方不再原地按↓+跳直接落层(用户2026-09-19删旁路),dy>面板下方带由B判cross、统一走_enter_descend完整下跳", 1))

# M14 边界分支删 _below_down_since 清值
E.append(("M14边界分支删_below_down_since",
"                if VK_DOWN in self._random_move_keys:\n"
"                    self._key_up(VK_DOWN)\n"
"                self._below_down_since = 0\n"
"                if move_dir is not None and not self._combat_at_locked_edge(move_dir):",
"                if VK_DOWN in self._random_move_keys:\n"
"                    self._key_up(VK_DOWN)\n"
"                if move_dir is not None and not self._combat_at_locked_edge(move_dir):", 1))

# M15 删 else 正下方直接落层整段(17424 else: 到 17442 debug日志), 保留其后17443统一return
E.append(("M15删正下方直接落层else",
"            else:\n"
"                # 几乎正下方(|X|≤15)：锁定了平台编号时禁止落层(下层怪不属于勾选平台,本就不该锁;双保险防掉出绿线)；\n"
"                # 只有全图模式(没勾平台)才按住下+跳落到下一层\n"
"                if self._selected_platforms:\n"
"                    self._release_combat_move()\n"
"                    self._release_combat_key(VK_DOWN)\n"
"                    self._below_down_since = 0\n"
"                    return\n"
"                # 用户2026-09-11:分层已用\"跳前点基线Y\"(起跳冻结、整跳不变),下跳腾空不会再误判高低,\n"
"                # 故删掉旧的3秒Y冻结;防连按只靠下面 _combat_last_jump>450 的跳冷却。\n"
"                self._release_combat_move()\n"
"                self._hold_combat_key(VK_DOWN)\n"
"                # 【2026-09-09下跳时序】先按住↓≥50ms建立向下状态再按跳(同帧按=普通跳不下落,下跳0成功根因)\n"
"                if not getattr(self, '_below_down_since', 0):\n"
"                    self._below_down_since = now\n"
"                if jump_key and (now - self._below_down_since) >= 50 and now - self._combat_last_jump > 450:\n"
"                    self._press_game_key(jump_key, duration=120)\n"
"                    self._combat_last_jump = now\n"
"                    _debug_log(\"[下坡] 怪在正下方Y差%d,↓按住≥50ms+跳落层\" % (t_cy - py_layer))\n", "", 1))

# M16 人物定位 frame None / 无锚点 不再返回旧foot
E.append(("M16定位无帧/无锚点返None",
"        if frame is None:\n"
"            return tr[\"foot\"]\n"
"        # 一个已采锚点都没有→新链无数据(测试期不再回退旧整框链),返回最后点/None\n"
"        if not any(self._role_has_anchor(_k) for _k in ROLE_ANCHOR_KEYS):\n"
"            _dot = self._dot_fallback_pos()   # 特征一个没采:黑框光点基点先顶替,map/光点也缺才退回foot保持点(用户2026-09-19)\n"
"            if _dot is not None:\n"
"                self._role_pos_src = 'dot'\n"
"                return _dot\n"
"            return tr[\"foot\"]",
"        if frame is None:\n"
"            return None   # 无画面不输出旧点(用户2026-09-19坐标不冻结),下游拿None本帧跳过\n"
"        # 一个已采锚点都没有→新链无数据:黑框光点基点先顶替;黑框也缺=本帧无人返回None(不停旧点,用户2026-09-19)\n"
"        if not any(self._role_has_anchor(_k) for _k in ROLE_ANCHOR_KEYS):\n"
"            _dot = self._dot_fallback_pos()\n"
"            if _dot is not None:\n"
"                self._role_pos_src = 'dot'\n"
"                return _dot\n"
"            return None", 1))

# M17 删 hold 参数
E.append(("M17删hold参数",
"        maxmove = int(P.get(\"maxmove\", 48)); faststep = int(P.get(\"faststep\", 2)); research = float(P.get(\"research\", 1500))\n"
"        hold = int(P.get(\"hold\", 90))  # 丢失保持(识别节拍数):丢了先沿用上一可信点,超过hold拍仍没找回才清空",
"        maxmove = int(P.get(\"maxmove\", 48)); faststep = int(P.get(\"faststep\", 2)); research = float(P.get(\"research\", 1500))", 1))

# M18 删 hold旧点输出段(fp), 黑框也缺直接None
E.append(("M18删hold旧点输出",
"        fp = tr[\"foot\"]\n"
"        if fp is not None and tr[\"miss\"] > hold:  # 丢失保持到期:连续hold个识别节拍没找回→清空旧点,不再死停(后台仍全图重搜,搜到自动恢复)\n"
"            tr[\"foot\"] = None; fp = None\n"
"        if fp is not None:\n"
"            if not getattr(self, '_role_pos_src', None):\n"
"                self._role_pos_src = 'hold'\n"
"            _fw = frame.shape[1]\n"
"            return fp\n",
"        # 黑框也缺=本帧确实无人(用户2026-09-19定稿:坐标绝不冻结/停旧点,直接None,下游本帧跳过);tr[\"last\"]保留供下帧局部窗快速重找、不掉帧率\n", 1))

# M23 定位docstring更新
E.append(("M23定位docstring",
"        人物匹配频率受fps节流(A线程,上梯高帧豁免);丢失先保持上一可信点、连续hold个跟踪节拍没找回才清空(保持秒数≈hold/fps)。",
"        人物匹配频率受fps节流(A线程,上梯高帧豁免);本帧人名/脸/后脑/宠物全丢且小地图黑框光点也缺=返回None(用户2026-09-19:坐标绝不冻结/停旧点);内部仍以上一可信点为局部窗中心,下帧快速重找、不掉帧率。", 1))

# M24 人物线程注释更新
E.append(("M24人物线程注释",
"                # 人物每帧一更新(用户2026-09-15定稿):每个新截图帧都重匹配并立刻发布,不再按角色fps节流沿用旧点;\n"
"                # 找不到才由_get_player_screen_pos内部停最后点(局部窗快跟→全图限频找回),坐标永远跟手、跳落即回地面值",
"                # 人物每帧一更新(用户2026-09-15定稿):每个新截图帧都重匹配并立刻发布,不再按角色fps节流沿用旧点;\n"
"                # 找不到(特征+小地图黑框双缺)直接发布None、绝不停旧点(用户2026-09-19坐标不冻结);局部窗仍以上一可信点为中心下帧快跟、全图限频找回", 1))

# M19 _enter_descend 记时刻
E.append(("M19 enter_descend记时刻",
"        self._climb_target_y = target_y\n"
"        self._climb_action_time = now_ms\n"
"        # 用户2026-09-11:跳前点基线已解决下跳腾空误判高低,删掉旧3秒冻结;防重复下跳靠descend状态机自身(进descend后不再走入口)",
"        self._climb_target_y = target_y\n"
"        self._climb_action_time = now_ms\n"
"        self._descend_enter_t = now_ms   # 进下跳时刻(用户2026-09-19):落地重锁保护到此刻+DESCEND_RELOCK_DELAY_MS(2秒),人落稳Y回地面再许B锁怪\n"
"        # 用户2026-09-11:跳前点基线已解决下跳腾空误判高低,删掉旧3秒冻结;防重复下跳靠descend状态机自身(进descend后不再走入口)", 1))

# M20 _reset_lock_after_arrival 下跳保护期2秒
E.append(("M20落地重锁保护期分来源",
"        # 【用户2026-09-19】识别线程在爬梯硬态也全程不停(硬冻只清锁定、不清怪表),到顶时self._monsters已是新层热表,\n"
"        # 不再清空怪表/血条、不再强制等整轮重扫(旧逻辑清表→空站等YOLO=到顶发呆数秒的根因);只靠下面150ms保护窗挡旧帧cross。\n"
"        # 到顶重识别保护窗:只挡硬冻刚解除那一瞬旧帧把梯子下方旧怪判成cross把人拉下去;识别没停、热表立即可锁,150ms足够\n"
"        self._arrival_relock_until = time.time() * 1000 + 150",
"        # 【用户2026-09-19】识别线程在爬梯硬态也全程不停(硬冻只清锁定、不清怪表),到顶时self._monsters已是新层热表,\n"
"        # 不再清空怪表/血条、不再强制等整轮重扫(旧逻辑清表→空站等YOLO=到顶发呆数秒的根因)。\n"
"        # 重锁保护窗(用户2026-09-19定稿):到顶/走台/边界只挡150ms旧帧cross;唯独\"下跳(下台)落地\"保护到进descend+2秒——\n"
"        # 人落稳、Y回到地面值才许B锁怪,杜绝下落/空中旧Y把同层怪判成下层又把人带下去(方式二借梯侧跳耗时>2s,落地即按150ms)。\n"
"        _now_relock = time.time() * 1000\n"
"        if source in ('下行自由落', '借梯侧跳落下', '下跳落地'):\n"
"            self._arrival_relock_until = max(_now_relock + 150, getattr(self, '_descend_enter_t', 0) + DESCEND_RELOCK_DELAY_MS)\n"
"        else:\n"
"            self._arrival_relock_until = _now_relock + 150", 1))

# M21 B线程锁怪门控叠加重锁保护窗
E.append(("M21 B门控叠保护窗",
"                        if self._is_lock_frozen():",
"                        if self._is_lock_frozen() or int(time.time() * 1000) < getattr(self, '_arrival_relock_until', 0):  # 再叠到顶/下跳落地重锁保护窗(下跳=进descend+2秒):窗内同样清锁不出包、怪表照刷,落稳零等待重锁(用户2026-09-19)", 1))

# M22 主线B无锁分支: 保护期内不巡游松键站等
E.append(("M22无锁分支保护期不巡游",
"            self._combat_active = False\n"
"            self._combat_had_target = False\n"
"            self._combat_last_target_pos = None\n"
"            self._combat_locked_target = None\n"
"            if self._roam_tick(now):\n"
"                return\n"
"            if self._combat_transit:\n"
"                self._transit_step()\n"
"            self._release_combat_move()\n"
"            return",
"            self._combat_active = False\n"
"            self._combat_had_target = False\n"
"            self._combat_last_target_pos = None\n"
"            self._combat_locked_target = None\n"
"            if now < getattr(self, '_arrival_relock_until', 0):\n"
"                # 到顶/下跳落地重锁保护期(下跳=进descend+2秒):松键站等、不巡游不跨层,落稳B立刻重锁(用户2026-09-19),杜绝保护期内乱走/拿空中旧Y锁错层\n"
"                self._release_combat_move()\n"
"                return\n"
"            if self._roam_tick(now):\n"
"                return\n"
"            if self._combat_transit:\n"
"                self._transit_step()\n"
"            self._release_combat_move()\n"
"            return", 1))

# M6 两个Y函数用锚点切片删除(单独处理, 不在E里走replace)
def remove_y_funcs(txt):
    start = "    def _update_char_ground_y(self, ch):"
    end = "        return _gy if _gy is not None else fallback_y"
    i = txt.count(start)
    j = txt.count(end)
    if i != 1 or j != 1:
        print("[FAIL] M6 Y函数锚点 start=%d end=%d" % (i, j)); sys.exit(1)
    si = txt.index(start)
    ei = txt.index(end)
    if ei < si:
        print("[FAIL] M6 Y函数 end在start前"); sys.exit(1)
    ej = ei + len(end)
    if txt[ej:ej+1] == "\n":
        ej += 1  # 吃掉函数尾换行, 不留多余空行
    print("[OK]   maple M6删_update_char_ground_y/_layer_y两函数")
    return txt[:si] + txt[ej:]


def main():
    mt, mbom = load(MAPLE)
    lt, lbom = load(LOGIC)
    if not mbom:
        print("[FAIL] maple_route_ui.py 缺BOM, 停(防写坏主文件编码)"); sys.exit(1)

    mt = apply(mt, E, "maple")
    mt = remove_y_funcs(mt)

    # combat_logic: 去掉锁定目标的下方维持带
    L = [("C1去下方维持带",
"            _b_down = (_pool_y_down + LOCK_HOLD_Y_BAND) if _pool_y_down is not None else _pool_y_down",
"            _b_down = _pool_y_down   # 下方不加维持带(用户2026-09-19):锁定目标dy>面板下方Y带立即判cross下行,消除\"维持带30~55内pursue卡住/旁路直接落层\"缝隙;维持带只留上方防跳高边界横跳", 1)]
    lt = apply(lt, L, "logic")

    # 残留自检: Y钉/旁路符号必须全部消失(maple); 用精确符号避免误伤 py_layer 等子串
    for sym in ["self._layer_y", "def _layer_y", "_update_char_ground_y", "_last_strike_ms",
                "_char_y_hist", "_char_ground_y", "_char_y_attacking",
                "GROUND_Y_WINDOW_MS", "STRIKE_ACTIVE_MS",
                "_below_down_since", "_slope_high_air", "hold = int(P.get"]:
        if sym in mt:
            print("[FAIL] 残留符号未清干净: %s (%d处)" % (sym, mt.count(sym))); sys.exit(1)
    print("[OK]   maple Y钉/下坡旁路/hold 残留符号自检=EMPTY; py_layer保留%d处" % mt.count("py_layer"))

    save(MAPLE, mt, mbom)
    save(LOGIC, lt, lbom)
    py_compile.compile(MAPLE, doraise=True)
    py_compile.compile(LOGIC, doraise=True)
    print("[DONE] 两文件已写回(UTF-8 BOM/LF)并通过 py_compile")


if __name__ == "__main__":
    main()
