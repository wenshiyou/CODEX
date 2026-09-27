# -*- coding: utf-8 -*-
# 直跳停稳加长(2→4帧)+对齐门槛0.6+当帧全松方向键;紫点漏检保持0.8s防闪。每处count==1,失败不写回。
import io, sys
PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    c0 = f.read()

edits = []

# 1) 紫点常量
edits.append((
 u'MONSTER_MAP_Y_SNAP = 10   # 紫点Y吸到绿线的最大偏差(小地图px,用户2026-09-26):|怪Y-绿线Y|≤10才拉到线上,超过不硬贴防跨层',
 u'MONSTER_MAP_Y_SNAP = 10   # 紫点Y吸到绿线的最大偏差(小地图px,用户2026-09-26):|怪Y-绿线Y|≤10才拉到线上,超过不硬贴防跨层\nPURPLE_KEEP_MS = 800        # 紫点漏检保持ms(用户2026-09-26):最后已知位置短暂保持防闪,超时消失\nPURPLE_MATCH_SCREEN_PX = 60 # 紫点跨帧关联阈值(屏幕px):此距离内视为同一只怪'))

# 2) 停稳帧数 2→4 + 新增对齐门槛常量
edits.append((
 u'LADDER_MM_STILL_FRAMES = 2       # 直跳需连续几拍停稳才原地跳(不在滑行中零速跳)',
 u'LADDER_MM_STILL_FRAMES = 4       # 直跳需连续几拍停稳才原地跳(用户2026-09-26:2帧太短没停透,改4≈180ms真停稳,goto/coast共用)\nLADDER_MM_ALIGN_OK_DX = 0.6  # 直跳起跳对齐门槛(小地图px,用户2026-09-26):|人梯X差|≤此值(≈0)才跳,治差1上不去'))

# 3) goto 直跳条件
edits.append((
 u'        if ad <= vl and self._ladder_mm_still_frames >= LADDER_MM_STILL_FRAMES:',
 u'        if ad <= LADDER_MM_ALIGN_OK_DX and self._ladder_mm_still_frames >= LADDER_MM_STILL_FRAMES:'))

# 4) settle 对齐条件
edits.append((
 u'        if ad <= max(float(vl), 0.6):',
 u'        if ad <= LADDER_MM_ALIGN_OK_DX:'))

# 5) 直跳当帧全松两套方向键(带上下文)
edits.append((
 u'        else:\n            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)\n        if VK_DOWN in self._random_move_keys:\n            self._key_up(VK_DOWN)\n        self._climb_start_y = py',
 u'        else:\n            self._release_move_conflicts()   # 直跳当帧两套左右(战斗+巡路)全松,治带方向跳(用户2026-09-26)\n        if VK_DOWN in self._random_move_keys:\n            self._key_up(VK_DOWN)\n        self._climb_start_y = py'))

# 6) 紫点绘制段替换
edits.append((
 u'        if self._monsters and self._player_map_pos and self._player_screen_pos:\n            COLOR_MONSTER_MAP = (255, 0, 255)  # 紫色BGR\n            for (x1, y1, x2, y2, score) in self._monsters:\n                mcx = (x1 + x2) // 2\n                mcy = y2\n                mpos = self._get_monster_map_pos_verified(mcx, mcy)\n                if mpos:\n                    dx_s = int(mpos[0] * scale_x)\n                    dy_s = int(mpos[1] * scale_y)\n                    if 0 <= dx_s < render_w and 0 <= dy_s < render_h:  # 边界检查用实际渲染尺寸\n                        cv2.circle(map_display, (dx_s, dy_s), 6, COLOR_MONSTER_MAP, -1)',
 u'        # 紫点稳定(用户2026-09-26):最后已知位置保持PURPLE_KEEP_MS,漏检不闪、渐淡;纯显示不碰锁怪\n        if self._player_map_pos and self._player_screen_pos:\n            COLOR_MONSTER_MAP = (255, 0, 255)  # 紫色BGR\n            for (_pmx, _pmy, _pratio) in self._purple_persist_update(int(time.time() * 1000)):\n                _dxs = int(_pmx * scale_x)\n                _dys = int(_pmy * scale_y)\n                if 0 <= _dxs < render_w and 0 <= _dys < render_h:\n                    _pc = COLOR_MONSTER_MAP if _pratio >= 1.0 else tuple(int(_v * _pratio) for _v in COLOR_MONSTER_MAP)\n                    cv2.circle(map_display, (_dxs, _dys), 6, _pc, -1)'))

# 7) 新增 persist 方法(插在 _get_monster_platform 前)
METHOD = u'''    def _purple_persist_update(self, now_ms):
        """紫点稳定(纯显示,用户2026-09-26):当前怪屏幕坐标最近邻关联到持久记录并更新小地图位置,
        漏检记录保持PURPLE_KEEP_MS(渐淡)、超时移除。返回[(map_x,map_y,ratio)],ratio=1实色、随漏检时长变淡。"""
        if not hasattr(self, '_purple_persist'):
            self._purple_persist = {}
            self._purple_seq = 0
        cur = []
        if self._monsters and self._player_map_pos and self._player_screen_pos:
            for (_x1, _y1, _x2, _y2, _sc) in self._monsters:
                _mcx = (_x1 + _x2) // 2
                _mcy = _y2
                _mp = self._get_monster_map_pos_verified(_mcx, _mcy)
                if _mp:
                    cur.append((_mcx, _mcy, _mp[0], _mp[1]))
        used = set()
        keep = {}
        for (_mcx, _mcy, _mx, _my) in cur:
            best = None; bd = 1e9
            for _key, _rec in self._purple_persist.items():
                if _key in used:
                    continue
                _d = abs(_rec['sx'] - _mcx) + abs(_rec['sy'] - _mcy)
                if _d < bd:
                    bd = _d; best = _key
            if best is not None and bd <= PURPLE_MATCH_SCREEN_PX:
                _rec = self._purple_persist[best]; used.add(best)
                _rec.update(sx=_mcx, sy=_mcy, mx=_mx, my=_my, t=now_ms)
                keep[best] = _rec
            else:
                self._purple_seq += 1
                keep[self._purple_seq] = {'sx': _mcx, 'sy': _mcy, 'mx': _mx, 'my': _my, 't': now_ms}
        for _key, _rec in self._purple_persist.items():
            if _key not in keep and now_ms - _rec['t'] <= PURPLE_KEEP_MS:
                keep[_key] = _rec
        self._purple_persist = keep
        out = []
        for _rec in keep.values():
            _age = now_ms - _rec['t']
            _ratio = 1.0 if _age <= 0 else max(0.3, 1.0 - _age / float(PURPLE_KEEP_MS))
            out.append((_rec['mx'], _rec['my'], _ratio))
        return out

    def _get_monster_platform(self, screen_x, screen_y):'''
edits.append((
 u'        return (map_x, map_y)\n\n    def _get_monster_platform(self, screen_x, screen_y):',
 u'        return (map_x, map_y)\n\n' + METHOD))

content = c0
for i, (old, new) in enumerate(edits, 1):
    c = content.count(old)
    if c != 1:
        print("[FAIL] edit%d count=%d -> abort" % (i, c)); sys.exit(1)
    content = content.replace(old, new, 1)
with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("DONE: %d edits applied" % len(edits))
