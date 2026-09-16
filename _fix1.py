# -*- coding: utf-8 -*-
import io, re
P = 'maple_route_ui.py'
s = io.open(P, encoding='utf-8', newline='').read()
before_field = len(re.findall(r'self\._ladder_realign_step(?!\s*\()', s))
before_call = len(re.findall(r'self\._ladder_realign_step\s*\(', s))
before_def = s.count('def _ladder_realign_step')
print('改前: 字段用法=%d 方法调用=%d 方法定义=%d' % (before_field, before_call, before_def))
# 只改字段(self._ladder_realign_step 后不跟括号=不是调用);def 无 self. 前缀天然不动
s2, n = re.subn(r'self\._ladder_realign_step(?!\s*\()', 'self._ladder_realign_px', s)
assert n == before_field == 5, ('替换数异常', n, before_field)
io.open(P, 'w', encoding='utf-8', newline='').write(s2)
print('已改名字段 %d 处' % n)
