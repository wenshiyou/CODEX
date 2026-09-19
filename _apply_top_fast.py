# -*- coding: utf-8 -*-
"""原子改动①(用户2026-09-20 "1"批准):上行到顶增加"光点已到梯顶+后脑已开始消失"快判,
不干等 BACK_TOP_LOST_MS(已500→333)。双条件防09-19删光点判据时的坏/短梯误判:
  _end_y=0(没录到梯端)不触发;光点没到梯顶(还在梯中/梯底)不触发 → 退回后脑333ms兜底。
下行光点对梯底不变。maple 带 BOM/LF,只改 climbing 到顶判定这一段。"""
import codecs, py_compile

P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with open(P, 'rb') as f:
    raw = f.read()
assert raw.startswith(codecs.BOM_UTF8), 'maple 必须带 BOM'
text = raw.decode('utf-8-sig')

old1 = (
"            _top_by_back = bool(_up and self._ladder_back_top)\n"
"            _map_ok_down = bool((not _up) and bool(_end_y) and py >= _end_y - LADDER_TOP_ARRIVE_TOL)\n"
"            if _top_by_back or _map_ok_down:\n"
)
new1 = (
"            _top_by_back = bool(_up and self._ladder_back_top)\n"
"            # 上行快判(用户2026-09-20):后脑已开始消失(确在翻台,_lost计时已起)且小地图光点已到/越过录制梯顶→立即到顶,不干等BACK_TOP_LOST_MS;\n"
"            # 双条件防坏梯/梯底误判:_end_y=0(没录到梯端)不触发、光点没到梯顶(还在梯中/梯底)不触发,退回后脑333ms兜底\n"
"            _map_ok_up = bool(_up and bool(_end_y) and self._ladder_back_lost_since > 0 and py <= _end_y + LADDER_TOP_ARRIVE_TOL)\n"
"            _map_ok_down = bool((not _up) and bool(_end_y) and py >= _end_y - LADDER_TOP_ARRIVE_TOL)\n"
"            if _top_by_back or _map_ok_up or _map_ok_down:\n"
)
assert text.count(old1) == 1, 'old1 锚点数量=%d' % text.count(old1)
text = text.replace(old1, new1)

old2 = (
"                    self._climb_top_hold_why = (\"后脑连续%dms看不到=翻台到顶,补按%dms\" % (BACK_TOP_LOST_MS, LADDER_TOP_HOLD_MS)) if _top_by_back \\\n"
"                        else (\"光点重合梯底后多按%dms翻稳\" % LADDER_TOP_HOLD_MS)\n"
)
new2 = (
"                    if _top_by_back:\n"
"                        _why0 = \"后脑连续%dms看不到=翻台到顶,补按%dms\" % (BACK_TOP_LOST_MS, LADDER_TOP_HOLD_MS)\n"
"                    elif _map_ok_up:\n"
"                        _why0 = \"光点到梯顶且后脑已消失=快判到顶,补按%dms\" % LADDER_TOP_HOLD_MS\n"
"                    else:\n"
"                        _why0 = \"光点重合梯底后多按%dms翻稳\" % LADDER_TOP_HOLD_MS\n"
"                    self._climb_top_hold_why = _why0\n"
)
assert text.count(old2) == 1, 'old2 锚点数量=%d' % text.count(old2)
text = text.replace(old2, new2)

assert '\r' not in text, '出现 CR'
with open(P, 'wb') as f:
    f.write(codecs.BOM_UTF8 + text.encode('utf-8'))
py_compile.compile(P, doraise=True)
print('OK 上行光点到顶快判已落盘, py_compile pass, BOM/LF kept')
