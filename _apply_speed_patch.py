# -*- coding: utf-8 -*-
# 提速:小地图光点20ms→10ms(100fps);人物基点忙档33ms→20ms(50fps)。count==1。
import io, sys
PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    content = f.read()
edits = [
 (u'PERSON_BUSY_TARGET_MS = 33       # 忙档目标周期≈30fps',
  u'PERSON_BUSY_TARGET_MS = 20       # 忙档目标周期≈50fps(用户2026-09-27:光点/基点刷新提速,上梯对位更跟手;跑不完自适应退避)'),
 (u'            time.sleep(0.020)',
  u'            time.sleep(0.010)  # 小地图光点10ms=100fps(用户2026-09-27提速,原20ms)'),
]
for i, (old, new) in enumerate(edits, 1):
    c = content.count(old)
    if c != 1:
        print("[FAIL] edit%d count=%d -> abort" % (i, c)); sys.exit(1)
    content = content.replace(old, new, 1)
with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("DONE: 2 edits")
