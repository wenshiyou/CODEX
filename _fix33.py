# -*- coding: utf-8 -*-
# _fix33: 抓住梯子绑定录制梯时,把该梯duration_sec与算出的保命超时(duration+2s/无则默认12s)打进debug.log,便于真机核对变量已替换12秒。只改日志,不动逻辑。
import io
p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(p, "r", encoding="utf-8") as f:
    text = f.read()

old = (
    "        _debug_log(\"[选梯·上梯后绑定] 光点(%.0f,%s)直配录制梯x=%.0f 顶=%.0f 底=%.0f(不走倍率,到顶比光点Y与梯端)\" % (\n"
    "            _dx, (\"%.0f\" % _dy) if _dy is not None else \"NA\",\n"
    "            float(ld['x']), float(ld['y_top']), float(ld['y_bottom'])))\n"
)
new = (
    "        _bdur = self._climb_ladder_duration  # 已规范化: float>=1.0 或 None\n"
    "        _btimeout = (\"%.1fs\" % (_bdur + 2.0)) if isinstance(_bdur, (int, float)) else \"默认12s\"\n"
    "        _debug_log(\"[选梯·上梯后绑定] 光点(%.0f,%s)直配录制梯x=%.0f 顶=%.0f 底=%.0f 录制爬升=%s 保命超时=%s(不走倍率,到顶比光点Y与梯端)\" % (\n"
    "            _dx, (\"%.0f\" % _dy) if _dy is not None else \"NA\",\n"
    "            float(ld['x']), float(ld['y_top']), float(ld['y_bottom']),\n"
    "            (\"%.2fs\" % _bdur) if isinstance(_bdur, (int, float)) else \"无(旧梯)\",\n"
    "            _btimeout))\n"
)
n = text.count(old)
assert n == 1, "命中%d(应为1)" % n
text = text.replace(old, new)
with io.open(p, "w", encoding="utf-8", newline="") as f:
    f.write(text)
print("_fix33 OK, 绑定日志已补duration/保命超时")
