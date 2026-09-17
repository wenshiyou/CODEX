# -*- coding: utf-8 -*-
"""
_fix34b2.py  块2 停滞1秒纯观测(报【异常】栏,只看不干预) + 块5-G 战斗线程异常上屏
- 常量 STALL_OBSERVE_MS=1000
- init _obs_* 基准字段
- 新增 _stall_observer(主循环combat_tick后独立try调,只读不发键) + _stall_state_text/_stall_next_text/_stall_obs_baseline
  判据口径同 _global_stall_watchdog(屏幕基点≥6/光点≥2/近2秒放技能/怪数减少/豁免长动作/有任务),
  满1秒首报、每秒一条"停滞N秒 当前=X 下一步=Y",无怪待命/休息/爬梯下跳起跳回退不报,恢复报一条
- 主循环战斗 except 同步送异常栏(块5-G的战斗侧;识别线程侧另接)
"""
import io
PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    text = f.read()
def rep(old, new, n):
    global text
    c = text.count(old); assert c == n, "命中=%d 期望%d %r" % (c, n, old[:60])
    text = text.replace(old, new)

# 1) 常量
rep(
"""GLOBAL_SKILL_HB_MS = 2000    # 最近这么多ms内放过主攻/群攻=站桩输出中(进展,不误判施法站桩)""",
"""GLOBAL_SKILL_HB_MS = 2000    # 最近这么多ms内放过主攻/群攻=站桩输出中(进展,不误判施法站桩)
STALL_OBSERVE_MS = 1000     # 停滞纯观测阈值:有任务却连续1秒无任一进展心跳→【异常】栏报一条(只观测不干预,2026-09-17)""", 1)

# 2) init 字段
rep(
"""        self._dragging_log_hscroll = False  # 正在拖底部水平滚动条""",
"""        self._dragging_log_hscroll = False  # 正在拖底部水平滚动条
        # 停滞纯观测(2026-09-17):有任务无进展满1秒报【异常】栏,只观测不干预(基准/上次秒数/是否在停滞态)
        self._obs_hb = 0
        self._obs_sp = None
        self._obs_mp = None
        self._obs_nmon = 0
        self._obs_active = False
        self._obs_last_rep = 0""", 1)

