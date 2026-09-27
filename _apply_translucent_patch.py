# -*- coding: utf-8 -*-
# 紫点漏检保持改为真半透明(alpha混合、保持紫相),不调暗变黑。count==1,失败不写回。
import io, sys
PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    content = f.read()

OLD = u'''            for (_pmx, _pmy, _pratio) in self._purple_persist_update(int(time.time() * 1000)):
                _dxs = int(_pmx * scale_x)
                _dys = int(_pmy * scale_y)
                if 0 <= _dxs < render_w and 0 <= _dys < render_h:
                    _pc = COLOR_MONSTER_MAP if _pratio >= 1.0 else tuple(int(_v * _pratio) for _v in COLOR_MONSTER_MAP)
                    cv2.circle(map_display, (_dxs, _dys), 6, _pc, -1)'''

NEW = u'''            for (_pmx, _pmy, _pratio) in self._purple_persist_update(int(time.time() * 1000)):
                _dxs = int(_pmx * scale_x)
                _dys = int(_pmy * scale_y)
                if not (0 <= _dxs < render_w and 0 <= _dys < render_h):
                    continue
                if _pratio >= 1.0:
                    cv2.circle(map_display, (_dxs, _dys), 6, COLOR_MONSTER_MAP, -1)
                else:
                    # 漏检保持=真半透明(alpha混合、保持紫色相),不调暗变黑;局部ROI叠加,点少开销极小
                    _r = 6
                    _x0 = max(0, _dxs - _r); _x1 = min(render_w, _dxs + _r + 1)
                    _y0 = max(0, _dys - _r); _y1 = min(render_h, _dys + _r + 1)
                    _roi = map_display[_y0:_y1, _x0:_x1]
                    _ov = _roi.copy()
                    cv2.circle(_ov, (_dxs - _x0, _dys - _y0), _r, COLOR_MONSTER_MAP, -1, cv2.LINE_AA)
                    cv2.addWeighted(_ov, _pratio, _roi, 1.0 - _pratio, 0, _roi)
                    map_display[_y0:_y1, _x0:_x1] = _roi'''

c = content.count(OLD)
if c != 1:
    print("[FAIL] count=%d -> abort" % c); sys.exit(1)
content = content.replace(OLD, NEW, 1)
with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("DONE: translucent applied")
