# -*- coding: utf-8 -*-
import io
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
b = io.open(p, 'rb').read()
bom = b[:3] == b'\xef\xbb\xbf'
s = b.decode('utf-8-sig').replace('\r\n', '\n')

# 改 box 计算:miss后不用白框,直接黑框ROI
old = '        box = None if need_full else (last[0] - rx, last[1] - ry, last[0] + rx, last[1] + ry)'
new = (
    '        if need_full:\n'
    '            box = None\n'
    '        elif tr["miss"] > 0:\n'
    '            # 用户2026-09-23:miss后不用白框(瞬移后人不在last附近),直接黑框ROI(小地图光点跟人走)\n'
    '            _dot0 = self._dot_fallback_pos()\n'
    '            if _dot0 is not None:\n'
    '                _brx0 = int(getattr(self, \'LOCK_BOX_RX\', 40) or 40)\n'
    '                _bry0 = int(getattr(self, \'LOCK_BOX_RY\', 40) or 40)\n'
    '                _H0, _W0 = frame.shape[:2]\n'
    '                box = (max(0, int(_dot0[0])-_brx0), max(0, int(_dot0[1])-_bry0),\n'
    '                       min(_W0, int(_dot0[0])+_brx0), min(_H0, int(_dot0[1])+_bry0))\n'
    '            else:\n'
    '                box = None  # 光点也没了(卡住)→全图不停扫\n'
    '        else:\n'
    '            box = (last[0] - rx, last[1] - ry, last[0] + rx, last[1] + ry)'
)
c = s.count(old)
assert c == 1, 'count=%d' % c
s = s.replace(old, new)

o = s.replace('\n', '\r\n')
io.open(p, 'wb').write((b'\xef\xbb\xbf' if bom else b'') + o.encode('utf-8'))
print('OK: miss后直接黑框ROI,不再白框空找')
