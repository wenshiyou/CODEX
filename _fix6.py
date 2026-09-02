with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 恢复小地图尺寸（去掉四周内缩1px）
old_map = '''        new_map = {
            "left": left + 1,
            "top": top + TITLE_PAD + 1,
            "width": right - left - 2,
            "height": bottom - top - TITLE_PAD - 2
        }'''
new_map = '''        new_map = {
            "left": left,
            "top": top + TITLE_PAD,
            "width": right - left,
            "height": bottom - top - TITLE_PAD
        }'''
content = content.replace(old_map, new_map)

# 2. 绿框正常模式：到边贴边逻辑（宽高不变，整体移动）
old_normal = '''        elif self._blue_box and self._player_map_pos:
            # 正常模式：用偏移量绘制实线绿框，人物在框内任意位置（不强制中心）
            px, py = self._player_map_pos
            h, w = map_frame.shape[:2]
            bl_ox = self._blue_box.get("bl_ox", 0)
            bl_oy = self._blue_box.get("bl_oy", 0)
            tr_ox = self._blue_box.get("tr_ox", 0)
            tr_oy = self._blue_box.get("tr_oy", 0)
            # 四个角点（基于偏移量），四边边界限制
            tl_x = max(0, min(int(px + bl_ox), w - 1))
            tl_y = max(0, min(int(py + tr_oy), h - 1))
            br_x = max(0, min(int(px + tr_ox), w - 1))
            br_y = max(0, min(int(py + bl_oy), h - 1))
            cv2.rectangle(map_frame, (tl_x, tl_y), (br_x, br_y), (0, 255, 0), 1)'''
new_normal = '''        elif self._blue_box and self._player_map_pos:
            # 正常模式：用偏移量绘制实线绿框，到边贴边（宽高不变，整体移动）
            px, py = self._player_map_pos
            h, w = map_frame.shape[:2]
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            bl_ox = self._blue_box.get("bl_ox", 0)
            bl_oy = self._blue_box.get("bl_oy", 0)
            tr_ox = self._blue_box.get("tr_ox", 0)
            tr_oy = self._blue_box.get("tr_oy", 0)
            # 方框左上角（严格按偏移量，中间不偏移）
            box_x = int(px + bl_ox)
            box_y = int(py + tr_oy)
            # 到边贴边：任意一条边和小地图边重合时，不再向外移动
            if box_x < 0:
                box_x = 0               # 左边重合，不再向左
            elif box_x + bw > w:
                box_x = w - bw          # 右边重合，不再向右
            if box_y < 0:
                box_y = 0               # 上边重合，不再向上
            elif box_y + bh > h:
                box_y = h - bh          # 下边重合，不再向下
            cv2.rectangle(map_frame, (box_x, box_y), (box_x + bw, box_y + bh), (0, 255, 0), 1)'''
content = content.replace(old_normal, new_normal)

# 3. lock_screen_from_dot：到边贴边的归一化计算
old_lock = '''        if self._blue_box and "bl_ox" in self._blue_box:
            # 绿框已校准（含偏移量）：光点在绿框内归一化，人物在框内任意位置（不强制中心）
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            bl_ox, bl_oy = self._blue_box["bl_ox"], self._blue_box["bl_oy"]
            tr_ox, tr_oy = self._blue_box["tr_ox"], self._blue_box["tr_oy"]
            # 绿框左上角 = 光点 + 偏移量
            box_x = mx + bl_ox
            box_y = my + tr_oy
            rx = (mx - box_x) / float(bw) if bw > 0 else 0.5
            ry = (my - box_y) / float(bh) if bh > 0 else 0.5
            rx = max(0.0, min(1.0, rx))
            ry = max(0.0, min(1.0, ry))
            mode = "绿框"'''
new_lock = '''        if self._blue_box and "bl_ox" in self._blue_box:
            # 绿框已校准（含偏移量）：光点在绿框内归一化，到边贴边
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            bl_ox = self._blue_box["bl_ox"]
            tr_oy = self._blue_box["tr_oy"]
            # 绿框左上角 = 光点 + 偏移量，到边贴边
            box_x = mx + bl_ox
            box_y = my + tr_oy
            mw = r["width"]
            mh = r["height"]
            if box_x < 0:
                box_x = 0
            elif box_x + bw > mw:
                box_x = mw - bw
            if box_y < 0:
                box_y = 0
            elif box_y + bh > mh:
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
