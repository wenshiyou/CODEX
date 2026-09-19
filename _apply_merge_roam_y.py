# -*- coding: utf-8 -*-
"""一次性:主线两档合并 + 巡游找怪 + 人物Y两态基线(用户2026-09-19)。每锚点必须唯一,全过才写盘。"""
import io, sys

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(P, "r", encoding="utf-8-sig") as f:
    text = f.read()

R = []

# R1 常量
R.append((
"LAYER_Y_GAP = 150         # 用户2026-09-05：怪脚Y与人物Y差≤150px=同平台怪（超150=跨层/不同平台）；简单直接不靠绿线",
"""LAYER_Y_GAP = 150         # 用户2026-09-05：怪脚Y与人物Y差≤150px=同平台怪（超150=跨层/不同平台）；简单直接不靠绿线
# === 同层巡游找怪(用户2026-09-19):同层无怪也无跨层候选时,朝小地图光点"远的一侧竖线"走70%,边走边找怪、遇怪即停不补齐;一次结束冷却15s ===
ROAM_SIDE_RATIO = 0.70    # 朝远侧竖线走该侧剩余距离的比例
ROAM_COOLDOWN_MS = 15000  # 一次巡游结束(遇怪/走完)后冷却,期内不主动巡游(防左右来回晃)
ROAM_MIN_SIDE_PX = 24     # 远侧距离(小地图px)小于此=已贴边没空间,改短冷却3s不巡游
# === 人物Y地面基线两态(用户2026-09-19):最近1秒出过攻击键=打怪态,取2秒窗人名中心Y最大值(屏幕最靠下=脚踩地面),
#     治跳起Y变小误判"怪在下方"乱下跳;连续1秒没出手=移动/巡路/上梯态,关窗Y实时;X永远实时、不进窗 ===
GROUND_Y_WINDOW_MS = 2000
STRIKE_ACTIVE_MS = 1000"""))

# R2 初始化
R.append((
"        self._raw_char_pos = None           # 后台线程算出的人物脚位置",
"""        self._raw_char_pos = None           # 后台线程算出的人物脚位置
        # === 人物Y地面基线两态(用户2026-09-19) ===
        self._last_strike_ms = 0           # 最近一次真正发攻击键(主攻/群攻/跳高打)时间ms,每次出手都刷;1秒内有=打怪态
        self._char_y_hist = []            # 打怪态人名中心Y滚动样本[(y,t_ms)],取GROUND_Y_WINDOW_MS窗内最大值=脚踩地面
        self._char_ground_y = None        # 分层用Y基线(打怪态=窗内最大;移动态=None=回退实时Y);X永远实时不进窗
        self._char_y_attacking = False    # 上一帧是否打怪态(移动→打怪上升沿清窗重采,不带入上一层旧Y)
        # === 同层巡游找怪(用户2026-09-19) ===
        self._roam_active = False         # 正在朝小地图远侧走路找怪
        self._roam_target_mx = None       # 巡游目标小地图X(光点像素)
        self._roam_cd_until = 0           # 巡游冷却截止ms(一次结束起15s)"""))

# R3 人物线程维护基线
R.append((
"""                self._raw_char_pos = _ch                 # 原子发布:动作线程直接读最新人物点
                self._raw_char_t = time.time() * 1000    # 同步发布坐标时间戳(判坐标新鲜/陈旧,瞬移校验防误判)""",
"""                self._raw_char_pos = _ch                 # 原子发布:动作线程直接读最新人物点
                self._raw_char_t = time.time() * 1000    # 同步发布坐标时间戳(判坐标新鲜/陈旧,瞬移校验防误判)
                self._update_char_ground_y(_ch)          # Y地面基线两态(打怪态2秒窗最大/移动态实时),X不处理"""))

