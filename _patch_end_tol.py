# -*- coding: utf-8 -*-
import io
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
b = io.open(p, 'rb').read()
bom = b[:3] == b'\xef\xbb\xbf'
s = b.decode('utf-8-sig').replace('\r\n', '\n')
old = 'LADDER_MM_END_TOL = 1       # 合格高度门=光点与梯连接端重合±1(用户2026-09-23定稿"直接选光点和梯底重合的,容差都不用"):上行|y_bottom-光点Y|<=1且梯身在人上方/下行|y_top-光点Y|<=1且梯身下通;差>=2即非本层梯排除(旧值10会选到悬在头顶的上段)'
new = 'LADDER_MM_END_TOL = 3       # 合格高度门=光点与梯连接端重合±3(真机小地图光点像素块与录制梯底固有2px系统偏差,±1把正确梯id2底104/光点106差2误杀;±3只放系统偏差,id0底98差8/id3底87差19仍被排除)'
assert s.count(old) == 1, 'count=%d' % s.count(old)
s = s.replace(old, new)
o = s.replace('\n', '\r\n')
io.open(p, 'wb').write((b'\xef\xbb\xbf' if bom else b'') + o.encode('utf-8'))
print('END_TOL 1->3 改完')
