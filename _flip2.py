# -*- coding: utf-8 -*-
import io
T=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
d=io.open(T,"r",encoding="utf-8",newline="").read()
crlf="\r\n" in d; c=d.replace("\r\n","\n")
E=[
("        FLOW_BOX, FLOW_TAIL_GAP, FLOW_MARGIN = 30, 40, 4   # 检测框=显示框30;框中心离光点40;块内边距4",
 "        FLOW_BOX, FLOW_TAIL_GAP, FLOW_MARGIN = 15, 40, 4   # 检测框=显示框15;框中心离光点40;块内边距4"),
("        _M = roi.shape[0]; _tsz = max(12, _M // 2); _t0 = (_M - _tsz) // 2; _hm = _M // 2  # 框40时模板20",
 "        _M = roi.shape[0]; _tsz = max(8, _M // 2); _t0 = (_M - _tsz) // 2; _hm = _M // 2   # 框15时模板8,搜索半径约4"),
("        _tsz = max(12, _M // 2); _t0 = (_M - _tsz) // 2   # 框40时模板20",
 "        _tsz = max(8, _M // 2); _t0 = (_M - _tsz) // 2   # 框15时模板8"),
("                    _lab = ('向下..' if _d > 0 else '向上..') if _axis == 'y' else ('向左..' if _d > 0 else '向右..')",
 "                    _lab = ('向上..' if _d > 0 else '向下..') if _axis == 'y' else ('向左..' if _d > 0 else '向右..')"),
("""                        _lab = ('向上..' if _idy < 0 else '向下..') if abs(_idy) >= abs(_idx) else ('向左..' if _idx < 0 else '向右..')""",
 """                        _lab = ('向下..' if _idy < 0 else '向上..') if abs(_idy) >= abs(_idx) else ('向右..' if _idx < 0 else '向左..')"""),
]
for i,(o,n) in enumerate(E):
    assert c.count(o)==1, (i,c.count(o))
    c=c.replace(o,n)
if crlf: c=c.replace("\n","\r\n")
io.open(T,"w",encoding="utf-8",newline="").write(c)
print("done 5 edits")
