# -*- coding: utf-8 -*-
"""阶段3a: 新增 _ladder_approach_step/_ladder_pick_fail_action(站定/二帧建锁等待/挪位冷却),
改造 to_ladder 状态机(删每帧precise=True、删固定1500ms超时,插入approach相位)。"""
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s = open(P, "rb").read().decode("utf-8-sig")
log = []
def rep(old, new, n=1, tag=""):
    global s
    c = s.count(old)
    assert c == n, "[%s] 命中%d次(期望%d) old=%r" % (tag, c, n, old[:80])
    s = s.replace(old, new); log.append("OK " + tag)

_NEW_METHODS = '''
    def _ladder_approach_step(self, sp, now_ms):
        """to_ladder起跳前approach相位(用户2026-09-19):settle走到怪X±300并自然松键站定→pick站着等蒙板段二帧稳梯建锁
        (建锁转align由蒙板段做)→连续3扫描节拍无稳梯走repos挪位1次/10秒冷却回主线。全程怪扫开,身边刷同层怪B线cast软档打断回打。
        返回False(本帧不推进对位)。"""
        try:
            if sp is None:
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                return False
            spx = int(sp[0])
            phase = getattr(self, '_ladder_approach_phase', 'none')
            tmox = getattr(self, '_ladder_target_mon_x', None)
            if phase == 'repos':
                # 挪位:朝怪X方向按住LADDER_REPOS_MS,到点回主线自然重锁(10s冷却只禁挪位,不影响扫怪锁梯)
                if now_ms < self._ladder_repos_until:
                    self._hold_toward_ladder(self._ladder_repos_dir)
                    return False
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                _cd = max(0, int(self._ladder_repos_cd_until - now_ms))
                _debug_log("[选梯·挪位] 挪位%dms结束回主线自然重锁(10s冷却剩%dms只禁挪位,稳梯二帧稳定仍立即上)" % (LADDER_REPOS_MS, _cd))
                self._reset_climb(); self._decide_climb_fail_action()
                return False
            if phase == 'settle':
                # 怪X还在300外:继续水平走近(不为锁梯半路刹停);走进300才松键,按人物识别帧判横移停=自然站定
                if tmox is not None and abs(int(tmox) - spx) > LADDER_DIR_X_HALF:
                    self._hold_toward_ladder(int(tmox) - spx)
                    self._ladder_settle_last_x = None
                    self._ladder_settle_frames = 0
                    return False
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                _ct = getattr(self, '_raw_char_t', 0)
                if _ct and _ct != self._ladder_settle_last_char_t:
                    if self._ladder_settle_last_x is None:
                        self._ladder_settle_frames = 0
                    elif abs(spx - self._ladder_settle_last_x) <= LADDER_SETTLE_DPX:
                        self._ladder_settle_frames += 1
                    else:
                        self._ladder_settle_frames = 0
                    self._ladder_settle_last_x = spx
                    self._ladder_settle_last_char_t = _ct
                    if self._ladder_settle_frames >= LADDER_SETTLE_FRAMES:
                        self._ladder_approach_phase = 'pick'
                        self._ladder_pick_beat_scan_t = 0.0
                        self._ladder_pick_stable = None
                        self._ladder_pick_fail_beats = 0
                        _debug_log("[选梯·站定] 已到怪X±%d内并自然站定,开二帧稳梯观察(怪扫仍开)" % LADDER_DIR_X_HALF)
                return False
            # phase == 'pick': 松键站着等蒙板段二帧稳梯建锁;fail_beats到阈值=找不到稳梯,挪位1次/冷却回主线,不发呆
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            if self._ladder_pick_fail_beats >= LADDER_PICK_FAIL_BEATS:
                self._ladder_pick_fail_beats = 0
                self._ladder_pick_stable = None
                self._ladder_pick_fail_action(spx, now_ms, tmox)
            return False
        except Exception as _e:
            _debug_log("[选梯·approach] 异常:%r" % (_e,))
            return False

    def _ladder_pick_fail_action(self, spx, now_ms, tmox):
        """连续3扫描节拍无稳梯(用户2026-09-19):冷却内直接回主线重锁同层/身边怪;否则朝怪X挪位LADDER_REPOS_MS(仅1次),
        挪完回主线自然重锁;10s内不再挪位(扫怪/锁梯/上梯/打怪全程正常,稳梯二帧稳定立即可上)。"""
        if now_ms < self._ladder_repos_cd_until:
            _debug_log("[选梯·冷却] 无稳梯且挪位冷却中(剩%dms),回主线重锁;稳梯二帧稳定仍会立即上" % int(self._ladder_repos_cd_until - now_ms))
            self._reset_climb(); self._decide_climb_fail_action()
            return
        _dir = 1 if (tmox is None or int(tmox) >= spx) else -1
        self._ladder_repos_dir = _dir
        self._ladder_repos_until = now_ms + LADDER_REPOS_MS
        self._ladder_repos_cd_until = now_ms + LADDER_REPOS_COOLDOWN_MS
        self._ladder_approach_phase = 'repos'
        _debug_log("[选梯·挪位] 连续%d扫描节拍无稳梯,朝怪X向%s挪位%dms后自然重锁;%ds内不再挪位(扫怪锁梯不影响)" % (
            LADDER_PICK_FAIL_BEATS, '右' if _dir > 0 else '左', LADDER_REPOS_MS, LADDER_REPOS_COOLDOWN_MS // 1000))

'''

