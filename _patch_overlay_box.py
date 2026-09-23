# -*- coding: utf-8 -*-
import io
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
b = io.open(p, 'rb').read()
bom = b[:3] == b'\xef\xbb\xbf'
s = b.decode('utf-8-sig').replace('\r\n', '\n')

EDITS = []

# 1) 蒙板画的框改成黑框ROI(光点±500),不画白框
EDITS.append((
    '蒙板框改黑框ROI',
    '        self._role_search_box = box  # 局部跟踪搜索范围框(全图重搜时=None不画),供蒙板可视化"在哪片区域找锚点"',
    '''        # 用户2026-09-23:蒙板只画黑框ROI(光点±500),不画白框(last±rx/ry)
        _dot_for_roi = self._dot_fallback_pos()
        if _dot_for_roi is not None:
            _brx_d = int(getattr(self, 'LOCK_BOX_RX', 40) or 40)
            _bry_d = int(getattr(self, 'LOCK_BOX_RY', 40) or 40)
            _Hd, _Wd = frame.shape[:2]
            self._role_search_box = (max(0, int(_dot_for_roi[0])-_brx_d), max(0, int(_dot_for_roi[1])-_bry_d),
                                     min(_Wd, int(_dot_for_roi[0])+_brx_d), min(_Hd, int(_dot_for_roi[1])+_bry_d))
        else:
            self._role_search_box = None'''
))

# 2) 框颜色白色->青色(区分白框)
EDITS.append((
    '框颜色白->青',
    'rpen = gdi32.CreatePen(0, 1, 0xFFFFFF)  # 白色1px=rx/ry局部搜索范围',
    'rpen = gdi32.CreatePen(0, 1, 0x00FFFF)  # 青色1px=黑框ROI(光点±500)'
))

for desc, old, new in EDITS:
    c = s.count(old)
    if c != 1:
        print('FAIL [%s] count=%d' % (desc, c))
        raise SystemExit(1)
    s = s.replace(old, new)

o = s.replace('\n', '\r\n')
io.open(p, 'wb').write((b'\xef\xbb\xbf' if bom else b'') + o.encode('utf-8'))
print('OK: %d处' % len(EDITS))
for desc, _, _ in EDITS:
    print('  -', desc)
