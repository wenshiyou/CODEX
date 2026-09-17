# -*- coding: utf-8 -*-
"""
_fix34b3.py  块4 高频异常计数 -> 【异常】栏
- 连续空打:第1次不报,第2次报一条(跳高打空/普通空怪两处drop计数);命中血条(_dl hp_confirmed)清零
- 1秒滑动窗高频:锁怪/换锁>=3次、建梯锁>=3次 各报一条(窗长冷却防刷)
- 左右横跳:监管线程 _wd_check_antijitter 命中(已有2.5s节流)并列上报异常栏
新增 _note_freq_event/_note_phantom_drop 两个纯上报辅助(不发键、不干预)。
"""
import io
PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    text = f.read()
def rep(old, new, n):
    global text
    c = text.count(old); assert c == n, "命中=%d 期望%d %r" % (c, n, old[:60])
    text = text.replace(old, new)

# 1) init 字段
rep(
"""        self._obs_active = False
        self._obs_last_rep = 0""",
"""        self._obs_active = False
        self._obs_last_rep = 0
        # 高频异常计数(2026-09-17):连续空打streak(第2次才报)+1秒滑动窗高频事件(锁怪/找梯>=3次)
        self._phantom_streak = 0
        self._freq_events = {}""", 1)

# 2) 两个上报辅助方法,插在 _wd_log 前
rep(
"""    def _wd_log(self, key, msg, color=(0, 0, 255)):""",
'''    def _note_freq_event(self, key, limit, win_ms, msg):
        """滑动窗高频事件计数:窗内达limit次往【异常】栏报一条,窗长冷却防刷屏。仅主线程调用。"""
        now = int(time.time() * 1000)
        d = self._freq_events
        lst = d.setdefault(key, [])
        lst[:] = [t for t in lst if now - t <= win_ms]
        lst.append(now)
        cdkey = '_cd_' + key
        if len(lst) >= limit and now - d.get(cdkey, 0) >= win_ms:
            d[cdkey] = now
            try:
                self._rlog(msg % len(lst), log='exception', color=LOG_RED)
            except Exception:
                pass

    def _note_phantom_drop(self, kind):
        """连续空打计数:第1次不报,第2次报【异常】栏(命中血条时在决策回传处清零)。"""
        self._phantom_streak = getattr(self, '_phantom_streak', 0) + 1
        if self._phantom_streak == 2:
            try:
                self._rlog("连续空打%d次(%s):出手无血条无伤害,疑似假怪/够不着,已连续换目标" % (self._phantom_streak, kind),
                           log='exception', color=LOG_RED)
            except Exception:
                pass

    def _wd_log(self, key, msg, color=(0, 0, 255)):''', 1)

# 3) 横跳并列上报异常栏(在2.5s节流门内)
rep(
"""        self._wd_log('wd_antijitter',
                     "原地左右横跳:%.1fs内换向%d次、光点净位移仅%.1f<%d[只观察不干预]" % (
                         AJ_WIN_MS / 1000.0, n, net, AJ_NET_MAP_DX), color=(0, 0, 255))""",
"""        self._wd_log('wd_antijitter',
                     "原地左右横跳:%.1fs内换向%d次、光点净位移仅%.1f<%d[只观察不干预]" % (
                         AJ_WIN_MS / 1000.0, n, net, AJ_NET_MAP_DX), color=(0, 0, 255))
        try:
            self._rlog("左右横跳:%.1fs内换向%d次、人没挪窝(净位移%.1f<%d),疑似打怪/巡路抢方向" % (
                AJ_WIN_MS / 1000.0, n, net, AJ_NET_MAP_DX), log='exception', color=LOG_RED)
        except Exception:
            pass""", 1)

# 4) 锁怪/换锁高频(_is_new_target块首)
rep(
"""            if _is_new_target:
                # 改打身边能直打的怪(cast)=不再去上层,清掉可能残留的锁定梯,防下帧又被拉回cross拉扯(用户2026-09-11)""",
"""            if _is_new_target:
                self._note_freq_event('lock_tgt', 3, 1000, "1秒内锁定/换锁怪%d次(疑似锁不住或假怪多)")
                # 改打身边能直打的怪(cast)=不再去上层,清掉可能残留的锁定梯,防下帧又被拉回cross拉扯(用户2026-09-11)""", 1)

# 5) 建梯锁高频
rep(
"""                                    _sel = (_rx, _ry, True)
                                    _stage = '建锁'""",
"""                                    _sel = (_rx, _ry, True)
                                    _stage = '建锁'
                                    self._note_freq_event('lock_lad', 3, 1000, "1秒内反复锁定梯子%d次(疑似掉锁/白框不稳)")""", 1)

# 6) 跳高打空计数
rep(
'''                    self._rlog("跳高打打空:无血条无伤害=这位置够不着(怪在上%dpx),改走梯子/瞬移" % (py_layer - t_cy), LOG_RED)''',
'''                    self._rlog("跳高打打空:无血条无伤害=这位置够不着(怪在上%dpx),改走梯子/瞬移" % (py_layer - t_cy), LOG_RED)
                    self._note_phantom_drop('跳高打空')''', 1)

# 7) 普通空怪计数
rep(
'''                    self._rlog("怪无血条/无伤害(已死或假怪,在上%+dpx),放弃并重新锁怪" % (py_layer - t_cy), LOG_RED)''',
'''                    self._rlog("怪无血条/无伤害(已死或假怪,在上%+dpx),放弃并重新锁怪" % (py_layer - t_cy), LOG_RED)
                    self._note_phantom_drop('普通空怪')''', 1)

# 8) 命中血条清零连续空打(cast/pursue两处相同两行块,count=2)
rep(
"""        self._combat_target_hp_confirmed = _dl['hp_confirmed']
        self._combat_gone_frames = _dl['gone_frames']""",
"""        self._combat_target_hp_confirmed = _dl['hp_confirmed']
        self._combat_gone_frames = _dl['gone_frames']
        if _dl.get('hp_confirmed'):
            self._phantom_streak = 0   # 命中血条=真怪在掉血,连续空打计数清零""", 2)

with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(text)
print("B3 WRITTEN")
