# -*- coding: utf-8 -*-
# 拼接脚本v2:整段替换6143行起的旧下行函数区(_enter_desc_mm_ladder.._descend_step结束)
# 新结构=part1(影子状态+避梯+选侧)+旧_desc_horiz_walk(保留)+part2(mm入口/tick+新状态机)
import io

P = 'maple_route_ui.py'
lines = io.open(P, encoding='utf-8').read().split('\n')

# 锚点1:替换起点=旧_enter_desc_mm_ladder(6143)
a = next(i for i, l in enumerate(lines) if l.strip().startswith('def _enter_desc_mm_ladder'))
# 锚点2:保留段起点=_desc_horiz_walk(6113,在a之前)
h = next(i for i, l in enumerate(lines) if l.strip().startswith('def _desc_horiz_walk'))
assert h < a
# 锚点3:替换终点=_descend_step之后第一个同级def
d = next(i for i, l in enumerate(lines) if l.strip().startswith('def _descend_step'))
e = next(i for i in range(d + 1, len(lines)) if lines[i].strip().startswith('def '))
# 内容断言
seg = '\n'.join(lines[a:e])
for anchor in ('lad_grab', 'lad_slide', 'lad_fall_wait', 'check_drop', 'first_jump'):
    assert anchor in seg, '锚点缺失:' + anchor
assert 'random.choice' in '\n'.join(lines[a:d])   # 旧_pick_desc_side在区内

part1 = io.open('.trash/desc_part1.py', encoding='utf-8').read().rstrip('\n')
part2 = io.open('.trash/desc_part2.py', encoding='utf-8').read().rstrip('\n')

# 新顺序:_desc_horiz_walk(旧,保留) → part1(_dot_moving_state/_desc_ladder_side_blocked/_pick_desc_side新)
#         → part2(_enter_desc_mm_ladder新/_desc_mm_ladder_tick新/_descend_step新) → 后面原有函数
new_lines = lines[:a] + part1.split('\n') + [''] + part2.split('\n') + [''] + lines[e:]
io.open(P, 'w', encoding='utf-8', newline='\n').write('\n'.join(new_lines))
print('spliced: lines[%d:%d] replaced (%d old lines -> new descend)' % (a, e, e - a))
