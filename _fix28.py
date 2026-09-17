# -*- coding: utf-8 -*-
# 诊断: 截图周期日志加 目标周期/本轮实际耗时, 分清3fps是sleep还是同步任务耗时
import io
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(P, "r", encoding="utf-8") as f:
    t = f.read()
old = (
'                _msg = "[截图耗时] %d轮 周期%s 截图%d (ms/秒)" % (\n'
'                    _dt_rounds, "精" if _precise_now else ("忙" if _busy else "闲"),\n'
'                    _dt_grab * 1000)\n'
)
new = (
'                _msg = "[截图耗时] %d轮 周期%s 截图%d 目标%.0fms 本轮%.0fms (ms/秒)" % (\n'
'                    _dt_rounds, "精" if _precise_now else ("忙" if _busy else "闲"),\n'
'                    _dt_grab * 1000, _period, _elapse)\n'
)
c = t.count(old)
assert c == 1, "锚点命中%d" % c
t = t.replace(old, new, 1)
with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(t)
print("诊断日志已加(目标周期/本轮耗时)")
