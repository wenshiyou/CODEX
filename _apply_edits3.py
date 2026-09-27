# -*- coding: utf-8 -*-
"""补丁3:紫点Y按怪屏幕高低分层——收集所有X匹配台,选绿线Y最接近线性Y的台钉线,不再全钉第一条线。"""
import io, sys

TARGET = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(TARGET, "r", encoding="utf-8", newline="") as f:
    _raw = f.read()
_crlf = "\r\n" in _raw
content = _raw.replace("\r\n", "\n")

old = '''        """【模块B】怪物屏幕坐标转小地图坐标（人物锚点+相对偏移，Y用同平台绿线校准）
        X = 人物小地图X + (怪屏幕X - 人物屏幕X) * 自动X倍率。
        Y：平台游戏里怪必站某台,X判到哪台就取该台绿线在怪X处的高度(真实台高,不受爬梯镜头半随动影响);
           判不到台(不在选中台)才退回同层绿线校准+线性Y近似。
        参数：screen_x, screen_y = 怪物屏幕坐标（YOLO检测框的中心点X，底部Y）
        返回：(map_x, map_y) 小地图坐标；人物位置未知时返回None"""
        # 线性换算(X用自动倍率;Y为取景框兜底近似)
        pos_a = self._screen_to_map(screen_x, screen_y)
        if pos_a is None:
            return None
        map_x, map_y = pos_a
        # X判到选中台:怪站该台,Y直接钉该台绿线在map_x处高度(最准,不依赖Y倍率)
        _pf = self._get_monster_platform(screen_x, screen_y)
        if _pf is not None:
            _pf_best_y = None; _pf_best_dx = 999
            for (px, py) in self._platform_points(_pf):
                _dx = abs(px - map_x)
                if _dx < _pf_best_dx:
                    _pf_best_dx = _dx; _pf_best_y = py
            if _pf_best_y is not None:
                return (map_x, _pf_best_y)
        # 判不到台:同层(Y差<30)仍按X最近绿线校准,避免高处怪被拉到低层
        player_map_y = self._player_map_pos[1] if self._player_map_pos else None
        if player_map_y is not None and abs(map_y - player_map_y) < 30:
            best_y = None
            best_dx = 999
            for p in self.platforms:
                pts = self._platform_points(p)
                for (px, py) in pts:
                    dx = abs(px - map_x)
                    dy = abs(py - map_y)
                    # X最接近且Y偏差<15px（怪站在这个平台上）
                    if dx < best_dx and dy < 15:
                        best_dx = dx
                        best_y = py
            if best_y is not None:
                map_y = best_y
        return (map_x, map_y)'''

new = '''        """怪物屏幕坐标→小地图紫点（台子模式）。
        X = 人物小地图X + (怪屏幕X - 人物屏幕X) * 自动X倍率(录台子死区帧标定)。
        Y线性近似 = 人物小地图Y + (怪屏幕Y - 人物屏幕Y) * 取景框垂直比例(人物站平台时垂直为死区、比例可靠);
          再收集所有“X匹配map_x”的选中台(X重叠的上下层会有多个),选绿线Y最接近该线性Y的台、钉到它的绿线高度
          ——怪必站某台,上下层怪屏幕Y差几百px、远大于取景比例误差,会被分到各自层(修正“全钉第一条线、上下层挤一排”)。
        参数：screen_x, screen_y = 怪物屏幕坐标（YOLO检测框的中心点X，底部Y）
        返回：(map_x, map_y) 小地图坐标；人物位置未知时返回None"""
        # 线性换算(X自动倍率;Y取景框垂直比例,人物站平台时可靠)
        pos_a = self._screen_to_map(screen_x, screen_y)
        if pos_a is None:
            return None
        map_x, map_y = pos_a
        # 收集所有X匹配map_x的选中台,各取绿线在map_x处Y,选与线性map_y最近的层(按怪屏幕高低分层)
        _sel = self._active_platforms()
        _best_y = None; _best_dy = 999999
        if _sel and self.platforms:
            for pf in self.platforms:
                if (pf.get('id', 0) + 1) not in _sel:
                    continue
                _xmn, _xmx = self._platform_x_range(pf)
                if (_xmn - MONSTER_MAP_X_TOL) <= map_x <= (_xmx + MONSTER_MAP_X_TOL):
                    _py = None; _pdx = 999
                    for (px, py) in self._platform_points(pf):
                        _dx = abs(px - map_x)
                        if _dx < _pdx:
                            _pdx = _dx; _py = py
                    if _py is not None and abs(_py - map_y) < _best_dy:
                        _best_dy = abs(_py - map_y); _best_y = _py
        if _best_y is not None:
            return (map_x, _best_y)
        return (map_x, map_y)'''

c = content.count(old)
if c != 1:
    print("FAIL count=", c); sys.exit(1)
content = content.replace(old, new)
if _crlf:
    content = content.replace("\n", "\r\n")
with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("OK 补丁3已写回")
