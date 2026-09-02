with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 正常模式绿框：中心模式+到边贴边（替换之前的偏移量模式）
old_normal = '''        elif self._blue_box and self._player_map_pos:
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

new_normal = '''        elif self._blue_box and self._player_map_pos:
            # 正常模式：中心模式+到边贴边（人物从左到右走，光点在框内从左到右移动）
            px, py = self._player_map_pos
            h, w = map_frame.shape[:2]
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            # 以人物为中心
            box_x = int(px - bw // 2)
            box_y = int(py - bh // 2)
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

# 2. lock_screen_from_dot：中心模式+到边贴边
old_lock = '''        if self._blue_box and "bl_ox" in self._blue_box:
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
            mode = "绿框"
        elif self._blue_box:
            # 旧版配置（只有宽高，无偏移量）：回退中心模式
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            box_x = max(0, min(mx - bw // 2, r["width"] - bw))
            box_y = max(0, min(my - bh // 2, r["height"] - bh))
            rx = (mx - box_x) / float(bw)
            ry = (my - box_y) / float(bh)
            mode = "绿框旧"'''

new_lock = '''        if self._blue_box:
            # 绿框已校准：中心模式+到边贴边，光点在绿框内归一化
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            mw = r["width"]
            mh = r["height"]
            # 以人物为中心，到边贴边
            box_x = mx - bw // 2
            box_y = my - bh // 2
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

# 3. 校准圆点小一半（半径3→2）
content = content.replace('CALIB_DOT_R = 3', 'CALIB_DOT_R = 2')

# 4. F4统一控制：在_handle_hotkey中，如果在校准模式，按F4保存退出
old_f4 = '''        if vk == VK_F4:
            print("[热键] 蓝色框校准 (F4)")
            self._start_blue_box_calibration()'''
new_f4 = '''        if vk == VK_F4:
            if self._calibrating_blue_box:
                # 校准模式下按F4：保存并退出（不管有没有改动点）
                self._save_and_exit_blue_box_calibration()
            else:
                # 正常模式下按F4：进入校准
                print("[热键] 绿框校准 (F4)")
                self._start_blue_box_calibration()'''
content = content.replace(old_f4, new_f4)

# 5. 新增 _save_and_exit_blue_box_calibration 函数（在 _start_blue_box_calibration 后面）
old_start_end = '''        else:
            self._blue_box_corners = {"bl": None, "tr": None}
            self._add_log("绿框校准：请点击小地图左下和右上的位置点")
            print("[绿框] 进入校准模式（新校准：左下+右上）")'''

new_start_end = '''        else:
            self._blue_box_corners = {"bl": None, "tr": None}
            self._add_log("绿框校准：请点击小地图左下和右上的位置点")
            print("[绿框] 进入校准模式（新校准：左下+右上）")

    def _save_and_exit_blue_box_calibration(self):
        """保存绿框校准并退出（不管有没有改动点，有已保存配置就用已有的）"""
        bl = self._blue_box_corners.get("bl")
        tr = self._blue_box_corners.get("tr")
        if bl is not None and tr is not None:
            # 两个点都齐了：计算大小+偏移量，保存
            self._calc_blue_box_from_corners()
            if self._blue_box is not None:
                self._save_blue_box()
                self._add_log("绿框已保存: %dx%d" % (self._blue_box["width"], self._blue_box["height"]))
            else:
                self._add_log("绿框太小，保存失败")
        elif self._blue_box is not None:
            # 点没齐但有已保存配置：用已有的，不改动
            self._add_log("绿框保持原配置: %dx%d" % (self._blue_box["width"], self._blue_box["height"]))
        else:
            self._add_log("没有点也没有已保存配置，无法保存")
        self._calibrating_blue_box = False
        self._selected_corner = None
        print("[绿框] 保存并退出校准模式")'''
content = content.replace(old_start_end, new_start_end)

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