# 3) 三个方法插在 _global_stall_watchdog 前
METHODS = '''    def _stall_obs_baseline(self, now, active=False):
        """重置停滞观测基准(进展/无任务/休息时调用)。"""
        self._obs_hb = now
        self._obs_sp = self._player_screen_pos
        self._obs_mp = self._player_map_pos
        self._obs_nmon = len(self._monsters or [])
        self._obs_active = active
        self._obs_last_rep = 0

    def _stall_state_text(self, cs):
        """停滞观测:把当前战斗/爬梯状态翻成白话(只读状态,不发键)。"""
        _cs = {
            'to_ladder': '走向梯子(平地接近,尚未抓上)',
            'climbing': '爬梯子中',
            'jump_up': '上跳起跳/空中',
            'jump_down': '下台阶起跳/空中',
            'teleport': '瞬移中',
            'descend': '下梯子/下台中',
        }.get(cs)
        if _cs:
            return _cs
        if getattr(self, '_combat_transit', False):
            return '跨层规划/执行中'
        if self._combat_locked_target is not None:
            return '打怪中·锁怪%s' % ('出手攻击' if getattr(self, '_combat_active', False) else '追怪靠近')
        if self._monsters:
            return '选怪中(画面有怪但还没锁定)'
        return '无明确任务'

    def _stall_next_text(self, cs):
        """停滞观测:按当前状态给出"下一步本该做什么"的白话,一眼看出卡在哪。"""
        if cs != 'none' or getattr(self, '_combat_transit', False):
            if cs == 'to_ladder':
                return '走到起跳点跑跳/直跳,失败走三次校准,三次都失败开怪识别打怪'
            if cs == 'climbing':
                return '持续按上直到小地图光点对梯顶,到顶多按200ms后开怪识别'
            return '完成本次爬梯/跨层/瞬移动作,结束后回打怪'
        if self._combat_locked_target is not None:
            return '近身就出手;打不到就靠近,跨层(Y差>=200且X<300)才走梯子,否则换最近怪'
        if self._monsters:
            return '按Y差小+X近锁一只怪(同层优先,跨层最后)'
        return '原地等刷怪(无怪待命,正常)'

    def _stall_observer(self, now):
        """停滞纯观测(2026-09-17,只报【异常】栏、绝不发键/不干预、不另起线程,主线combat_tick后独立try调):
        运行中【有任务在身】却连续STALL_OBSERVE_MS无任一进展心跳(屏幕基点>=6/光点>=2/近2秒放过技能/怪数减少),
        满1秒首报、之后每秒一条"停滞N秒 当前=X 下一步=Y";无怪待命/拟人休息/正常长动作(确实在爬/下跳/起跳空中/平台回退)不报,恢复时报一条。
        判据口径与_global_stall_watchdog一致(那个是干预型、总开关关着只关不删),本方法只观测。"""
        if not self._running:
            return
        if getattr(self, '_aux_enable_rest', True) and now < getattr(self, '_rest_until', 0):
            self._stall_obs_baseline(now, active=False)
            return
        cs = getattr(self, '_climb_state', 'none')
        has_job = bool(self._monsters) or self._combat_locked_target is not None \\
            or getattr(self, '_combat_transit', False) or cs != 'none'
        exempt = (
            (cs == 'climbing' and getattr(self, '_climb_move_confirmed', False)) or
            cs == 'descend' or
            getattr(self, '_ladder_jump_phase', None) == 'post_jump' or
            getattr(self, '_platform_retreat_active', False)
        )
        sp = self._player_screen_pos
        mp = self._player_map_pos
        if self._obs_hb == 0:
            self._stall_obs_baseline(now)
            return
        moved = bool(sp is not None and self._obs_sp is not None and
                     (abs(sp[0] - self._obs_sp[0]) + abs(sp[1] - self._obs_sp[1])) >= GLOBAL_MOVE_PX)
        mapmoved = bool(mp is not None and self._obs_mp is not None and
                        (abs(mp[0] - self._obs_mp[0]) + abs(mp[1] - self._obs_mp[1])) >= GLOBAL_MAP_D)
        _last_atk = max(self._attack_last.values()) if self._attack_last else 0
        casting = (now - _last_atk) < GLOBAL_SKILL_HB_MS
        killed = len(self._monsters or []) < self._obs_nmon
        if exempt or moved or mapmoved or casting or killed or not has_job:
            if self._obs_active:
                self._rlog("停滞解除·恢复推进 当前=%s" % self._stall_state_text(cs),
                           log='exception', color=(0, 140, 0))
            self._stall_obs_baseline(now, active=False)
            return
        stall_ms = now - self._obs_hb
        secs = int(stall_ms // STALL_OBSERVE_MS)
        if stall_ms >= STALL_OBSERVE_MS and secs != self._obs_last_rep:
            self._obs_last_rep = secs
            self._obs_active = True
            self._rlog("停滞%d秒 当前=%s；下一步=%s" % (secs, self._stall_state_text(cs), self._stall_next_text(cs)),
                       log='exception', color=LOG_RED)

    def _global_stall_watchdog(self, now):'''
rep("    def _global_stall_watchdog(self, now):", METHODS, 1)

# 4) 主循环:战斗异常上屏 + 挂载停滞观测
rep(
"""            except Exception as e:
                print("[战斗] 异常:", e)
                import traceback; _debug_log("[战斗] 异常: " + str(e) + "\\n" + traceback.format_exc())""",
"""            except Exception as e:
                print("[战斗] 异常:", e)
                import traceback; _tb = traceback.format_exc(); _debug_log("[战斗] 异常: " + str(e) + "\\n" + _tb)
                try:
                    self._rlog("战斗线程异常:%s(已捕获未崩溃,详见debug.log)" % str(e)[:60], log='exception', color=LOG_RED)
                except Exception:
                    pass
            # 停滞纯观测(2026-09-17):独立try、只读不发键,有任务却1秒无进展报【异常】栏
            try:
                if not _aux_busy and not _hard_reset_done:
                    self._stall_observer(time.time() * 1000)
            except Exception as _oe:
                _debug_log("[停滞观测] 异常: %s" % _oe)""", 1)

with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(text)
print("B2 WRITTEN")
