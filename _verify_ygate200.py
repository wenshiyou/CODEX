# -*- coding: utf-8 -*-
# 真实函数验证: 上行人梯Y差200硬门 (用户2026-09-20)
import maple_route_ui as M
C = M.MinimapRouteRecorder
P = C._dir_band_pick_ladder

# 用例1(复刻日志): 人(799,576) 怪X611在左; 高梯(806,270)Y差306 / 右梯(806,420)Y差156 / 左梯(700,400)Y差176
r1 = P([(806, 270), (806, 420), (700, 400)], 799, 576, 1, 611, x_half=300, y_far=200, y_near=0)
print('case1 选中=%s 理由=%s 带内=%s' % r1)
assert r1[0] == (700, 400), r1
assert (806, 270) not in r1[2], '高梯Y差306必须被排除'
assert (806, 420) in r1[2] and (700, 400) in r1[2]

# 用例2: 只有高梯(离人306) -> 带内无梯, 不锁
r2 = P([(806, 270)], 799, 576, 1, 611, x_half=300, y_far=200, y_near=0)
print('case2', r2[0], r2[1])
assert r2[0] is None and r2[1] == '带内无梯', r2

# 用例3: 怪在右(900), 200内右梯应被选
r3 = P([(806, 400), (700, 420)], 799, 576, 1, 900, x_half=300, y_far=200, y_near=0)
print('case3 选中=%s 理由=%s' % (r3[0], r3[1]))
assert r3[0] == (806, 400), r3

# 用例4: 边界 Y差=200(y376)在带; Y差=201(y375)排除
r4a = P([(806, 376)], 799, 576, 1, 900, x_half=300, y_far=200, y_near=0)
r4b = P([(806, 375)], 799, 576, 1, 900, x_half=300, y_far=200, y_near=0)
print('case4 dy200->%s  dy201->%s' % (r4a[0], r4b[0]))
assert r4a[0] == (806, 376) and r4b[0] is None

# 用例5: X>300 的梯排除(即便Y在200内)
r5 = P([(1200, 400)], 799, 576, 1, 900, x_half=300, y_far=200, y_near=0)
print('case5 X差401 ->', r5[0], r5[1])
assert r5[0] is None

# 用例6: 下行(cdir=-1)默认带不受影响, 脚下0~150能选
r6 = P([(806, 650)], 799, 576, -1, None)
print('case6 下行选中=%s 理由=%s' % (r6[0], r6[1]))
assert r6[0] == (806, 650), r6

print('Y_GATE_VERIFY_OK')
