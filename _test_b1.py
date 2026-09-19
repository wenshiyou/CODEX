# -*- coding: utf-8 -*-
"""块1a 验证：单攻射程内改为 Y近优先、Y同档再X近；范围外口径不变。直接调真实函数。"""
import sys
sys.path.insert(0, r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2')
import combat_logic as cl

px, py = 400, 300
cast_range = 100

# 用例1：射程内 A(X差10/Y差0) 与 B(X差5/Y差100)。旧纯X近会选B，新Y近必须选A
cand = [(10, 410, 300), (5, 405, 200)]
r = cl.pick_from_buckets(px, py, list(cand), [], cast_range, group_priority=False)
assert r['target'] == (410, 300), '用例1失败: %s' % r
assert r['state'] == 'cast', r

# 用例2：全在射程外，仍按 Y近→X近，选Y差5的A而非Y差100的B
cand2 = [(150, 550, 305), (120, 520, 200)]
r2 = cl.pick_from_buckets(px, py, list(cand2), [], cast_range, group_priority=False)
assert r2['target'] == (550, 305), '用例2失败: %s' % r2
assert r2['state'] == 'pursue', r2

# 用例3：Y差相同(同档)时取X近
cand3 = [(20, 420, 300), (8, 408, 300)]
r3 = cl.pick_from_buckets(px, py, list(cand3), [], cast_range, group_priority=False)
assert r3['target'] == (408, 300), '用例3失败: %s' % r3

# 用例4：群怪路径(group_priority=True)不受影响——射程内单向群攻仍按数量分桶
rg = cl.pick_from_buckets(px, py, [(10, 410, 300)], [], cast_range,
                          group_priority=True, group_radius=120, aoe_dual=False)
assert rg['target'] is not None, '用例4失败: %s' % rg

print('BLOCK1a pick_from_buckets 全部断言 PASS')