# R4 B线程_ch用基线Y
R.append((
"""                    _ch = self._raw_char_pos   # 用A最新人物点做范围裁剪(差一个A周期,寻怪范围有余量,不影响)
                    _now_det = time.time()""",
"""                    _ch = self._raw_char_pos   # 用A最新人物点做范围裁剪(差一个A周期,寻怪范围有余量,不影响)
                    if _ch is not None:
                        _ch = (_ch[0], self._layer_y(_ch[1]))  # Y用地面基线(打怪态2秒窗最大/移动态实时),X实时;裁剪/metric/锁怪分层全链路一致
                    _now_det = time.time()"""))

# R5 B怪扫门控解耦(识别不停)
R.append((
"""                # 怪物识别百分百总闸:_monster_scan_enabled(锁梯/上梯/下跳由set_monster_scan关) 或 上梯精准模式,任一关=当帧清空全部怪输出
                # (含2秒宽限/时序平滑/怪物血条/几何包这些'旧怪复活'漏口),主线程当帧拿不到任何怪→不打怪不巡路;不continue,落到尾部仍扫梯子白框
                _scan_mon = (not _precise) and bool(getattr(self, '_monster_scan_enabled', True))""",
"""                # 怪物识别百分百总闸(用户2026-09-19):识别/怪表/血条/距离软态硬态全程不停,只认_monster_scan_enabled;
                # _precise(上梯精准)只管梯子高频ROI、不再关怪识别。起跳后一心爬梯改由publish前"硬冻门控"只清锁定不出包,怪表照刷=到顶零等待重锁
                _scan_mon = bool(getattr(self, '_monster_scan_enabled', True))"""))

# R6 publish硬冻门控
R.append((
"""                    try:
                        self._publish_combat_decision(_ch, _merged, _metric, _fc, _frame, _bars, int(_now_det * 1000))
                    except Exception as _ie:
                        _debug_log("[识别B] 锁怪决策异常:%s" % _ie)""",
"""                    try:
                        if self._is_lock_frozen():
                            # 硬冻(已起跳/校准/爬梯/下跳):识别与怪表照刷(上面_raw已更新),但清锁定、不出打怪目标,
                            # 主线帧首硬闸一心爬梯绝不锁怪;到顶/失败解冻后B下一帧用一直热着的新层怪表立即重锁、零等待
                            self._b_lock = None; self._b_lock_tier = None
                            self._b_hp_confirmed = False; self._b_gone = 0; self._b_lock_time = 0
                            self._combat_decision_packet = None
                            self._combat_exec_feedback = None
                        else:
                            self._publish_combat_decision(_ch, _merged, _metric, _fc, _frame, _bars, int(_now_det * 1000))
                    except Exception as _ie:
                        _debug_log("[识别B] 锁怪决策异常:%s" % _ie)"""))

# R7 帧首唯一硬闸
R.append((
"""        if now < self._combat_busy_until:
            return

        # 【用户2026-09-08】爬梯不是单独的线，是找怪→锁定→移动→打怪这条线内的一部分（移动方式包括走路/跳/爬梯/下跳）""",
"""        if now < self._combat_busy_until:
            return

        # === 唯一硬闸(用户2026-09-19两档合并):已起跳/校准/爬梯/下跳/瞬移(_is_lock_frozen硬态)=本帧只走跨层状态机, ===
        # 打怪/走位/战斗瞬移/巡游全不碰、松战斗移动键,从决策最源头独占,根治"爬一半被打怪侧抢键/两个司机拉扯"。
        # 平地走向梯子还没起跳(to_ladder未post_jump)=软态,不在此拦(下面软分流放行近身站定怪cast先打)。
        if self._is_lock_frozen():
            self._release_combat_move()
            if self._combat_transit:
                self._transit_step()
            return

        # 【用户2026-09-08】爬梯不是单独的线，是找怪→锁定→移动→打怪这条线内的一部分（移动方式包括走路/跳/爬梯/下跳）"""))

