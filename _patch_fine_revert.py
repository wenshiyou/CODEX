# -*- coding: utf-8 -*-
"""回退 fine_tick gap 内 ad<=vl 直接跳(goto每帧重算band使该分支不可达;停稳判据统一在goto)。"""
import io
PATH = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(PATH, 'r', encoding='utf-8-sig', newline='') as f:
    s = f.read()
old = ("            if ad <= vl:\r\n"
       "                self._ladder_mm_fine_phase = ''\r\n"
       "                return self._ladder_mm_start_jump('vert', d, py, now_ms, jump_key)  # 微调到位直接直跳\r\n")
new = ("            if ad <= vl:\r\n"
       "                self._ladder_mm_fine_phase = ''   # 回goto:停稳判据唯一在goto,下帧停稳后vert起跳\r\n"
       "                return False\r\n")
n = s.count(old)
assert n == 1, 'fine gap 锚点命中%d(应1)' % n
s = s.replace(old, new)
with io.open(PATH, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(s)
print('FINE REVERT OK')
