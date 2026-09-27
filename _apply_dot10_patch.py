# -*- coding: utf-8 -*-
# 光点线程 sleep 20ms->10ms(100fps)。count==1。
import io, sys
PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    content = f.read()
old = u'            time.sleep(0.020)'
new = u'            time.sleep(0.010)  # 小地图光点10ms=100fps(用户2026-09-27提速,原20ms)'
c = content.count(old)
if c != 1:
    print("[FAIL] count=%d -> abort" % c); sys.exit(1)
content = content.replace(old, new, 1)
with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("DONE:光点10ms")