# R8 无has_target分支
R.append((
"""        if not has_target:
            # 【冻结锁漏口修复·用户2026-09-09】抓梯/爬梯/下跳中检测线程漏一帧怪很常见,旧代码在此直接把锁定清成None,
            # 下帧重锁就可能锁到别的层(表现:人继续往上爬、目标却换成下层怪=两套意图打架中途停)。冻结中保留最后锁定,沿原目标继续跨层。
            if self._is_lock_frozen():
                if self._combat_transit:
                    self._transit_step()
                return
            self._combat_had_target = False
            self._combat_last_target_pos = None
            self._combat_locked_target = None
            # 【模块A】无怪时重置所有战斗状态，恢复巡路
            self._combat_active = False          # 取消战斗活跃，巡路恢复移动
            # 跨层行进中：感知不到怪也继续走向目标平台（_transit_step驱动状态机爬梯/水平脚走路）
            if self._combat_transit:
                self._transit_step()
            self._release_combat_move()
            return""",
"""        if not has_target:
            _cs0 = getattr(self, '_climb_state', 'none')
            if _cs0 == 'to_ladder' or (self._combat_transit and _cs0 == 'none'):
                # 软态跨层路(走向梯子未起跳/走台子):没锁到怪也一心继续走,不巡游;到顶保护窗内松键防旧帧
                if now >= getattr(self, '_arrival_relock_until', 0):
                    self._transit_step()
                else:
                    self._release_combat_move()
                return
            self._combat_had_target = False
            self._combat_last_target_pos = None
            self._combat_locked_target = None
            self._combat_active = False          # 取消战斗活跃
            # 同层无怪也无跨层目标:巡游找怪(朝小地图远侧走70%、遇怪即停不补齐),不能巡游才松键站等,绝不发呆
            if self._roam_tick(now):
                return
            if self._combat_transit:
                self._transit_step()
            self._release_combat_move()
            return"""))

# R9 py_layer基线
R.append((
"        py_layer = py",
"        py_layer = self._layer_y(py)  # Y两态地面基线(打怪态=2秒窗最大脚踩地面/移动态=实时);X仍用px实时,治跳起Y变小误判怪在下方乱下跳"))

# R10 删硬冻分支(保留瞬移校验)
R.append((
"""        # 锁怪冻结(用户2026-09-09)：已进入爬梯/上下跳/瞬移动作就不换锁——中途有怪进技能范围也不替换,
        # 等上/下到位(_climb_state回none)后下一帧重新识别时才解绑重锁；平地走向梯子那段(_climb_state=none)不冻,仍允许近身怪优先。
        # 【2026-09-09修复"一上去就下来"】独占判据只看_climb_state!=none,不再and _combat_transit:
        # 边界帧transit可能还没置位/已被取消分支清掉,旧写法此刻漏冻→锁到活着=False死怪/近身怪,决策抖成cast抢发攻击键把人从梯上弄下来。
        _freeze_lock = self._is_lock_frozen()  # 硬信号:跳起抓梯(post_jump)/爬梯/下跳/瞬移才冻;平地走向梯子(to_ladder未跳)不冻可换怪
        # 【责任硬分界·用户2026-09-10定稿】第一次起跳(post_jump)→登顶/失败=跨层执行期,与打怪彻底互斥:
        # 这期间不跑打怪决策(不找怪/不锁怪/不判空怪/不攻击),战斗侧也不碰左右移动键,只由transit一心爬到顶或出失败结果。
        # 从决策最源头切干净,不再靠后面逐段if拦截(根治"战斗移动与跨层抢方向键/两个脑子左右拉扯")。
        # 跨层前本层有怪先打由决策层保证(state=cast/pursue优先,cross=本层无够得着的怪才触发);登顶/失败_reset_climb后自动恢复找怪打怪。
        if _freeze_lock:
            self._release_combat_move()
            if self._combat_transit:
                self._transit_step()
            return
        # 每帧先核对上一次战斗瞬移是否真的让人物位移(用户2026-09-11:瞬移不过去要立刻知道、转跳/梯子,不卡住空闪)
        self._check_combat_teleport(now, px, py)""",
"""        # (硬冻独占已统一上移到反应门后唯一硬闸:post_jump/realign/climbing/descend等本帧根本走不到这里,
        #  旧的6处重复冻结关卡与死状态元组分支已全部删除;此处往后全是平地软态或正常打怪,同一帧只有一个司机)
        # 每帧先核对上一次战斗瞬移是否真的让人物位移(用户2026-09-11:瞬移不过去要立刻知道、转跳/梯子,不卡住空闪)
        self._check_combat_teleport(now, px, py)"""))

