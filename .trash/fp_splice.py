# -*- coding: utf-8 -*-
# 拼接:用融合预测器替换_dot_predict_pos+_predict_char_pos两方法(锚点断言,拼完自删)
import io

P = 'maple_route_ui.py'
lines = io.open(P, encoding='utf-8').read().split('\n')
a = next(i for i, l in enumerate(lines) if l.strip().startswith('def _dot_predict_pos'))
b = next(i for i, l in enumerate(lines) if l.strip().startswith('def _research_anchor_around_predict'))
seg = '\n'.join(lines[a:b])
assert '_predict_char_pos' in seg and '光点实测预测' in seg, '锚段不符'
fp = io.open('.trash/fp_method.py', encoding='utf-8').read().rstrip('\n')
lines[a:b] = fp.split('\n') + ['']
io.open(P, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
print('spliced %d->%d' % (a, b))
