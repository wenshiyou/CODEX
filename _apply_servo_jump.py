# -*- coding: utf-8 -*-
# 一次性:校准直跳改"连续眼手同步伺服"(用户2026-09-19定稿),跑跳带收60-75。物理替换旧大步+三轮定时小步+固定停顿。
# 主文件 UTF-8 BOM + 纯 LF。每处锚点 count==1 断言,先全量校验再写,写完外部 py_compile。
import io, sys

PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"

with io.open(PATH, "r", encoding="utf-8-sig", newline="") as f:
    text = f.read()

REPL = []

# R1 跑跳带常量 80/70 -> 75/60
REPL.append((
'''LADDER_RUNJUMP_HI = 80         # 跑跳带上限(用户2026-09-16定稿):人梯X差落入70-80跑跳
LADDER_RUNJUMP_LO = 70         # 跑跳带下限''',
'''LADDER_RUNJUMP_HI = 75         # 跑跳带上限(用户2026-09-19定稿):人梯X差落入60-75带速度跑跳;80贴边危险,收窄到75
LADDER_RUNJUMP_LO = 60         # 跑跳带下限(70→60):60-75跑跳,≤60不跑跳直接进连续伺服校准直跳'''))

# R2 校准常量块(629-645)整段替换
REPL.append((
'''# === 梯子【校准直跳】(用户2026-09-18定稿:跑跳/直跳没抓住不回主线;首次进校准先【走一大步】=按住朝梯键闭环走到
#   "进校准时首次人梯X差"的70%(走到剩30%即抬键;超时BIG_TIMEOUT也抬,防镜头/遮挡卡死),大步只在round=0走一次,直跳失败重入不再走;
#   大步后最多3轮精修(定时长60/50/40ms朝梯走→抬键停gap→对齐检测,|X差|≤10连续2帧原地直跳);任一直跳Y变小=抓住接爬梯段、剩余轮次作废;
#   3轮精修仍没抓住→重新算怪距回主线打怪。gap停120ms保底够人名X刷新一帧(约10帧/秒≈100ms),检测只吃新坐标、不拖时间) ===
LADDER_REALIGN_MAX_ROUNDS = 3     # 大步后精修最多3轮(用户2026-09-18):60/50/40ms三次小步
LADDER_REALIGN_MOVE_TIMES = (60, 50, 40)  # 三次精修移动时长ms(用户2026-09-18提速,原100/80/50)
LADDER_REALIGN_BIG_RATIO = 0.70   # 首次大步:走完进校准时人梯X差的70%(走到剩30%抬键)
LADDER_REALIGN_BIG_TIMEOUT_MS = 350  # 大步闭环超时(走不到70%也抬键进检测,余下交三轮精修,不卡死)
LADDER_REALIGN_CONFIRM_MS = 80    # gap停稳后对齐确认窗(原硬编码150→80提速):停这么久仍没达标才开下一轮精修
LADDER_REALIGN_GAP_MIN = 120      # 每次移动(含大步)后抬键固定停120ms等新一帧人名X(原200;≥约100ms一帧,保检测)
LADDER_REALIGN_GAP_MAX = 120      # 同上(固定120,无随机)
LADDER_REALIGN_TOL = 10           # 达标=屏幕|人-梯X差|≤此值
LADDER_REALIGN_LOCK_PX = 10       # 方向锁死区
LADDER_REALIGN_HOLD_FRAMES = 2    # 达标需连续帧数(防抖,和正常屏幕直跳一致)
LADDER_DEBUG_DIFF_PX = 200        # 诊断(用户2026-09-15):人梯屏幕|X差|≤此值才开始每秒打印一次"人X-梯X"
LADDER_DEBUG_DIFF_MS = 1000       # 诊断:"人X-梯X"打印节流1秒1条
LADDER_REALIGN_NO_TPL_MS = 1200   # 校准直跳里连续多久拿不到梯子屏幕X(无模板/匹配不到)=回主线,不死等''',
'''# === 梯子【校准直跳·连续眼手同步伺服】(用户2026-09-19定稿,物理替换旧"首次大步70%+三轮定时小步60/50/40+每步固定停120ms"开环碎步,新旧只留一套):
#   眼=人物线程持续刷人名X(_raw_char_pos原子发布)、B线程(上梯切小ROI高频档)持续刷梯白框X,手=主线keybd_event即时投递不阻塞眼;
#   主线每帧都拿得到最新人/梯X,故"走的时候就一直看"(闭环),不再"走固定时长→抬手死等→看一眼"。相位只有两个:
#   approach=按住朝梯方向键连续走,用最近窗内|人梯X差|的收敛速率估"靠近速度",按 速度×制动延迟 提前松手(让人靠惯性正好滑到X差≈0),
#            制动延迟按每次停稳结果一阶滤波自学、越用越准(只存内存);settle=松手后停稳,连续2帧X差≤10且人名X帧间不再滑=原地直跳,
#            走过头/没走到最多回approach修正1次。直跳后交_ladder_post_jump_process判后脑/Y,没抓住重入,最多尝试MAX_ROUNDS次回主线打怪。 ===
LADDER_REALIGN_MAX_ROUNDS = 3     # 直跳尝试上限(用户2026-09-19):每"进一次校准并起跳没抓住"算1次,满3次回主线(旧精修轮次语义废弃)
LADDER_REALIGN_TOL = 10           # 达标=屏幕|人-梯X差|≤此值(直跳抓取容差)
LADDER_REALIGN_LOCK_PX = 10       # 方向锁死区:|diff|≤此值的识别抖动不许左右翻向,真走过头/回approach才刷新方向
LADDER_REALIGN_HOLD_FRAMES = 2    # 停稳需连续帧数(防抖,和正常屏幕直跳一致)
LADDER_SERVO_BRAKE_T_DEFAULT = 100  # 松手→人物相对梯真正停住的总延迟初值ms(识别一拍+按键+行走惯性);自适应学习的起点
LADDER_SERVO_BRAKE_T_MIN = 40       # 制动延迟自学下限ms(夹范围防跑飞)
LADDER_SERVO_BRAKE_T_MAX = 260      # 制动延迟自学上限ms
LADDER_SERVO_BRAKE_ALPHA = 0.35     # 制动延迟一阶学习率(每次停稳小步修正,越用越准;只存内存不写盘)
LADDER_SERVO_HIST_MS = 300          # 靠近速度样本窗ms(窗内最早~最新|X差|变化算收敛速率,抗单帧识别抖)
LADDER_SERVO_APPROACH_TIMEOUT_MS = 1600  # approach连续走超时(卡住/镜头遮挡致X差不收敛,到点松手进settle看结果,不无限走)
LADDER_SERVO_SETTLE_TIMEOUT_MS = 700     # settle停稳确认超时(松手后人应很快停;到点仍不齐按修正/失败处理)
LADDER_SERVO_STOP_DPX = 3.0        # 停稳判据:相邻帧人名X位移≤此px=真不滑了(只在停稳后跳,不在滑行中跳)
LADDER_SERVO_CORRECT_MAX = 1       # 停稳后没对齐(走过头/没走到)最多回approach修正次数
LADDER_DEBUG_DIFF_PX = 200        # 诊断(用户2026-09-15):人梯屏幕|X差|≤此值才开始每秒打印一次"人X-梯X"
LADDER_DEBUG_DIFF_MS = 1000       # 诊断:"人X-梯X"打印节流1秒1条
LADDER_REALIGN_NO_TPL_MS = 1200   # 校准直跳里连续多久拿不到梯子屏幕X(无模板/匹配不到)=回主线,不死等'''))

