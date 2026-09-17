# -*- coding: utf-8 -*-
"""
_fix34b4.py  块5 失败/异常事件分流到【异常】栏 + H陈旧观测 + I陈旧目标纯观测
B 爬梯保命超时(上/下行,与正常到顶区分) / C 三次校准全失败 / D 找不到梯子白框(3处) / E 下台阶横跳没下去
G 识别B线程未捕获异常(限频3s) / H 人物坐标>800ms不刷新、识别B线程>1s没处理新帧(限频5s)
I 主攻已出手但锁定目标不在当前怪列表(纯观测限频5s)
只改日志归属/新增只读观测,不改任何判定与控制流。
"""
import io
PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    text = f.read()
def rep(old, new, n):
    global text
    c = text.count(old); assert c == n, "命中=%d 期望%d %r" % (c, n, old[:60])
    text = text.replace(old, new)

# 0) init 字段(挂在 b3 的 _freq_events 后)
rep(
"""        self._phantom_streak = 0
        self._freq_events = {}""",
"""        self._phantom_streak = 0
        self._freq_events = {}
        self._recognize_beat_t = 0    # 识别B线程处理新帧心跳(ms),H陈旧观测用(关怪扫上梯时仍扫梯子照跳)
        self._recog_err_last = 0      # 识别B线程异常上屏节流(ms)
        self._stale_rep = {}          # 人物坐标/识别线程陈旧观测上屏节流""", 1)

# 1) H/I 观测方法,插在 _wd_log 前(位于 b3 两个 _note 方法之后)
rep(
"""    def _wd_log(self, key, msg, color=(0, 0, 255)):""",
'''    def _note_stale_feeds(self, now):
        """H 坐标/识别线程陈旧纯观测(5秒一条,只报异常栏不干预):
        人物坐标>800ms不刷新=人物识别停摆/丢失;识别B线程>1s没处理新帧=B卡死(会发呆/不锁怪)。
        上梯关怪扫但B线程仍扫梯子、心跳照跳,不会误报;只有线程真卡死才报。"""
        if now - self._stale_rep.get('feed', 0) < 5000:
            return
        rc = getattr(self, '_raw_char_t', 0)
        if rc and now - rc > 800:
            self._stale_rep['feed'] = now
            try:
                self._rlog("人物坐标%.1f秒没刷新(人物识别疑似停摆/丢失)" % ((now - rc) / 1000.0),
                           log='exception', color=LOG_RED)
            except Exception:
                pass
            return
        bt = getattr(self, '_recognize_beat_t', 0)
        if bt and getattr(self, '_monster_running', False) and now - bt > 1000:
            self._stale_rep['feed'] = now
            try:
                self._rlog("怪物识别B线程%.1f秒没处理新帧(识别线程疑似卡住,会发呆/不锁怪)" % ((now - bt) / 1000.0),
                           log='exception', color=LOG_RED)
            except Exception:
                pass

    def _note_stale_target_attack(self, cx, cy, now):
        """I 纯观测(不干预,5秒一条):主攻已出手但锁定坐标不在当前怪列表任一框附近=在打陈旧/空目标。
        跨帧平滑可能短暂保留,故只低频提示;真正drop仍由空怪/列表规则负责。"""
        if now - self._freq_events.get('_cd_stale_atk', 0) < 5000:
            return
        for m in (self._monsters or []):
            try:
                if abs((m[0] + m[2]) / 2 - cx) <= 45 and abs(m[3] - cy) <= 55:
                    return
            except Exception:
                continue
        self._freq_events['_cd_stale_atk'] = now
        try:
            self._rlog("主攻已出手但锁定目标(%d,%d)不在当前怪列表(疑似打陈旧/空目标)" % (int(cx), int(cy)),
                       log='exception', color=LOG_RED)
        except Exception:
            pass

    def _wd_log(self, key, msg, color=(0, 0, 255)):''', 1)

# 2) _stall_observer 开头接 H 陈旧观测
rep(
"""        if not self._running:
            return
        if getattr(self, '_aux_enable_rest', True) and now < getattr(self, '_rest_until', 0):
            self._stall_obs_baseline(now, active=False)""",
"""        if not self._running:
            return
        self._note_stale_feeds(now)   # H:人物坐标/识别B线程陈旧观测(独立限频,不干预、不影响下面停滞判定)
        if getattr(self, '_aux_enable_rest', True) and now < getattr(self, '_rest_until', 0):
            self._stall_obs_baseline(now, active=False)""", 1)

