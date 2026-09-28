# -*- coding: utf-8 -*-
"""临时:田字诊断日志,对比按键方向与光点实际位移。验证后删除。"""
import io, sys
TARGET = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(TARGET, "r", encoding="utf-8", newline="") as f:
    _raw = f.read()
_crlf = "\r\n" in _raw
content = _raw.replace("\r\n", "\n")
edits = []

edits.append(("1 变量",
"        _last_log = 0",
"        _last_log = 0\n        _last_dot = None   # 上一帧光点(块坐标),算光点帧间位移"))

edits.append(("2 dot位移",
"                _px, _py = int(_dot[0]), int(_dot[1])",
"                _px, _py = int(_dot[0]), int(_dot[1])\n                _ddx = _px - _last_dot[0] if _last_dot else 0\n                _ddy = _py - _last_dot[1] if _last_dot else 0\n                _last_dot = (_px, _py)"))

edits.append(("3 移动日志",
'''                    # [2026-09-27关闭] 田字诊断日志(80字符长,每秒4条,log=130ms帧率降到20)
                    # if _now_ms - _last_log >= 250: ...''',
'''                    if _now_ms - _last_log >= 300:
                        _last_log = _now_ms
                        _debug_log("[田诊]移 dot=(%d,%d) dotΔ=(%d,%d) key%s d=%d edge=%s r=%d/%d sc=%.2f ->%s"
                                   % (_px, _py, _ddx, _ddy, _axis, _d, _edge, _n_rounds, len(_hist), _score, _lab))'''))

edits.append(("4 原地日志",
'''                    # [2026-09-27关闭] 田字诊断日志(原地版)
                    # if _now_ms - _last_log >= 250: ...''',
'''                    if _now_ms - _last_log >= 300:
                        _last_log = _now_ms
                        _debug_log("[田诊]原 dot=(%d,%d) dotΔ=(%d,%d) still=%s n=%d ->%s"
                                   % (_px, _py, _ddx, _ddy, _still, len(_hist_idle), _lab))'''))

fails = []
for name, old, new in edits:
    c = content.count(old)
    if c == 1:
        content = content.replace(old, new); print("OK  ", name)
    else:
        fails.append((name, c)); print("FAIL", name, "count=", c)
if fails:
    print("\n有失败项,未写回。"); sys.exit(1)
if _crlf:
    content = content.replace("\n", "\r\n")
with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("\n补丁已写回")
