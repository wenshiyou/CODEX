# -*- coding: utf-8 -*-
"""判活双门:100ms开始看血条/伤害(_detect_open);满500ms仍无血无伤才判死drop(_attacked)。
maple(utf-8-sig/LF),唯一锚点assert。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(CP, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()

old = (
"        _attacked = False\n"
"        if _bl is not None and _fb and _fb.get('pos'):\n"
"            _fpos = _fb['pos']\n"
"            if abs(_fpos[0] - _bl[0]) <= 40 and abs(_fpos[1] - _bl[1]) <= 50:\n"
"                _first = _fb.get('first', 0) or 0\n"
"                # 过POST_STRIKE反馈窗才判(本轮处理的帧时间在出手之后=出手后新帧,杜绝拿旧帧误杀真怪)\n"
"                if _first and now_ms >= _first and (now_ms - _first) > POST_STRIKE_CHECK_MS:\n"
"                    _attacked = True\n"
"        # can_strike=锁在停步线+主攻Y带(真打得到);只有成立时才用\"无血无伤\"判死\n"
"        _in_skill = bool(_bl) and abs(_bl[0] - px) <= _stop and -_yup <= (_bl[1] - py) <= _ydn\n"
"        _has_dmg = False\n"
"        if _in_skill and _attacked:\n"
)
new = (
"        _attacked = False\n"
"        _detect_open = False   # 用户2026-09-20:100ms开始看伤害数字(判死仍走500ms截止)\n"
"        if _bl is not None and _fb and _fb.get('pos'):\n"
"            _fpos = _fb['pos']\n"
"            if abs(_fpos[0] - _bl[0]) <= 40 and abs(_fpos[1] - _bl[1]) <= 50:\n"
"                _first = _fb.get('first', 0) or 0\n"
"                _el = now_ms - _first\n"
"                # 用户2026-09-20:100ms起开始看血条/伤害(检测门);满500ms仍无血无伤才判死(判死门)\n"
"                if _first and now_ms >= _first and _el > POST_STRIKE_CHECK_MS:\n"
"                    _detect_open = True\n"
"                if _first and now_ms >= _first and _el > STRIKE_DEADLINE_MS:\n"
"                    _attacked = True\n"
"        # can_strike=锁在停步线+主攻Y带(真打得到);只有成立时才用\"无血无伤\"判死\n"
"        _in_skill = bool(_bl) and abs(_bl[0] - px) <= _stop and -_yup <= (_bl[1] - py) <= _ydn\n"
"        _has_dmg = False\n"
"        if _in_skill and _detect_open:\n"
)
assert s.count(old) == 1, "锚点命中%d次" % s.count(old)
s = s.replace(old, new)
with io.open(CP, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("TWODOOR_OK")