# R3 _reset_climb 复位段(4939-4951)
REPL.append((
'''        # === 梯子校准直跳(首次大步70%+3轮精修)状态复位(用户2026-09-18) ===
        self._ladder_realign_round = 0       # 大步后精修已开始的轮数(每进一次move段+1,最多3;大步不计轮)
        self._ladder_realign_phase = None    # 'bigstep'首次大步 / 'move'精修走 / 'gap'抬键停顿 / 'align'等连续达标帧
        self._ladder_realign_t = 0           # 当前阶段开始时刻/本轮随机停顿截止
        self._ladder_realign_gap_to = 0      # 本轮抬键停顿截止时刻ms
        self._ladder_realign_from_x = None   # 本轮移动起点·人物屏幕X
        self._ladder_realign_px = 0          # 精修本轮移动时长ms(MOVE_TIMES)
        self._ladder_realign_lock_vk = None  # 本轮move锁定方向vk(10px方向锁:抖动不翻向,进gap/下一轮重定;用户2026-09-15)
        self._ladder_realign_ok_frames = 0   # 达标连续帧计数
        self._ladder_realign_no_tpl_since = 0  # 拿不到梯子屏幕X的起始时刻(超时回主线)
        self._ladder_realign_big_done = False  # 首次大步是否已走(只round=0走一次;仅_reset_climb复位,直跳失败重入不重置)
        self._ladder_realign_big_remain = 0    # 大步目标剩余X差px(走到剩这么多抬键);0=大步本段未初始化
        self._ladder_realign_big_to = 0        # 大步闭环超时截止ms(到点也抬键,余下交精修)''',
'''        # === 梯子校准直跳(连续眼手同步伺服)状态复位(用户2026-09-19) ===
        self._ladder_realign_round = 0       # 直跳尝试次数(每进一次校准+1,最多LADDER_REALIGN_MAX_ROUNDS)
        self._ladder_realign_phase = None    # 'approach'连续闭环走近 / 'settle'松手停稳确认起跳
        self._ladder_realign_t = 0           # 当前相位(approach/settle)起始时刻ms
        self._ladder_realign_hist = []       # 最近样本[(|X差|,now_ms)]估靠近速度(收敛速率)
        self._ladder_realign_lock_vk = None  # 方向锁vk(10px内抖动不翻向,真走过头/回approach重定)
        self._ladder_realign_ok_frames = 0   # 停稳连续帧计数
        self._ladder_realign_no_tpl_since = 0  # 拿不到梯子屏幕X的起始时刻(超时回主线)
        self._ladder_realign_corr = 0        # settle没对齐已回approach修正次数(≤LADDER_SERVO_CORRECT_MAX)
        self._ladder_realign_last_spx = None # 上一帧人名屏幕X(停稳判据:帧间位移)
        self._ladder_realign_rel_adiff = 0.0 # 松手瞬间|X差|(制动延迟自学用)
        self._ladder_realign_rel_r = 0.0     # 松手瞬间靠近速度px/ms(制动延迟自学用)
        self._ladder_realign_rel_timeout = False  # 本次松手是否为approach超时(超时样本不参与制动学习)
        # 注:_ladder_brake_t(制动延迟自学值)不在此复位,跨梯子保留、越用越准;首次访问getattr取LADDER_SERVO_BRAKE_T_DEFAULT'''))