# R11 无包分支
R.append((
"""        _dlpkt = getattr(self, '_combat_decision_packet', None)
        if not _dlpkt or not _dlpkt.get('target'):
            # B无锁(无怪/关怪扫):爬梯/瞬移已由上面freeze分支接走,这里按无目标松键,不打不巡、不发呆乱走
            self._combat_active = False
            self._combat_had_target = False
            self._combat_last_target_pos = None
            self._combat_locked_target = None
            if self._combat_transit:
                self._transit_step()
            self._release_combat_move()
            return""",
"""        _dlpkt = getattr(self, '_combat_decision_packet', None)
        if not _dlpkt or not _dlpkt.get('target'):
            # B无锁(同层无怪):硬冻已由帧首硬闸接走;软态跨层路继续走梯/走台;否则巡游找怪,不能巡游才松键站等,绝不发呆
            _cs1 = getattr(self, '_climb_state', 'none')
            if _cs1 == 'to_ladder' or (self._combat_transit and _cs1 == 'none'):
                if now >= getattr(self, '_arrival_relock_until', 0):
                    self._transit_step()
                else:
                    self._release_combat_move()
                return
            self._combat_active = False
            self._combat_had_target = False
            self._combat_last_target_pos = None
            self._combat_locked_target = None
            if self._roam_tick(now):
                return
            if self._combat_transit:
                self._transit_step()
            self._release_combat_move()
            return"""))

# R12 删死代码元组分支
R.append((
"""        if getattr(self, '_climb_state', 'none') in ('climbing', 'jump_up', 'jump_down', 'descend', 'teleport'):
            if self._combat_transit:
                self._transit_step()
            return
""",
"""        # (climbing/jump_up/jump_down/descend/teleport硬冻态已由帧首硬闸独占,此重复分支已删)
"""))

# R13 软分流
R.append((
"""        if self._combat_transit or getattr(self, '_climb_state', 'none') == 'to_ladder':
            # 一条线串行(用户2026-09-15):一旦进入跨层/上梯段就只干这一件事,整段不再看打怪决策、
            # 没有"近身刷怪就解绑回打"分支(它=1212左右争抢抖动的根源,已废)。只走_transit_step,
            # 到顶/3轮失败这些"段结束事件"里才松键+重开怪扫+切回打怪。攻击键进入即松(打完怪再上梯)。
            if now < getattr(self, '_arrival_relock_until', 0):
                self._release_combat_move()
                return
            self._transit_step()
            return
        # 非transit:移动权在战斗手里,继续往下走 cast/pursue(打/追) 或 cross(首次启动跨层),互不重叠""",
"""        _cs2 = getattr(self, '_climb_state', 'none')
        if _cs2 == 'to_ladder' or (self._combat_transit and _cs2 == 'none'):
            # 软态跨层路(走向梯子还没起跳/走台子,用户2026-09-19):B锁怪没停——
            # 仅当锁到"站定就够得着的近身怪"(state=cast)时,松掉跨层走路按着的左右键、放行到下面原地打(本帧不tick transit);
            # 其余(pursue远怪/cross/switch/idle)一心_transit_step继续去梯/走台,不被远怪带偏。起跳(post_jump)起归帧首硬闸。
            if now < getattr(self, '_arrival_relock_until', 0):
                self._release_combat_move()
                return
            if _dl.get('state') != 'cast':
                self._transit_step()
                return
            # state=cast:近身站定怪先打(移动中游戏发不出技能,先物理松开左右键站定);打完下帧B若无cast自然回此分支继续去梯
            self._key_up(VK_LEFT)
            self._key_up(VK_RIGHT)
        # 非transit平地:移动权在战斗手里,继续 cast/pursue(打/追) 或 cross(首次启动跨层),互不重叠"""))

