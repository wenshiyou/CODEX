# -*- coding: utf-8 -*-
# 人物地基帧率保底: 截图闲时100ms/忙时60ms, 上梯高帧不变(用户2026-09-17选推荐档)
import io
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(P, "r", encoding="utf-8") as f:
    t = f.read()

old = (
"                self._precise_ov_n = self._precise_rx_n = 0\n"
"                _period = self._perf_val('detect_busy_ms') if _busy else self._perf_val('detect_idle_ms')  # 忙/闲周期按CPU性能档\n"
)
new = (
"                self._precise_ov_n = self._precise_rx_n = 0\n"
"                # 人物地基帧率保底(用户2026-09-17):人物识别是永不停的地基线程、吃这里的帧,不能被闲时省电拖到3fps(333ms延迟);\n"
"                # 截图(mss BitBlt释放GIL)很便宜,YOLO/模板在B线程另按时间节流、帧多也不会多跑。忙(锁怪/0.4s内见怪)保底60ms≈16fps,闲保底100ms≈10fps;上梯高帧档(_precise_now)不变。\n"
"                _PERSON_BUSY_MAX_MS, _PERSON_IDLE_MAX_MS = 60, 100\n"
"                _period = (min(self._perf_val('detect_busy_ms'), _PERSON_BUSY_MAX_MS) if _busy\n"
"                           else min(self._perf_val('detect_idle_ms'), _PERSON_IDLE_MAX_MS))\n"
)
c = t.count(old)
assert c == 1, "锚点命中%d次" % c
t = t.replace(old, new, 1)
with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(t)
print("截图周期保底替换完成(忙60/闲100)")