# R4 enter _ladder_realign_jump(5222-5260)整方法
REPL.append((
'''    def _ladder_realign_jump(self, py, now_ms, why):
        """进入/重回【梯子校准直跳】(用户2026-09-14):起跳后Y没变小=没抓住梯子时调用,不回主线打怪。
        首次进(round=0)先走bigstep首次距离70%大步(只一次);之后每"开始一次精修move"算一轮(move段内+1),最多LADDER_REALIGN_MAX_ROUNDS轮;已满轮仍要进=精修三次都没成,
        松键、置短冷却、回主线重新算怪距。进入时保持_climb_state='to_ladder'、相位切realign(被_is_lock_frozen硬冻,不打怪不巡路)。"""
        for _vk in (VK_UP, VK_LEFT, VK_RIGHT):
            if _vk in self._random_move_keys:
                self._key_up(_vk)
        if self._ladder_realign_round >= LADDER_REALIGN_MAX_ROUNDS:
            _debug_log("[校准直跳] 已%d轮校准仍没抓住(%s),放弃回主线重新算怪距打怪"
                       % (self._ladder_realign_round, why))
            self._rlog("梯子校准%d轮都没挂上,回主线打怪(三次直跳失败)" % self._ladder_realign_round, LOG_RED, log='exception')
            self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
            self._reset_climb()
            self._decide_climb_fail_action()
            return False
        # 锁存跑跳已用(校准直跳只走对齐直跳)、开放重新直跳;相位realign硬冻。首次(round=0且大步未走)先进bigstep走首次距离70%大步(只一次),
        # 直跳失败重入(round>=1或大步已走)直接从move段开下一轮精修(move内round+1)
        self._ladder_run_jumped = True
        self._ladder_vert_jumped = False
        self._ladder_precise_mode = True   # 校准直跳全程彻底关怪物扫描,直到3轮失败_reset_climb/成功到顶才恢复(用户2026-09-14)
        self._ladder_jump_phase = 'realign'
        self._ladder_post_jump_step = None
        _go_big = (self._ladder_realign_round == 0 and not self._ladder_realign_big_done)
        self._ladder_realign_phase = 'bigstep' if _go_big else 'move'
        self._ladder_realign_from_x = None
        self._ladder_realign_px = 0
        self._ladder_realign_big_remain = 0   # 大步本段未初始化(进bigstep首帧按当时adiff定目标)
        self._ladder_realign_big_to = 0
        self._ladder_realign_lock_vk = None  # 新进校准:方向锁从头定(用户2026-09-15)
        self._ladder_realign_ok_frames = 0
        self._ladder_realign_no_tpl_since = 0
        self._ladder_realign_t = now_ms
        if _go_big:
            _debug_log("[校准直跳] 进校准(原因=%s):先走首次距离70%%大步→停%dms→对齐直跳;不成再%d轮精修(60/50/40ms)"
                       % (why, LADDER_REALIGN_GAP_MIN, LADDER_REALIGN_MAX_ROUNDS))
        else:
            _debug_log("[校准直跳] 进校准(原因=%s,已用精修轮=%d/%d):下一轮朝梯走→停下%dms→检测直跳"
                       % (why, self._ladder_realign_round, LADDER_REALIGN_MAX_ROUNDS, LADDER_REALIGN_GAP_MIN))
        return False''',
'''    def _ladder_realign_jump(self, py, now_ms, why):
        """进入/重回【梯子校准直跳·连续眼手同步伺服】(用户2026-09-19,物理替换原大步+三轮定时碎步):
        每次进入=一次直跳尝试(round+1,含首次),超过LADDER_REALIGN_MAX_ROUNDS次仍没抓住→松键、短冷却、回主线重新算怪距打怪。
        进入后置相位approach:按住朝梯连续闭环走、按自适应制动提前量松手→settle停稳原地直跳;起跳后交_ladder_post_jump_process判后脑/Y,
        没抓住由post_jump回本函数=下一次尝试。保持_climb_state='to_ladder'、相位realign(被_is_lock_frozen硬冻,不打怪不巡路)。"""
        for _vk in (VK_UP, VK_LEFT, VK_RIGHT):
            if _vk in self._random_move_keys:
                self._key_up(_vk)
        self._ladder_realign_round += 1
        if self._ladder_realign_round > LADDER_REALIGN_MAX_ROUNDS:
            _debug_log("[伺服直跳] 已尝试%d次仍没抓住(%s),放弃回主线重新算怪距打怪"
                       % (LADDER_REALIGN_MAX_ROUNDS, why))
            self._rlog("梯子伺服直跳%d次都没挂上,回主线打怪" % LADDER_REALIGN_MAX_ROUNDS, LOG_RED, log='exception')
            self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
            self._reset_climb()
            self._decide_climb_fail_action()
            return False
        # 锁存跑跳已用(校准只走对齐直跳)、开放重新直跳;相位realign硬冻、关锁怪出包(B线程梯子白框照刷且切高频小ROI);进approach连续伺服
        self._ladder_run_jumped = True
        self._ladder_vert_jumped = False
        self._ladder_precise_mode = True
        self._ladder_jump_phase = 'realign'
        self._ladder_post_jump_step = None
        self._ladder_realign_phase = 'approach'
        self._ladder_realign_hist = []
        self._ladder_realign_corr = 0
        self._ladder_realign_lock_vk = None
        self._ladder_realign_ok_frames = 0
        self._ladder_realign_no_tpl_since = 0
        self._ladder_realign_t = now_ms
        self._ladder_realign_last_spx = None
        self._ladder_realign_rel_adiff = 0.0
        self._ladder_realign_rel_r = 0.0
        self._ladder_realign_rel_timeout = False
        _debug_log("[伺服直跳] 第%d/%d次尝试(原因=%s):按住朝梯连续走→眼手同步提前松手→停稳直跳(制动T=%.0fms)"
                   % (self._ladder_realign_round, LADDER_REALIGN_MAX_ROUNDS, why,
                      getattr(self, '_ladder_brake_t', LADDER_SERVO_BRAKE_T_DEFAULT)))
        return False'''))