# R14 有target流程开头结束巡游
R.append((
"""        _dl = _dlpkt
        t_cx, t_cy = _dl['target']""",
"""        _dl = _dlpkt
        if getattr(self, '_roam_active', False):
            self._roam_end(True)  # 巡游中B锁到怪/跨层目标:先松巡游移动键并起冷却,再走打怪/跨层,杜绝两套移动键同帧
        t_cx, t_cy = _dl['target']"""))

# R15 idle分支加巡游
R.append((
"""        else:
            # idle：无任何可打目标，恢复巡路
            self._combat_active = False
            self._combat_had_target = False
            self._combat_locked_target = None
            if self._combat_transit:
                self._transit_step()
            self._release_combat_move()
            return""",
"""        else:
            # idle：B在跑但没选出目标(怪表空/无合适)→同层巡游找怪,不能巡游才松键站等,不发呆
            self._combat_active = False
            self._combat_had_target = False
            self._combat_locked_target = None
            if self._roam_tick(now):
                return
            if self._combat_transit:
                self._transit_step()
            self._release_combat_move()
            return"""))

# R16 到顶不清怪表
R.append((
"""        # 【用户2026-09-09·关键】检测是在梯子上做的,到顶时缓存没更新:必须把"梯子/旧平台那一帧"的旧检测结果一并清空,
        # 否则新重扫(下面节流置0)出结果前的空窗期,combat仍拿旧怪表(旧怪在下方)选成cross→人刚上去又被拉下来。
        # 清空后到新检测填回前怪表为空→combat判idle站定等待,绝不沿旧坐标往下跨层。
        self._monsters = []
        self._monster_hp_bars = []
        self._monster_feature_matches = []""",
"""        # 【用户2026-09-19】识别线程在爬梯硬态也全程不停(硬冻只清锁定、不清怪表),到顶时self._monsters已是新层热表,
        # 不再清空怪表/血条、不再强制等整轮重扫(旧逻辑清表→空站等YOLO=到顶发呆数秒的根因);只靠下面150ms保护窗挡旧帧cross。"""))

# R17 到顶不强制节流重扫
R.append((
"""        # 到顶重识别保护期(0.5s)双保险：防检测线程用手里旧帧在清空瞬间又回填、再把下方旧怪锁成cross
        self._arrival_relock_until = time.time() * 1000 + 150  # 2026-09-10提效300→150:只挡清空瞬间旧帧回填(几十ms),新检测一帧本就>150ms,缩短登顶站定发呆
        # 强制下一检测周期立刻在寻怪范围ROI内做YOLO+怪物特征+血条(不等YOLO 2Hz/特征0.33s/血条节流)，新层怪表最快刷新
        self._yolo_last_t = 0.0
        self._feat_last_t = 0.0
        self._bars_last_t = 0.0""",
"""        # 到顶重识别保护窗:只挡硬冻刚解除那一瞬旧帧把梯子下方旧怪判成cross把人拉下去;识别没停、热表立即可锁,150ms足够
        self._arrival_relock_until = time.time() * 1000 + 150"""))

# R18a 主攻出手
R.append((
"                self._combat_target_attacked = True  # 已对锁定目标出手：空怪判定用",
"""                self._combat_target_attacked = True  # 已对锁定目标出手：空怪判定用
                self._last_strike_ms = now  # 刷最近出手时间(主攻),供人物Y两态判定:1秒内有出手=打怪态、Y钉地面基线"""))