# 3) B 上行:保命超时与正常光点重合到顶分流
rep(
'''                self._rlog("%s,到顶开打" % _arrive_why, LOG_OK, log='behavior')''',
'''                if str(_arrive_why).startswith("总超时"):
                    self._rlog("爬梯保命超时收尾:%s(没录到梯端或光点没重合,强制松键开打)" % _arrive_why, LOG_RED, log='exception')
                else:
                    self._rlog("%s,到顶开打" % _arrive_why, LOG_OK, log='behavior')''', 1)

# 4) B 下行:超时兜底与正常落地分流
rep(
'''                self._rlog("%s,落地接下一动作" % _why, log='behavior')''',
'''                if "超时" in str(_why):
                    self._rlog("下台保命超时兜底:%s(强制松键接下一动作)" % _why, LOG_RED, log='exception')
                else:
                    self._rlog("%s,落地接下一动作" % _why, log='behavior')''', 1)

# 5) C 三次校准全失败 -> 异常
rep(
'''            self._rlog("梯子校准%d轮没挂上,回主线打怪" % self._ladder_realign_round, LOG_RED, log='behavior')''',
'''            self._rlog("梯子校准%d轮都没挂上,回主线打怪(三次直跳失败)" % self._ladder_realign_round, LOG_RED, log='exception')''', 1)

# 6) D 找不到梯子白框(3处) -> 异常
rep(
'''                self._rlog("下行主窗口%.0fms没识别到梯子白框,放弃回主线" % LADDER_MERGE_WAIT_MS, LOG_RED, log='behavior')''',
'''                self._rlog("下行主窗口%.0fms没识别到梯子白框,放弃回主线" % LADDER_MERGE_WAIT_MS, LOG_RED, log='exception')''', 1)
rep(
'''                self._rlog("屏幕连续%.0fms找不到梯子,松键回主线打怪(不死等)" % LADDER_MERGE_WAIT_MS, LOG_RED, log='behavior')''',
'''                self._rlog("屏幕连续%.0fms找不到梯子,松键回主线打怪(不死等)" % LADDER_MERGE_WAIT_MS, LOG_RED, log='exception')''', 1)
rep(
'''            self._rlog("进主窗口%.0fms仍没识别到梯子白框,放弃回主线" % LADDER_MERGE_WAIT_MS, LOG_RED, log='behavior')''',
'''            self._rlog("进主窗口%.0fms仍没识别到梯子白框,放弃回主线" % LADDER_MERGE_WAIT_MS, LOG_RED, log='exception')''', 1)

# 7) E 下台阶横跳没下去转找梯 -> 异常(红字)
rep(
'''                self._rlog("横跳%.0fms没下去,直接主窗口找梯子" % _el, log='behavior')''',
'''                self._rlog("下台阶横跳%.0fms没下去,转主窗口找梯子" % _el, LOG_RED, log='exception')''', 1)

# 8) G 识别B线程未捕获异常上屏(限频3s)
rep(
'''            except Exception as _e:
                if self._monster_running:
                    print("[识别B] 异常:", _e)
                    _debug_log("[识别B] 异常:%s" % _e)
            time.sleep(0.010)''',
'''            except Exception as _e:
                if self._monster_running:
                    print("[识别B] 异常:", _e)
                    _debug_log("[识别B] 异常:%s" % _e)
                    try:
                        _en = time.time() * 1000
                        if _en - getattr(self, '_recog_err_last', 0) >= 3000:
                            self._recog_err_last = _en
                            self._rlog("怪物识别B线程异常:%s(已自保护未崩,见debug.log)" % str(_e)[:50], log='exception', color=LOG_RED)
                    except Exception:
                        pass
            time.sleep(0.010)''', 1)

# 9) B线程每处理一新帧刷新心跳(H)
rep(
'''                _rn = time.time()   # B耗时统计每秒一条''',
'''                _rn = time.time()   # B耗时统计每秒一条
                self._recognize_beat_t = _rn * 1000.0   # H陈旧观测心跳:每处理一新帧刷新(关怪扫上梯时仍扫梯子、照跳)''', 1)

# 10) I 主攻出手后陈旧目标纯观测
rep(
'''                self._combat_target_attacked = True  # 已对锁定目标出手：空怪判定用
                if not self._combat_first_strike_time:  # 仅记首次出手，持续攻击不刷新，保证130ms窗口后空怪能被drop''',
'''                self._combat_target_attacked = True  # 已对锁定目标出手：空怪判定用
                self._note_stale_target_attack(t_cx, t_cy, now)  # I纯观测:锁定目标不在当前怪列表(限频5s,不干预)
                if not self._combat_first_strike_time:  # 仅记首次出手，持续攻击不刷新，保证130ms窗口后空怪能被drop''', 1)

with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(text)
print("B4 WRITTEN")
