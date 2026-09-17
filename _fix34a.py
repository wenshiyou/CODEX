# -*- coding: utf-8 -*-
"""
_fix34a.py  瞬移生效校验修正 + 瞬移前后摇 + 解卡/移动受阻功能彻底停用
2026-09-17 用户定稿：
  前摇 50→120ms；校验窗 350/800 → 450/1400ms；坐标陈旧/None 不判瞬移失败(治"闪了却误判无位移")；
  瞬移后摇 250ms 内压主攻/群攻/跳高打(硬直吞键)、移动照常不发呆；
  解卡/移动受阻放弃 4 个登记点 getattr 默认 True→False(总开关 __init__ 已 False,双重关死,函数体保留备用)。
每处 replace 都 assert 命中数,文件 UTF-8、newline='' 原样写回。
"""
import io, sys

PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"

with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    text = f.read()

def rep(old, new, n):
    c = text.count(old)
    assert c == n, "命中数=%d 期望%d, old=%r" % (c, n, old[:60])
    return text.replace(old, new)

edits = []

# 1) 校验窗常量 350/800 → 450/1400
edits.append((
"""TP_VERIFY_MS = 350        # 瞬移后等350ms(给瞬移动作+人物特征重定位时间)再开始校验
TP_VERIFY_TIMEOUT = 800   # 最多等到800ms,仍没朝预期方向位移=本次瞬移无效(被台距/墙挡/没蓝)""",
"""TP_VERIFY_MS = 450        # 瞬移后等450ms(给瞬移动作+人物特征全图重定位时间)再开始校验(2026-09-17:350→450,人物识别约330ms/帧,原350窗内常拿不到瞬移后新坐标)
TP_VERIFY_TIMEOUT = 1400  # 最多等到1400ms,覆盖全图重捕最坏2~3帧;坐标持续刷新却仍没朝预期位移才判本次瞬移无效(被台距/墙挡/没蓝)""",
1))

# 2) 前摇 50→120,新增后摇/坐标新鲜常量
edits.append((
"""TP_ATK_RELEASE_MS = 50    # 瞬移前置:先松主攻键再等50ms前摇(本游戏攻击硬直/瞬移前后摇没给够会吞键失效,用户2026-09-11:150→50先试)""",
"""TP_ATK_RELEASE_MS = 120   # 瞬移前置:先松主攻键再等120ms前摇(攻击硬直没结束会吞瞬移键;2026-09-17真机:50ms太短瞬移被吞、肉眼没看到闪,提到120与"单次按键≥120ms"铁律一致)
TP_POST_MS = 250          # 瞬移后摇:瞬移落地250ms内不发主攻/群攻/跳高打(瞬移硬直期发攻击会被吞),移动追怪照常,避免瞬移后空挥/发呆(2026-09-17用户定)
TP_COORD_FRESH_MS = 400   # 瞬移生效校验:人物画面坐标在400ms内刷新过才算"新鲜";坐标陈旧=全图重定位还没出新点,不判瞬移无效继续等(治"闪了却被误判无位移")""",
1))

# 3) init 新增瞬移后摇字段
edits.append((
"""        self._combat_tp_block_until = 0           # 对该目标禁用瞬移到的时间戳(ms)""",
"""        self._combat_tp_block_until = 0           # 对该目标禁用瞬移到的时间戳(ms)
        self._combat_tp_post_until = 0            # 瞬移后摇截止时间戳(ms):此前压制主攻/群攻/跳高打出手,移动照常(2026-09-17)""",
1))

# 4) init 人物画面坐标时间戳
edits.append((
"""        self._player_screen_pos = None  # (x,y) 人物画面坐标""",
"""        self._player_screen_pos = None  # (x,y) 人物画面坐标
        self._player_screen_t = 0       # 人物画面坐标最近一次刷新时间戳(ms),判坐标陈旧用(瞬移生效校验/坐标陈旧观测)""",
1))

# 5) init 后台人物脚位置时间戳
edits.append((
"""        self._raw_char_pos = None           # 后台线程算出的人物脚位置""",
"""        self._raw_char_pos = None           # 后台线程算出的人物脚位置
        self._raw_char_t = 0                # 后台线程最近一次发布人物脚位置的时间戳(ms)""",
1))