# R18b 群攻出手
R.append((
"                self._combat_target_attacked = True  # 群攻也算对锁定目标出手：空放无反馈时同样走130ms空怪drop换目标",
"""                self._combat_target_attacked = True  # 群攻也算对锁定目标出手：空放无反馈时同样走130ms空怪drop换目标
                self._last_strike_ms = now  # 刷最近出手时间(群攻)"""))

# R18c 跳高打出手
R.append((
"""                    self._combat_target_attacked = True
                    if not self._combat_first_strike_time:
                        self._combat_first_strike_time = now""",
"""                    self._combat_target_attacked = True
                    self._last_strike_ms = now  # 刷最近出手时间(跳高打):1秒内有出手=打怪态
                    if not self._combat_first_strike_time:
                        self._combat_first_strike_time = now"""))

# R19a 新增Y基线方法(插_is_lock_frozen后)
R.append((
"""        if cs == 'to_ladder' and getattr(self, '_ladder_jump_phase', None) in ('post_jump', 'realign'):
            return True
        return False

    def _set_combat_move(self, direction, allow_in_transit=False):""",
"""        if cs == 'to_ladder' and getattr(self, '_ladder_jump_phase', None) in ('post_jump', 'realign'):
            return True
        return False

    def _update_char_ground_y(self, ch):
        \"\"\"人物Y地面基线·两态(用户2026-09-19):打怪态(最近STRIKE_ACTIVE_MS内发过攻击键)维护最近GROUND_Y_WINDOW_MS
        人名中心Y样本、取最大值=脚踩地面(屏幕Y向下增大),跳起Y变小不污染分层,根治"跳起来误判怪在下方乱下跳";
        连续1秒没出手=移动/巡路/上梯态,关窗、_char_ground_y=None(调用方_layer_y回退实时Y)。X永远实时不进窗。
        移动→打怪上升沿清空窗口重采,避免把走路/上一层的旧大Y带进本次站桩。ch=None(本帧没识别到人)不改动基线。\"\"\"
        if ch is None:
            return
        nowm = time.time() * 1000
        _attacking = (nowm - getattr(self, '_last_strike_ms', 0)) <= STRIKE_ACTIVE_MS
        if _attacking:
            if not getattr(self, '_char_y_attacking', False):
                self._char_y_hist = []   # 上升沿:重新积累,不带入上一层旧Y
            self._char_y_hist.append((ch[1], nowm))
            _cut = nowm - GROUND_Y_WINDOW_MS
            self._char_y_hist = [_s for _s in self._char_y_hist if _s[1] >= _cut]
            self._char_ground_y = max(_s[0] for _s in self._char_y_hist) if self._char_y_hist else ch[1]
        else:
            self._char_y_hist = []
            self._char_ground_y = None   # 移动态:Y实时
        self._char_y_attacking = _attacking

    def _layer_y(self, fallback_y):
        \"\"\"分层/人怪Y差统一取Y:打怪态用地面基线(2秒窗最大),移动态/未积累用传入实时Y。X不经过这里、永远实时。\"\"\"
        _gy = getattr(self, '_char_ground_y', None)
        return _gy if _gy is not None else fallback_y

    def _set_combat_move(self, direction, allow_in_transit=False):"""))

