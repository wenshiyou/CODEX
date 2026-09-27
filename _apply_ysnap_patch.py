# -*- coding: utf-8 -*-
# 紫点Y吸附设"度":仅|怪Y-绿线Y|<=10(小地图px)才拉到线上,超过不硬贴。每处count==1,失败不写回。
import io, sys
PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"

OLD1 = u'PLATFORM_LOCK_X_TOL = 100  # 平台锁怪X·台端外技能容差(游戏【窗口px】,用户2026-09-26动态锁怪):动态左右距离端外只留100'
NEW1 = OLD1 + u'\nMONSTER_MAP_Y_SNAP = 10   # 紫点Y吸到绿线的最大偏差(小地图px,用户2026-09-26):|怪Y-绿线Y|≤10才拉到线上,超过不硬贴防跨层'

OLD2 = u'                    if dx < best_dx and dy < 15:'
NEW2 = u'                    if dx < best_dx and dy <= MONSTER_MAP_Y_SNAP:'

with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    content = f.read()
for name, old, new in (("const", OLD1, NEW1), ("snap", OLD2, NEW2)):
    c = content.count(old)
    if c != 1:
        print("[FAIL] %s count=%d -> abort" % (name, c)); sys.exit(1)
content = content.replace(OLD1, NEW1, 1).replace(OLD2, NEW2, 1)
with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("DONE: const+snap applied")
