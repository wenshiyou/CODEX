with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修复绿框绘制：右边贴窗口边，不做max(0)限制
old_draw = '''        elif self._blue_box and self._player_map_pos:
            # 正常模式：中心模式+到边贴边（人物在中心时镜头跟随，绿框边到小地图边缘时镜头停止）
            px, py = self._player_map_pos
            h, w = map_frame.shape[:2]
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            # 以人物为中心
            box_x = int(px - bw // 2)
            box_y = int(py - bh // 2)
            # 到边贴边：用max-min限制，避免bw>w时if-elif冲突
            max_x = max(0, w - bw)   # 绿框左边最大可移动位置（bw>w时为0）
            max_y = max(0, h - bh)   # 绿框上边最大可移动位置
            box_x = max(0, min(box_x, max_x))
            box_y = max(0, min(box_y, max_y))
            cv2.rectangle(map_frame, (box_x, box_y), (box_x + bw, box_y + bh), (0, 255, 0), 1)'''

new_draw = '''        elif self._blue_box and self._player_map_pos:
            # 正常模式：中心模式+到边贴边（人物在中心时镜头跟随，绿框边到窗口边缘时镜头停止）
            px, py = self._player_map_pos
            h, w = map_frame.shape[:2]
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            # 以人物为中心
            box_x = int(px - bw // 2)
            box_y = int(py - bh // 2)
            # 到边贴边：左边贴窗口左边界，右边贴窗口右边界（不做max限制，bw>w时左边超出窗口）
            if box_x < 0:
                box_x = 0
            if box_x + bw > w:
                box_x = w - bw
            if box_y < 0:
                box_y = 0
            if box_y + bh > h:
                box_y = h - bh
            cv2.rectangle(map_frame, (box_x, box_y), (box_x + bw, box_y + bh), (0, 255, 0), 1)'''
content = content.replace(old_draw, new_draw)

# 2. 修复lock_screen_from_dot：同样处理
old_lock = '''        if self._blue_box:
            # 绿框已校准：中心模式+到边贴边，光点在绿框内归一化
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            mw = r["width"]
            mh = r["height"]
            # 以人物为中心，到边贴边（用max-min避免bw>mw时冲突）
            box_x = mx - bw // 2
            box_y = my - bh // 2
            max_x = max(0, mw - bw)
            max_y = max(0, mh - bh)
            box_x = max(0, min(box_x, max_x))
            box_y = max(0, min(box_y, max_y))
            rx = (mx - box_x) / float(bw) if bw > 0 else 0.5
            ry = (my - box_y) / float(bh) if bh > 0 else 0.5
            rx = max(0.0, min(1.0, rx))
            ry = max(0.0, min(1.0, ry))
            mode = "绿框"'''

new_lock = '''        if self._blue_box:
            # 绿框已校准：中心模式+到边贴边，光点在绿框内归一化
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            mw = r["width"]
            mh = r["height"]
            # 以人物为中心，到边贴边（左边贴0，右边贴mw-bw，不做max限制）
            box_x = mx - bw // 2
            box_y = my - bh // 2
            if box_x < 0:
                box_x = 0
            if box_x + bw > mw:
                box_x = mw - bw
            if box_y < 0:
                box_y = 0
            if box_y + bh > mh:
                box_y = mh - bh
            rx = (mx - box_x) / float(bw) if bw > 0 else 0.5
            ry = (my - box_y) / float(bh) if bh > 0 else 0.5
            rx = max(0.0, min(1.0, rx))
            ry = max(0.0, min(1.0, ry))
            mode = "绿框"'''
content = content.replace(old_lock, new_lock)

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