# R19b 新增巡游方法(插_move_horizontal后)
R.append((
"""        # 同层到达判断(纯水平脚不再调_reset_climb; 爬梯复位由状态机到顶/调用方收尾负责)
        return abs(dx) <= 4 and abs(dy) <= 6

    def _play_alert(self, count=5):""",
"""        # 同层到达判断(纯水平脚不再调_reset_climb; 爬梯复位由状态机到顶/调用方收尾负责)
        return abs(dx) <= 4 and abs(dy) <= 6

    def _roam_tick(self, now_ms):
        \"\"\"同层巡游找怪(用户2026-09-19):同层无怪、也没跨层梯子候选时,朝小地图光点"远的一侧竖线(l/r)"走该侧
        剩余距离的ROAM_SIDE_RATIO(70%),边走边找怪;B一锁到怪(任意target)立即松键停手回主线打,没走完也不补齐;
        一次巡游结束(遇怪/走完)起冷却ROAM_COOLDOWN_MS。返回True=本帧巡游在走路(调用方直接return);False=没巡游。
        水平移动唯一走_move_horizontal(小地图光点导航,用_random_move_keys,与战斗combat键互不复用)。
        爬梯/软态去梯/选台走/越线拉回一律不巡游并取消进行中的巡游(跨层/拉回打断不耗冷却)。\"\"\"
        cs = getattr(self, '_climb_state', 'none')
        if cs != 'none' or getattr(self, '_combat_transit', False):
            self._roam_end(False)
            return False
        if getattr(self, '_bound_pull', None) is not None:
            self._roam_end(False)
            return False
        _pkt = getattr(self, '_combat_decision_packet', None)
        if _pkt and _pkt.get('target'):
            if getattr(self, '_roam_active', False):
                self._roam_end(True)   # 遇怪即停(不补齐),起冷却
            return False
        if now_ms < getattr(self, '_roam_cd_until', 0):
            return False
        dot = getattr(self, '_player_map_pos', None)
        try:
            lines = self._get_bound_lines()
        except Exception:
            lines = None
        if dot is None or not lines:
            self._roam_end(False)
            return False
        mx, my = dot[0], dot[1]
        bl, br = lines['l'], lines['r']
        dL, dR = mx - bl, br - mx
        if not getattr(self, '_roam_active', False):
            _far = dR if dR >= dL else dL
            if _far < ROAM_MIN_SIDE_PX:
                self._roam_cd_until = now_ms + 3000   # 已贴边没空间,短冷却避免每帧重算
                return False
            _tgt = mx + ROAM_SIDE_RATIO * dR if dR >= dL else mx - ROAM_SIDE_RATIO * dL
            self._roam_target_mx = _tgt
            self._roam_active = True
            _debug_log("[巡游] 同层无怪,朝%s侧找怪:光点%.0f→目标%.0f(远侧%.0f小地图px,走%.0f%%)" % (
                "右" if dR >= dL else "左", mx, _tgt, _far, ROAM_SIDE_RATIO * 100))
        if self._roam_target_mx is None:
            self._roam_end(False)
            return False
        try:
            _arrived = self._move_horizontal((mx, my), self._roam_target_mx, my)
        except Exception as _e:
            _debug_log("[巡游] 水平移动异常:%s" % _e)
            self._roam_end(False)
            return False
        if _arrived or abs(mx - self._roam_target_mx) <= 4:
            self._roam_end(True)       # 走完,起冷却
            return False
        return True

    def _roam_end(self, start_cooldown):
        \"\"\"结束巡游:物理松开左右移动键(_move_horizontal同款_random_move_keys键);start_cooldown=True起15s冷却。\"\"\"
        self._roam_active = False
        self._roam_target_mx = None
        try:
            self._key_up(VK_LEFT)
            self._key_up(VK_RIGHT)
        except Exception:
            pass
        if start_cooldown:
            self._roam_cd_until = time.time() * 1000 + ROAM_COOLDOWN_MS
            _debug_log("[巡游] 本次结束(遇怪即停/走完不补),冷却%.0fs" % (ROAM_COOLDOWN_MS / 1000.0))

    def _play_alert(self, count=5):"""))

# 校验
for i, (old, new) in enumerate(R, 1):
    c = text.count(old)
    if c != 1:
        print("ANCHOR FAIL R%d count=%d" % (i, c))
        sys.exit(1)
for old, new in R:
    text = text.replace(old, new, 1)

assert "\r\n" not in text, "CRLF found"
with io.open(P, "wb") as f:
    f.write(b"\xef\xbb\xbf" + text.encode("utf-8"))
print("ALL %d REPLACEMENTS APPLIED OK" % len(R))