# 6) 后台线程发布人物点时同步时间戳
edits.append((
"""                self._raw_char_pos = _ch                 # 原子发布:动作线程直接读最新人物点""",
"""                self._raw_char_pos = _ch                 # 原子发布:动作线程直接读最新人物点
                self._raw_char_t = time.time() * 1000    # 同步发布坐标时间戳(判坐标新鲜/陈旧,瞬移校验防误判)""",
1))

# 7) 主循环透传坐标时间戳
edits.append((
"""                        self._player_screen_pos = self._raw_char_pos""",
"""                        self._player_screen_pos = self._raw_char_pos
                        self._player_screen_t = self._raw_char_t   # 透传坐标时间戳,瞬移校验据此判陈旧、坐标陈旧观测据此报警""",
1))

# 8) 两处战斗瞬移发起后置后摇截止(水平18041/竖直18063,文本相同一次替换2处)
edits.append((
"""                self._char_relocate_until = now + 700
""",
"""                self._char_relocate_until = now + 700
                self._combat_tp_post_until = now + TP_POST_MS  # 瞬移后摇:落地250ms内压技能不压移动
""",
2))

# 9) 校验函数重写:None/坐标陈旧不判失败,1400硬上限清pending不计数,新鲜+给足窗口仍不动才判真无效
edits.append((
"""        pen = self._combat_tp_pending
        if pen is None or px is None or py is None:
            return
        dt = now - pen['t']
        if dt < TP_VERIFY_MS:
            return
        if pen['axis'] == 'x':
            _prog = (px - pen['sx']) * pen['dir']     # 朝预期方向(右x增/左x减)为正
            moved = _prog >= TP_MIN_SCREEN_DX
        else:
            _prog = (py - pen['sy']) * pen['dir']     # 朝下(屏幕y增)/朝上(y减)为正
            moved = _prog >= TP_MIN_SCREEN_DY
        if moved:
            self._combat_tp_pending = None
            self._combat_tp_fail_cnt = 0
            self._combat_tp_fail_key = None
            return
        if dt < TP_VERIFY_TIMEOUT:
            return
        # 到超时仍无朝预期位移=本次瞬移无效
        _key = pen.get('key')
        if self._combat_tp_fail_key == _key:
            self._combat_tp_fail_cnt += 1
        else:
            self._combat_tp_fail_key = _key
            self._combat_tp_fail_cnt = 1
        _axis = '水平' if pen['axis'] == 'x' else '竖直'
        self._combat_tp_pending = None
        if self._combat_tp_fail_cnt >= TP_FAIL_MAX:
            self._combat_tp_block_until = now + TP_BLOCK_MS
            self._wd_log('tp_ineff', "%s瞬移连续%d次无位移=过不去,%.0f秒内对该目标改走路/跳/梯子" % (
                _axis, self._combat_tp_fail_cnt, TP_BLOCK_MS / 1000.0), color=(0, 0, 255))
        else:
            self._wd_log('tp_ineff1', "%s瞬移无位移(第%d次,进度%.0f),可能台距不够/被挡" % (
                _axis, self._combat_tp_fail_cnt, _prog))""",
"""        pen = self._combat_tp_pending
        if pen is None:
            return
        dt = now - pen['t']
        if dt < TP_VERIFY_MS:
            return
        # 坐标还没出来(瞬移后全图重定位中,人物点暂时None):不能判瞬移无效,继续等;
        # 到硬上限仍None=人物识别没跟上(不是瞬移的锅),清pending不计数,交"坐标陈旧"观测,既不误判也不永久挂起
        if px is None or py is None:
            if dt >= TP_VERIFY_TIMEOUT:
                self._combat_tp_pending = None
            return
        if pen['axis'] == 'x':
            _prog = (px - pen['sx']) * pen['dir']     # 朝预期方向(右x增/左x减)为正
            moved = _prog >= TP_MIN_SCREEN_DX
        else:
            _prog = (py - pen['sy']) * pen['dir']     # 朝下(屏幕y增)/朝上(y减)为正
            moved = _prog >= TP_MIN_SCREEN_DY
        if moved:
            self._combat_tp_pending = None
            self._combat_tp_fail_cnt = 0
            self._combat_tp_fail_key = None
            return
        # 没动先看坐标新不新鲜:瞬移后人物要全图重捕,坐标若仍是旧帧(没刷新到瞬移后位置),读到的px/py是瞬移前旧点,
        # _prog≈0是识别没跟上、不是瞬移失败——不计失败继续等;等满硬上限坐标仍陈旧=人物识别问题,清pending不计数(交坐标陈旧观测)
        if (now - getattr(self, '_player_screen_t', 0)) > TP_COORD_FRESH_MS:
            if dt >= TP_VERIFY_TIMEOUT:
                self._combat_tp_pending = None
            return
        if dt < TP_VERIFY_TIMEOUT:
            return
        # 坐标持续刷新(新鲜)、人却没离开起点、又给足1400ms窗口=瞬移真无效(攻击硬直吞键/被墙挡/没蓝)
        _key = pen.get('key')
        if self._combat_tp_fail_key == _key:
            self._combat_tp_fail_cnt += 1
        else:
            self._combat_tp_fail_key = _key
            self._combat_tp_fail_cnt = 1
        _axis = '水平' if pen['axis'] == 'x' else '竖直'
        _thr = TP_MIN_SCREEN_DX if pen['axis'] == 'x' else TP_MIN_SCREEN_DY
        self._combat_tp_pending = None
        if self._combat_tp_fail_cnt >= TP_FAIL_MAX:
            self._combat_tp_block_until = now + TP_BLOCK_MS
            self._wd_log('tp_ineff', "%s瞬移连续%d次无位移=过不去,%.0f秒内改走路/跳/梯子(等%.0fms,进度%.0f/阈值%d,坐标新鲜)" % (
                _axis, self._combat_tp_fail_cnt, TP_BLOCK_MS / 1000.0, dt, _prog, _thr), color=(0, 0, 255))
        else:
            self._wd_log('tp_ineff1', "%s瞬移无位移(第%d次,进度%.0f/阈值%d,坐标新鲜),可能台距不够/被挡" % (
                _axis, self._combat_tp_fail_cnt, _prog, _thr))""",
1))

