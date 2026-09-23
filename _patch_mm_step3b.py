# -*- coding: utf-8 -*-
"""Step3b: 小地图直跳失败轮次判据 > 改为 >=,使"跑跳后最多3次直跳"(第3次失败即放弃),与用户'三次'口径一致。
仅改 _ladder_mm_realign 内一处(屏幕旧 _ladder_realign_jump 同名行不动,step6 整删)。"""
import io
P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(P, 'r', encoding='utf-8-sig', newline='') as f:
    text = f.read()
old = ("        if '跑跳' not in str(why):\r\n"
       "            self._ladder_realign_round = getattr(self, '_ladder_realign_round', 0) + 1\r\n"
       "            if self._ladder_realign_round > LADDER_REALIGN_MAX_ROUNDS:")
new = old.replace('> LADDER_REALIGN_MAX_ROUNDS:', '>= LADDER_REALIGN_MAX_ROUNDS:')
assert text.count(old) == 1, 'anchor count=%d' % text.count(old)
text = text.replace(old, new, 1)
with io.open(P, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(text)
print('STEP3b OK: realign round threshold -> >=')
