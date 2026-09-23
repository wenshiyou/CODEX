# -*- coding: utf-8 -*-
import io
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
b = io.open(p, 'rb').read()
bom = b[:3] == b'\xef\xbb\xbf'
s = b.decode('utf-8-sig').replace('\r\n', '\n')

old = '''        if not cands:
            # 本帧无合格团:返回None交主循环丢点逻辑(不钉旧值、不冻结,用户2026-09-22)
            return None'''

new = '''        if not cands:
            # 用户2026-09-23:光门(蓝色覆盖层)把黄色光点盖住时,在上次光点位置±15内放宽阈值找透出的黄色像素
            try:
                _lp = getattr(self, '_player_map_pos', None)
                if _lp is not None:
                    _lx, _ly = int(_lp[0]), int(_lp[1])
                    _h, _w = bgr.shape[:2]
                    _x0, _y0 = max(0, _lx-15), max(0, _ly-15)
                    _x1, _y1 = min(_w, _lx+15), min(_h, _ly+15)
                    _sub = bgr[_y0:_y1, _x0:_x1]
                    if _sub.size > 0:
                        # 放宽黄色阈值B≤230(原205):光门下透出的黄色也能识别
                        _mask2 = cv2.inRange(_sub, np.array([0, 200, 200]), np.array([230, 255, 255]))
                        _ys, _xs = np.where(_mask2 > 0)
                        if len(_ys) >= 3:  # 至少3个黄色像素才算
                            _cx2 = int(round(_xs.mean())) + _x0
                            _cy2 = int(round(_ys.mean())) + _y0
                            if getattr(self, 'frame_count', 0) % 10 == 0:
                                _debug_log("[光点] 光门模糊重捕=(%d,%d) 上次=(%d,%d) 黄像素=%d" % (_cx2, _cy2, _lx, _ly, len(_ys)))
                            return (_cx2 + int(getattr(self, '_dot_center_off_x', 0) or 0),
                                    _cy2 + int(getattr(self, '_dot_center_off_y', 0) or 0))
            except Exception:
                pass
            # 本帧无合格团:返回None交主循环丢点逻辑(不钉旧值、不冻结,用户2026-09-22)
            return None'''

c = s.count(old)
assert c == 1, 'count=%d' % c
s = s.replace(old, new)

o = s.replace('\n', '\r\n')
io.open(p, 'wb').write((b'\xef\xbb\xbf' if bom else b'') + o.encode('utf-8'))
print('OK: 光门挡光点时,在上次位置±15放宽阈值重捕')