# R5 step 相位体(5340-5435: bigstep/move/gap/align -> approach/settle)
REPL.append((
'''        if ph == 'bigstep':
            # 首次大步(用户2026-09-18):闭环按住朝梯键,走到"进校准时人梯X差"的70%(剩30%)就抬键;已在TOL内直接进gap对齐直跳、不乱走。
            # 方向用上面算好的dir_vk/opp_vk(10px方向锁共用);超时也抬键,余下距离交3轮精修不卡死。大步不计精修轮数。
            if self._ladder_realign_big_remain <= 0:
                if adiff <= LADDER_REALIGN_TOL:
                    self._realign_release_move()
                    self._ladder_realign_big_done = True
                    self._ladder_realign_phase = 'gap'
                    self._ladder_realign_gap_to = now_ms + random.randint(LADDER_REALIGN_GAP_MIN, LADDER_REALIGN_GAP_MAX)
                    _debug_log("[校准直跳] 大步起步已对齐(剩%.0f<=%d),跳过移动直接检测直跳" % (adiff, LADDER_REALIGN_TOL))
                    return False
                self._ladder_realign_big_remain = max(adiff * (1.0 - LADDER_REALIGN_BIG_RATIO), float(LADDER_REALIGN_TOL))
                self._ladder_realign_big_to = now_ms + LADDER_REALIGN_BIG_TIMEOUT_MS
                self._ladder_realign_t = now_ms
                _debug_log("[校准直跳] 大步起步:首次差%.0fpx,走到剩%.0f(70%%)抬键,超时%dms"
                           % (adiff, self._ladder_realign_big_remain, LADDER_REALIGN_BIG_TIMEOUT_MS))
            if opp_vk in self._random_move_keys:
                self._key_up(opp_vk)
            if dir_vk not in self._random_move_keys:
                self._key_down(dir_vk)
            if adiff <= self._ladder_realign_big_remain or now_ms >= self._ladder_realign_big_to:
                if dir_vk in self._random_move_keys:
                    self._key_up(dir_vk)
                _big_timeout = now_ms >= self._ladder_realign_big_to and adiff > self._ladder_realign_big_remain
                self._ladder_realign_big_done = True
                self._ladder_realign_lock_vk = None
                self._ladder_realign_phase = 'gap'
                self._ladder_realign_gap_to = now_ms + random.randint(LADDER_REALIGN_GAP_MIN, LADDER_REALIGN_GAP_MAX)
                _debug_log("[校准直跳] 大步结束(目标剩%.0f 实际剩%.0f%s)抬键停%dms→对齐检测"
                           % (self._ladder_realign_big_remain, adiff, " 超时" if _big_timeout else "",
                              int(self._ladder_realign_gap_to - now_ms)))
            return False

        if ph == 'move':
            # 精修本轮起步:轮数+1,按LADDER_REALIGN_MOVE_TIMES[轮-1]定时长小步移动(60/50/40ms)
            if self._ladder_realign_from_x is None:
                self._ladder_realign_round += 1
                self._ladder_realign_from_x = spx
                self._ladder_realign_lock_vk = dir_vk
                _move_idx = min(self._ladder_realign_round - 1, len(LADDER_REALIGN_MOVE_TIMES) - 1)
                self._ladder_realign_px = LADDER_REALIGN_MOVE_TIMES[_move_idx]  # 复用字段存时长
                self._ladder_realign_t = now_ms
                _debug_log("[校准直跳] 第%d/%d轮:移动%dMS(剩余%.0fpx)"
                           % (self._ladder_realign_round, LADDER_REALIGN_MAX_ROUNDS,
                              self._ladder_realign_px, adiff))
            if opp_vk in self._random_move_keys:
                self._key_up(opp_vk)
            if dir_vk not in self._random_move_keys:
                self._key_down(dir_vk)
            _moved_ms = now_ms - self._ladder_realign_t
            if _moved_ms >= self._ladder_realign_px or adiff <= LADDER_REALIGN_TOL:
                # 按满时长/已达标→抬键,进gap停稳
                if dir_vk in self._random_move_keys:
                    self._key_up(dir_vk)
                self._ladder_realign_lock_vk = None
                self._ladder_realign_phase = 'gap'
                self._ladder_realign_gap_to = now_ms + random.randint(LADDER_REALIGN_GAP_MIN,
                                                                       LADDER_REALIGN_GAP_MAX)
                _debug_log("[校准直跳] 移动%dMS后剩余%.0f,抬键停%dms稳" % (
                    int(self._ladder_realign_px), adiff, int(self._ladder_realign_gap_to - now_ms)))
            return False

        if ph == 'gap':
            self._realign_release_move()
            if now_ms >= self._ladder_realign_gap_to:
                self._ladder_realign_phase = 'align'
                self._ladder_realign_ok_frames = 0
                self._ladder_realign_t = now_ms
            return False

        # align:停下检测新距离,连续达标=原地直跳;没达标且精修轮没用完回move再走一小步,满轮回主线
        self._realign_release_move()
        if adiff <= LADDER_REALIGN_TOL:
            self._ladder_realign_ok_frames += 1
            if self._ladder_realign_ok_frames >= LADDER_REALIGN_HOLD_FRAMES:
                _jk = self._get_fight_config().get("jump_key", "")
                self._climb_start_y = py    # 起跳前小地图Y=成败基准,起跳后Y变小=抓住接爬梯段
                if _jk:
                    self._press_game_key(_jk, duration=120)
                self._ladder_vert_jumped = True
                self._ladder_jump_phase = 'post_jump'
                self._ladder_post_jump_step = 'delay1'
                self._ladder_post_jump_t = now_ms
                self._ladder_realign_phase = None
                _debug_log("[校准直跳] 第%d轮对齐达标(X差%.1f<=%d)→原地直跳,跳后判Y"
                           % (self._ladder_realign_round, diff, LADDER_REALIGN_TOL))
            return False
        self._ladder_realign_ok_frames = 0
        # gap停稳后仍没达标就开下一轮精修(给LADDER_REALIGN_CONFIRM_MS确认,防落地/滑行惯性误判);已满3轮回主线
        if now_ms - self._ladder_realign_t >= LADDER_REALIGN_CONFIRM_MS:
            if self._ladder_realign_round >= LADDER_REALIGN_MAX_ROUNDS:
                return self._ladder_realign_jump(py, now_ms, "3轮移动仍对不齐(末轮剩余%.0fpx)" % adiff)
            self._ladder_realign_phase = 'move'
            self._ladder_realign_from_x = None
            self._ladder_realign_lock_vk = None   # 开下一轮move:方向锁清空,起步按新diff重定(用户2026-09-15)
        return False''',
'''        if ph == 'approach':
            # 连续闭环(眼手同步):按住dir_vk不抬,每帧用最新|人梯X差|在最近窗内的收敛速率估靠近速度,
            # 按 速度×制动延迟 提前松手(让人靠惯性正好滑到X差≈0)。镜头平移对人梯同向同量,差分里被抵消,r只反映人相对梯靠近。
            _hist = self._ladder_realign_hist
            _hist.append((adiff, now_ms))
            while _hist and now_ms - _hist[0][1] > LADDER_SERVO_HIST_MS:
                _hist.pop(0)
            _r = 0.0
            if len(_hist) >= 2:
                _a0, _t0 = _hist[0]
                _a1, _t1 = _hist[-1]
                _dtn = _t1 - _t0
                if _dtn > 0:
                    _r = max(0.0, (_a0 - _a1) / float(_dtn))   # px/ms,朝梯靠近为正
            _brake_t = getattr(self, '_ladder_brake_t', LADDER_SERVO_BRAKE_T_DEFAULT)
            _brake_px = _r * _brake_t
            _timeout = (now_ms - self._ladder_realign_t) >= LADDER_SERVO_APPROACH_TIMEOUT_MS
            # 松手判据:已进容差;或确在靠近且剩余距离≤制动滑行量+半容差(预测松手正好滑到0);或approach超时(卡死兜底)
            _release = (adiff <= LADDER_REALIGN_TOL) or \
                       (_r > 0.0 and adiff <= _brake_px + LADDER_REALIGN_TOL * 0.5) or _timeout
            if _release:
                self._ladder_realign_rel_adiff = float(adiff)
                self._ladder_realign_rel_r = _r
                self._ladder_realign_rel_timeout = bool(_timeout and adiff > LADDER_REALIGN_TOL)
                self._realign_release_move()
                self._ladder_realign_phase = 'settle'
                self._ladder_realign_t = now_ms
                self._ladder_realign_ok_frames = 0
                self._ladder_realign_last_spx = spx
                _debug_log("[伺服直跳] 松手进停稳(剩%.1f 靠近%.3fpx/ms 制动%.1fpx T%.0fms%s)"
                           % (adiff, _r, _brake_px, _brake_t, " approach超时" if _timeout else ""))
            else:
                if opp_vk in self._random_move_keys:
                    self._key_up(opp_vk)
                if dir_vk not in self._random_move_keys:
                    self._key_down(dir_vk)
            return False

        # settle:松手后停稳确认(连续HOLD_FRAMES帧X差≤TOL且人名X帧间不再滑)→原地直跳;没对齐最多回approach修正1次
        self._realign_release_move()
        _last_spx = self._ladder_realign_last_spx
        _slid = 999.0 if _last_spx is None else abs(spx - _last_spx)
        self._ladder_realign_last_spx = spx
        if adiff <= LADDER_REALIGN_TOL and _slid <= LADDER_SERVO_STOP_DPX:
            self._ladder_realign_ok_frames += 1
        else:
            self._ladder_realign_ok_frames = 0
        if self._ladder_realign_ok_frames >= LADDER_REALIGN_HOLD_FRAMES:
            # 制动延迟自学(仅非超时松手、且松手时确有靠近速度):松手后惯性实际走完(松手残差-停稳残差),反推有效制动时间,一阶滤波夹范围
            if (not self._ladder_realign_rel_timeout) and self._ladder_realign_rel_r > 0.0:
                _moved = max(0.0, self._ladder_realign_rel_adiff - adiff)
                _t_real = _moved / self._ladder_realign_rel_r
                _t_real = min(LADDER_SERVO_BRAKE_T_MAX, max(LADDER_SERVO_BRAKE_T_MIN, _t_real))
                _cur = getattr(self, '_ladder_brake_t', LADDER_SERVO_BRAKE_T_DEFAULT)
                self._ladder_brake_t = _cur + LADDER_SERVO_BRAKE_ALPHA * (_t_real - _cur)
            _jk = self._get_fight_config().get("jump_key", "")
            self._climb_start_y = py    # 起跳前Y=成败基准,起跳后看到后脑/Y变小=抓住接爬梯段
            if _jk:
                self._press_game_key(_jk, duration=120)
            self._ladder_vert_jumped = True
            self._ladder_jump_phase = 'post_jump'
            self._ladder_post_jump_step = 'delay1'
            self._ladder_post_jump_t = now_ms
            self._ladder_realign_phase = None
            _debug_log("[伺服直跳] 停稳达标(X差%.1f≤%d 帧滑%.1f)→原地直跳,跳后判后脑/Y(学到制动T=%.0fms)"
                       % (diff, LADDER_REALIGN_TOL, _slid,
                          getattr(self, '_ladder_brake_t', LADDER_SERVO_BRAKE_T_DEFAULT)))
            return False
        # 还没停稳/没对齐:settle超时则回approach修正(走过头方向锁会自动反向、没走到则补走),额度用完=本次失败回enter(尝试次数+1)
        if now_ms - self._ladder_realign_t >= LADDER_SERVO_SETTLE_TIMEOUT_MS:
            if self._ladder_realign_corr < LADDER_SERVO_CORRECT_MAX:
                self._ladder_realign_corr += 1
                self._ladder_realign_phase = 'approach'
                self._ladder_realign_hist = []
                self._ladder_realign_t = now_ms
                self._ladder_realign_lock_vk = None     # 回approach重定方向(走过头下一帧自动反向)
                self._ladder_realign_last_spx = None
                _debug_log("[伺服直跳] 停稳后未对齐(剩%.1f 梯在%s),回approach修正第%d/%d次"
                           % (adiff, ('右' if diff > 0 else '左'),
                              self._ladder_realign_corr, LADDER_SERVO_CORRECT_MAX))
            else:
                _debug_log("[伺服直跳] 修正%d次停稳仍不齐(剩%.1f),本次直跳失败,重入校准"
                           % (LADDER_SERVO_CORRECT_MAX, adiff))
                return self._ladder_realign_jump(py, now_ms, "伺服停稳对不齐(剩%.0f)" % adiff)
        return False'''))

