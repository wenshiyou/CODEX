with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_lock = '''        if self._blue_box:
            # 蓝色框已校准：光点在蓝色框内归一化（到边时框贴边，光点在框内移动，始终有效）
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            box_x = max(0, min(mx - bw // 2, r["width"] - bw))
            box_y = max(0, min(my - bh // 2, r["height"] - bh))
            rx = (mx - box_x) / float(bw)
            ry = (my - box_y) / float(bh)
            mode = "蓝框"'''

new_lock = '''        if self._blue_box and "bl_ox" in self._blue_box:
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
            mode = "绿框"
        elif self._blue_box:
            # 旧版配置（只有宽高，无偏移量）：回退中心模式
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            box_x = max(0, min(mx - bw // 2, r["width"] - bw))
            box_y = max(0, min(my - bh // 2, r["height"] - bh))
            rx = (mx - box_x) / float(bw)
            ry = (my - box_y) / float(bh)
            mode = "绿框旧"'''

content = content.replace(old_lock, new_lock)

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
