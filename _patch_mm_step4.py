# -*- coding: utf-8 -*-
"""Step4: 上行上梯入口 _enter_to_ladder_up 末尾关B【锁怪】并当场清已锁(识怪/怪表/血条照常)。
新小地图goto不经过白框蒙板二帧稳建锁(旧关锁点18757随白框将删),必须在进段就关,否则对位/起跳时B仍锁怪
发打怪/移动指令抢左右键(真机呆住/左右抵消根因)。到顶_reset_lock_after_arrival、失败_decide_climb_fail_action
本就_set_b_lock_enabled(True)热表重锁,闭环完整。保持BOM/CRLF。"""
import io
P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(P, 'r', encoding='utf-8-sig', newline='') as f:
    text = f.read()
old = ("        self._ladder_mm_no_pick_t = 0\r\n"
       "        self._ladder_realign_round = 0\r\n")
assert text.count(old) == 1, 'anchor count=%d' % text.count(old)
new = old + (
    "        # 小地图上梯不经过白框蒙板建锁(旧关锁点随白框整套删除),进段即关【锁怪】并当场清已锁;\r\n"
    "        # 识怪/怪表/血条快照照常跑(只停锁怪决策)。到顶_reset_lock_after_arrival、失败_decide_climb_fail_action\r\n"
    "        # 都会_set_b_lock_enabled(True)用热怪表重锁(用户2026-09-21:识怪常开、锁怪可关、起跳一心上梯)。\r\n"
    "        self._set_b_lock_enabled(False, '进上梯·关锁专心爬梯')\r\n")
text = text.replace(old, new, 1)
with io.open(P, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(text)
print('STEP4 OK: disable B-lock on enter to_ladder_up')