# R6 跑跳段 docstring(10537-10539)
REPL.append((
'''        X差>300瞬移;>100按住大步助跑;60~80移动中【跑跳·第1次起跳】(起跳即松左右、按住↑1秒判Y,贴脸带不出水平速度故提前到60-80);
        60<X差≤100按住朝梯正常走等进跑跳带;X差≤60一律进【三步校准直跳_ladder_realign_jump】(走剩余50%→抬键停→连续对齐直跳→判Y,
        最多3轮,内置10px方向锁治识别抖动左右翻向),不再有碎步三拍/≤5直跳旧路径。"""''',
'''        X差>300瞬移;>100按住大步助跑;75<X差≤100按住朝梯正常走等进跑跳带;60~75移动中【跑跳·第1次起跳】(起跳即松左右、按住↑判Y,贴脸带不出水平速度故在60-75带速度提前跳);
        X差≤60一律进【连续伺服校准直跳_ladder_realign_jump】(眼手同步按住连续走→自适应提前松手→停稳直跳→判后脑/Y,
        最多尝试3次,内置10px方向锁;旧大步+三轮定时小步+固定停顿碎步已物理删除,新旧只留一套)。"""'''))

# R7 移动分带日志
REPL.append((
'''                _band = '进三步直跳(<=%d)' % LADDER_RUNJUMP_LO''',
'''                _band = '进伺服直跳(<=%d)' % LADDER_RUNJUMP_LO'''))