# 1) 新方法挂到 _hold_toward_ladder 之后、_back_head_visible 之前
rep(
'''        # 上屏(用户2026-09-09)：持续走向梯子时限频报方向/剩余小地图X差，600ms一条
        self._rlog_throttle('to_ladder', "正走向梯子(梯在%s,小地图X差%.0f)" % (
            "右" if ldx > 0 else "左", abs(ldx)), 1500, log='behavior')

    def _back_head_visible(self):''',
'''        # 上屏(用户2026-09-09)：持续走向梯子时限频报方向/剩余小地图X差，600ms一条
        self._rlog_throttle('to_ladder', "正走向梯子(梯在%s,小地图X差%.0f)" % (
            "右" if ldx > 0 else "左", abs(ldx)), 1500, log='behavior')
''' + _NEW_METHODS + '''    def _back_head_visible(self):''',
    tag="新增approach两方法",
)

# 2) to_ladder 状态机: 删每帧关扫 + 删固定1500超时, 插入approach相位
rep(
'''            # 只要目标是梯子就关怪扫(用户2026-09-15拍板·不等90px):一进to_ladder识别B立刻清空怪表,战斗决策算不到
            # "技能范围内有怪"(不出cast)→近身解绑条件不成立、不会被身边怪拉回,下面屏幕选梯/朝梯走/对位/起跳全程不被打断;
            # 到顶或3轮失败由_reset_climb把标志置False恢复扫描。决定跨层去梯那一刻(_try_platform_transition)也提前关,堵首帧空窗。
            self._ladder_precise_mode = True

            # 起跳后统一流程优先（跑跳/直跳都走这里）
            if getattr(self, '_ladder_jump_phase', None) == 'post_jump':
                return self._ladder_post_jump_process(py, now_ms)
            # 【校准直跳】校准中(70%×3轮),与打怪/巡路互斥(用户2026-09-14)
            if getattr(self, '_ladder_jump_phase', None) == 'realign':
                return self._ladder_realign_step(py, now_ms)

            # === 纯屏幕找梯对位(用户2026-09-15定稿:删掉小地图找梯/小地图粗导航,找梯-朝梯走-对位-起跳全程游戏窗口屏幕坐标) ===
            # 选中梯屏幕X:主循环蒙板段"锁身份+两帧累积+最近邻跟踪"产出的_ladder_snap_x优先(空帧也保持);它为None才用模板现匹配兜底。
            _sel_x = getattr(self, '_ladder_snap_x', None)
            if _sel_x is None and getattr(self, '_ladder_templates', None) \\
                    and self._raw_frame is not None and self._player_screen_pos:
                _lkx0 = getattr(self, '_ladder_target_mon_x', None)   # 固定终点怪X(关怪扫后锁定怪已清空,不能用)
                _sel_x = self._match_ladder_screen_x(self._raw_frame, self._player_screen_pos,
                                                     self._climb_direction, _lkx0)
            if _sel_x is not None:
                self._lad_scr_last_t = now_ms
                self._lad_scr_last_x = _sel_x
                return self._ladder_align_by_screen(_sel_x, px, py, now_ms, jump_key)   # 各分带持续朝梯走,不停
            # 保命出口(不是补丁):进to_ladder连续LADDER_MERGE_WAIT_MS屏幕上一把梯都识别不到=没录梯图/没YOLO/不在梯旁,
            # 松左右键回主线打怪,绝不永久空转;刚进、短暂丢帧则站住不发键(不再回退小地图按住乱走)。
            if getattr(self, '_lad_scr_enter_t', 0) == 0:
                self._lad_scr_enter_t = now_ms
            if now_ms - self._lad_scr_enter_t >= LADDER_MERGE_WAIT_MS:
                self._rlog("屏幕连续%.0fms找不到梯子,松键回主线打怪(不死等)" % LADDER_MERGE_WAIT_MS, LOG_RED, log='exception')
                _debug_log("[梯子·掉锁] 屏幕连续%.0fms一把白框都没识别到(无梯模板/相似度不够/已离开梯旁),松左右键回主线打怪" % LADDER_MERGE_WAIT_MS)
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                self._reset_climb(); self._decide_climb_fail_action()
                return False
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            return False''',
'''            # 关怪扫时机(用户2026-09-19重写):进to_ladder不再立刻关扫。上行先走approach相位(走到怪X±300自然站定→
            # 蒙板段二帧稳梯建锁),建锁成功那一刻才由蒙板段权威置precise=True关扫,关扫窗口最短;走近/站定/扫梯/挪位全程怪扫开、
            # 身边出怪可被B线cast软档打断回打。起跳后(post_jump/realign/climbing)建锁早已关扫。下行(下跳失败转to_ladder,cdir=-1)
            # 在入口自置precise=True、approach_phase保持none直接走align对位,不走本相位。

            # 起跳后统一流程优先（跑跳/直跳都走这里）
            if getattr(self, '_ladder_jump_phase', None) == 'post_jump':
                return self._ladder_post_jump_process(py, now_ms)
            # 【校准直跳】伺服眼手同步校准中,与打怪/巡路互斥(用户2026-09-14)
            if getattr(self, '_ladder_jump_phase', None) == 'realign':
                return self._ladder_realign_step(py, now_ms)

            # === 起跳前approach:settle走近站定→pick等二帧稳梯建锁→repos挪位;建锁转align后才屏幕对位起跳(用户2026-09-19) ===
            _ap = getattr(self, '_ladder_approach_phase', 'align')
            if _ap in ('settle', 'pick', 'repos'):
                return self._ladder_approach_step(self._player_screen_pos or (px, py), now_ms)

            # === align:已建锁,纯屏幕对位(锁点_ladder_snap_x优先、空帧为None;它为None才用模板现匹配兜底) ===
            _sel_x = getattr(self, '_ladder_snap_x', None)
            if _sel_x is None and getattr(self, '_ladder_templates', None) \\
                    and self._raw_frame is not None and self._player_screen_pos:
                _lkx0 = getattr(self, '_ladder_target_mon_x', None)   # 固定终点怪X(关怪扫后锁定怪已清空,不能用)
                _sel_x = self._match_ladder_screen_x(self._raw_frame, self._player_screen_pos,
                                                     self._climb_direction, _lkx0)
            if _sel_x is not None:
                self._lad_scr_last_t = now_ms
                self._lad_scr_last_x = _sel_x
                return self._ladder_align_by_screen(_sel_x, px, py, now_ms, jump_key)   # 各分带持续朝梯走,不停
            # align相位这帧没锁点(蒙板段跟丢):站住不发键、不拿旧点;蒙板段连续3扫描节拍补不回会清锁回pick重新稳梯,
            # 再3拍无稳梯由_ladder_approach_step走挪位/冷却回主线,不会永久空转(用户2026-09-19,删固定1500ms超时)。
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            return False''',
    tag="to_ladder状态机",
)

open(P, "wb").write(s.encode("utf-8-sig"))
import py_compile
py_compile.compile(P, doraise=True)
print("\n".join(log)); print("阶段3a写回并编译通过")