# 10) 后摇门控·群攻
edits.append((
"""            if in_range >= 3 and now - last > aoe_cd:
                if random.random() < 0.8:""",
"""            if in_range >= 3 and now - last > aoe_cd and now >= getattr(self, '_combat_tp_post_until', 0):
                if random.random() < 0.8:""",
1))

# 11) 后摇门控·跳高打
edits.append((
"""                if abs(_ref_x - px) <= skill_range:
                    if _sj_mage:""",
"""                if abs(_ref_x - px) <= skill_range and now >= getattr(self, '_combat_tp_post_until', 0):
                    if _sj_mage:""",
1))

# 12) 后摇门控·平地主攻
edits.append((
"""            if (_stance_ok and in_attack_range   # 架构B:出手距离与走近/站定分水岭同源(实控=迟滞门;关=原t_dist<=stop_range)
                    and -_atk_y_up <= _dy_atk <= _atk_y_down
                    and _cd_ok):""",
"""            if (_stance_ok and in_attack_range   # 架构B:出手距离与走近/站定分水岭同源(实控=迟滞门;关=原t_dist<=stop_range)
                    and -_atk_y_up <= _dy_atk <= _atk_y_down
                    and _cd_ok
                    and now >= getattr(self, '_combat_tp_post_until', 0)):  # 瞬移后摇250ms内不发主攻(硬直吞键),移动照常不发呆""",
1))

# 13) 解卡/移动受阻 登记点默认值 True→False(4个活登记点18036/18071/18148/18188 + 1行已注释旧主循环18669,共5处;
#     总开关 __init__ 已 False,双重关死;函数体保留备用)
edits.append((
"getattr(self, '_aux_enable_unblock', True)",
"getattr(self, '_aux_enable_unblock', False)",
5))

for i, (old, new, n) in enumerate(edits, 1):
    text = rep(old, new, n)
    print("edit %2d ok (x%d)" % (i, n))

with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(text)
print("ALL WRITTEN")