# R8 段2跑跳触发注释(10599-10600)
REPL.append((
'''        # 段2:移动中跑跳(用户2026-09-15定稿):屏幕X差[60,80]、朝梯方向键此刻正按住(=带水平速度)、选中白框=移动中起跳;
        # 贴脸X差≈0水平速度为0跳不上,故必须在60-80带速度提前跳。X差≤60不跑跳,由段2.6直接进三步校准直跳。''',
'''        # 段2:移动中跑跳(用户2026-09-19定稿):屏幕X差[60,75]、朝梯方向键此刻正按住(=带水平速度)、选中白框=移动中起跳;
        # 贴脸X差≈0水平速度为0跳不上,故必须在60-75带速度提前跳(80贴边危险已收窄)。X差≤60不跑跳,由段2.6直接进连续伺服校准直跳。'''))

# R9 跑跳起跳注释(10607)
REPL.append((
'''            # 用户2026-09-16定稿:70-80带起跳→按跳120ms,【起跳同时松开左右键】、100ms后按↑、按↑300ms后判Y''',
'''            # 用户2026-09-19定稿:60-75带起跳→按跳120ms,【起跳同时松开左右键】、100ms后按↑、按↑300ms后判Y'''))

# R10 跑跳起跳日志(10616-10618)
REPL.append((
'''            _debug_log("[爬梯·屏幕·跑跳] 70-80带起跳(梯X=%d 人X=%d 差%.1f):起跳松左右、100ms后按↑、300ms后判Y(基准Y=%.0f)" % (
                tpl_x, spx, sdx, py))
            self._rlog("跑跳上梯(70-80带X差%.1f起跳)" % sdx, log='behavior')''',
'''            _debug_log("[爬梯·屏幕·跑跳] 60-75带起跳(梯X=%d 人X=%d 差%.1f):起跳松左右、100ms后按↑、300ms后判Y(基准Y=%.0f)" % (
                tpl_x, spx, sdx, py))
            self._rlog("跑跳上梯(60-75带X差%.1f起跳)" % sdx, log='behavior')'''))

