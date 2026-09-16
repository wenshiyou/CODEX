# -*- coding: utf-8 -*-
import io, os, re
p = 'debug.log'
lines = io.open(p, encoding='utf-8', errors='ignore').read().splitlines()
# 强信号
keep = ['跨层', '选梯', '白框', '对位', '起跳', '跑跳', '直跳', 'realign', 'post_jump',
        'to_lad', '上梯', '下梯', '梯集合', '梯顶', '抓梯', '抓住', '屏幕找梯', '找不到梯',
        '对齐', '分带', '助跑', 'climb', 'transit', '失败集合', '梯X', '梯(']
# 噪音排除
drop = ['[光点]', '[截图]', '[识别', '[血条', 'MP', 'FPS', '耗时', '角色跟踪', 'WM_PAINT', '战斗诊断', '空怪']
hit = []
for l in lines:
    if any(d in l for d in drop):
        continue
    if any(k in l for k in keep):
        hit.append(l)
for l in hit[-110:]:
    print(l[:170])
print('--- kept=%d / total=%d ---' % (len(hit), len(lines)))