# R11 段2.5注释(10623-10624)
REPL.append((
'''        # 段2.5(用户2026-09-15收窄):走到这X差≤100(段1挡了>100);60~80在"按住+选中白框"时已由段2跑跳消费,
        # 落这=80~100,或60~80这帧还没满足跑跳(没选中白框/朝梯键刚起步)→按住朝梯正常走,下帧进60-80自然跑跳,不reset不转打怪。''',
'''        # 段2.5:走到这X差≤100(段1挡了>100);60~75在"按住+选中白框"时已由段2跑跳消费,
        # 落这=75~100,或60~75这帧还没满足跑跳(没选中白框/朝梯键刚起步)→按住朝梯正常走,下帧进60-75自然跑跳,不reset不转打怪。'''))

# R12 段2.6注释(10628-10629)
REPL.append((
'''        # 段2.6(用户2026-09-15):X差≤60一律进【三步校准直跳】(走剩余50%→抬键停→连续对齐直跳→判Y,最多3轮,内置10px方向锁);
        # 一进屏幕对位就已≤60=第一次直接三步直跳,不等跑跳。旧段3碎步三拍/段4≤5直跳已整条删除,新旧只留一套。''',
'''        # 段2.6(用户2026-09-19):X差≤60一律进【连续伺服校准直跳】(按住连续走→自适应提前松手→停稳直跳→判后脑/Y,最多尝试3次,内置10px方向锁);
        # 一进屏幕对位就已≤60=第一次直接伺服直跳,不等跑跳。旧大步+三轮定时小步+固定停顿碎步已整条物理删除,新旧只留一套。'''))

# R13 段2.6 why 文案(10634)
REPL.append((
'''        return self._ladder_realign_jump(py, now_ms, "首次进0-%d直接三步直跳" % LADDER_RUNJUMP_LO)''',
'''        return self._ladder_realign_jump(py, now_ms, "首次进0-%d直接伺服直跳" % LADDER_RUNJUMP_LO)'''))

# 规范化(防脚本自身CRLF致锚点不匹配)
REPL = [(a.replace("\r\n", "\n"), b.replace("\r\n", "\n")) for a, b in REPL]

# 先全量校验 count==1
for i, (old, new) in enumerate(REPL, 1):
    c = text.count(old)
    if c != 1:
        print("ANCHOR_FAIL R%d count=%d" % (i, c))
        sys.exit(1)

# 统一替换
for i, (old, new) in enumerate(REPL, 1):
    text = text.replace(old, new, 1)
    print("R%d ok" % i)

assert "\r\n" not in text, "CRLF found, abort"
with io.open(PATH, "wb") as f:
    f.write(b"\xef\xbb\xbf" + text.encode("utf-8"))
print("WRITE_OK replacements=%d" % len(REPL))
