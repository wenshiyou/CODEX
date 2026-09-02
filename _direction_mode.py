import io

path = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with io.open(path, 'r', encoding='utf-8') as f:
    src = f.read()

# 1. 修改 _start_blue_box_calibration：corners 改成 [None]*4
old_start = '''    def _start_blue_box_calibration(self):
        """开始蓝色框校准模式（偏移量模式）：角点存相对光点的偏移，人物移动时跟着动"""
        if not self.map_area_rect:
            self._add_log("请先绑定窗口检测小地图")
            return
        self._calibrating_blue_box = True
        self._blue_box_corners = []  # 存储偏移量(offset_x, offset_y)，不是绝对坐标
        self._selected_corner = -1
        self._add_log("蓝色框校准：点第一个角→带着走验证→再点下一个")
        print("[蓝色框] 进入校准模式（偏移量模式，角点跟随光点移动）")'''

new_start = '''    def _start_blue_box_calibration(self):
        """开始蓝色框校准模式（偏移量+方向模式）：角点按方向存储，同方向重复点击覆盖"""
        if not self.map_area_rect:
            self._add_log("请先绑定窗口检测小地图")
            return
        self._calibrating_blue_box = True
        # 按方向存储: [左上, 右上, 右下, 左下]，None=未点
        self._blue_box_corners = [None, None, None, None]
        self._selected_corner = -1
        self._add_log("蓝色框校准：点角点(同方向重复点覆盖)→带着走验证→S保存")
        print("[蓝色框] 进入校准模式（方向模式，同方向覆盖）")'''

src = src.replace(old_start, new_start, 1)

# 2. 修改 _handle_blue_box_click：判断方向，覆盖同方向
old_click = '''    def _handle_blue_box_click(self, map_x, map_y):
        """校准模式下处理小地图点击：记录偏移量(点击位置-光点位置)，角点跟随光点移动"""
        if not self._calibrating_blue_box:
            return False
        if not self._player_map_pos:
            self._add_log("未检测到人物光点，无法记录偏移")
            return False
        px, py = self._player_map_pos
        # 点击已有角点附近=选中（用显示位置=光点+偏移来判断）
        for i, (ox, oy) in enumerate(self._blue_box_corners):
            cx, cy = px + ox, py + oy
            if abs(map_x - cx) < 8 and abs(map_y - cy) < 8:
                self._selected_corner = i
                self._add_log("选中角点%d，方向键微调偏移" % (i + 1))
                return True
        # 记录新角点（偏移量 = 点击位置 - 光点位置）
        if len(self._blue_box_corners) < 4:
            offset_x = int(map_x - px)
            offset_y = int(map_y - py)
            self._blue_box_corners.append((offset_x, offset_y))
            self._selected_corner = len(self._blue_box_corners) - 1
            self._add_log("角点%d: 偏移(%d, %d)" % (len(self._blue_box_corners), offset_x, offset_y))
            if len(self._blue_box_corners) == 4:
                self._calc_blue_box_from_corners()
            return True
        return False'''

new_click = '''    def _handle_blue_box_click(self, map_x, map_y):
        """校准模式下处理小地图点击：按方向判断，同方向重复点击覆盖（以最后一次为准）"""
        if not self._calibrating_blue_box:
            return False
        if not self._player_map_pos:
            self._add_log("未检测到人物光点，无法记录偏移")
            return False
        px, py = self._player_map_pos
        offset_x = int(map_x - px)
        offset_y = int(map_y - py)
        # 按偏移量判断方向: 0=左上, 1=右上, 2=右下, 3=左下
        if offset_x < 0 and offset_y < 0:
            direction = 0
            dir_name = "左上"
        elif offset_x > 0 and offset_y < 0:
            direction = 1
            dir_name = "右上"
        elif offset_x > 0 and offset_y > 0:
            direction = 2
            dir_name = "右下"
        elif offset_x < 0 and offset_y > 0:
            direction = 3
            dir_name = "左下"
        else:
            # 偏移为0（点在光点正中心），忽略
            self._add_log("点击位置太靠近光点，请点在光点周围")
            return False
        # 点击已有角点附近=选中（用显示位置=光点+偏移来判断）
        for i, corner in enumerate(self._blue_box_corners):
            if corner is not None:
                ox, oy = corner
                cx, cy = px + ox, py + oy
                if abs(map_x - cx) < 8 and abs(map_y - cy) < 8:
                    self._selected_corner = i
                    self._add_log("选中%s角点，方向键微调" % ["左上","右上","右下","左下"][i])
                    return True
        # 覆盖同方向的点（以最后一次为准）
        existed = self._blue_box_corners[direction] is not None
        self._blue_box_corners[direction] = (offset_x, offset_y)
        self._selected_corner = direction
        action = "覆盖" if existed else "新增"
        self._add_log("%s%s角点: 偏移(%d, %d)" % (action, dir_name, offset_x, offset_y))
        # 四个方向都点了就计算蓝色框大小
        if all(c is not None for c in self._blue_box_corners):
            self._calc_blue_box_from_corners()
        return True'''

src = src.replace(old_click, new_click, 1)

# 3. 修改 _calc_blue_box_from_corners：处理 None
old_calc = '''    def _calc_blue_box_from_corners(self):
        """四个角点齐了，用偏移量范围计算蓝色框宽高"""
        offsets = self._blue_box_corners
        oxs = [o[0] for o in offsets]
        oys = [o[1] for o in offsets]
        width = max(oxs) - min(oxs)
        height = max(oys) - min(oys)
        if width > 10 and height > 10:
            self._blue_box = {"width": width, "height": height}
            self._add_log("蓝色框大小: %dx%d，S保存" % (width, height))
            print("[蓝色框] 计算大小: %dx%d" % (width, height))
        else:
            self._add_log("蓝色框太小，请重新校准")'''

new_calc = '''    def _calc_blue_box_from_corners(self):
        """四个角点齐了，用偏移量范围计算蓝色框宽高"""
        offsets = [c for c in self._blue_box_corners if c is not None]
        if len(offsets) < 2:
            return
        oxs = [o[0] for o in offsets]
        oys = [o[1] for o in offsets]
        width = max(oxs) - min(oxs)
        height = max(oys) - min(oys)
        if width > 10 and height > 10:
            self._blue_box = {"width": width, "height": height}
            self._add_log("蓝色框大小: %dx%d，S保存" % (width, height))
            print("[蓝色框] 计算大小: %dx%d" % (width, height))
        else:
            self._add_log("蓝色框太小，请重新校准")'''

src = src.replace(old_calc, new_calc, 1)

# 4. 修改 _handle_blue_box_key：处理 None
old_key = '''    def _handle_blue_box_key(self, key_code):
        """校准模式下键盘方向键微调选中角点的偏移量，S保存，Q退出"""
        if not self._calibrating_blue_box:
            return False
        if self._selected_corner < 0 or self._selected_corner >= len(self._blue_box_corners):
            return False
        ox, oy = self._blue_box_corners[self._selected_corner]
        step = 1
        if key_code == 0x25:  # 左
            ox -= step
        elif key_code == 0x27:  # 右
            ox += step
        elif key_code == 0x26:  # 上
            oy -= step
        elif key_code == 0x28:  # 下
            oy += step
        elif key_code == 0x53:  # S 保存
            self._calc_blue_box_from_corners()
            self._save_blue_box()
            self._calibrating_blue_box = False
            self._add_log("蓝色框已保存: %dx%d" % (self._blue_box["width"], self._blue_box["height"]))
            return True
        elif key_code == 0x51:  # Q 退出校准
            self._calibrating_blue_box = False
            self._add_log("退出蓝色框校准")
            return True
        else:
            return False
        self._blue_box_corners[self._selected_corner] = (ox, oy)
        if len(self._blue_box_corners) == 4:
            self._calc_blue_box_from_corners()
        return True'''

new_key = '''    def _handle_blue_box_key(self, key_code):
        """校准模式下键盘方向键微调选中角点的偏移量，S保存，Q退出"""
        if not self._calibrating_blue_box:
            return False
        if self._selected_corner < 0 or self._selected_corner >= 4:
            return False
        if self._blue_box_corners[self._selected_corner] is None:
            return False
        ox, oy = self._blue_box_corners[self._selected_corner]
        step = 1
        if key_code == 0x25:  # 左
            ox -= step
        elif key_code == 0x27:  # 右
            ox += step
        elif key_code == 0x26:  # 上
            oy -= step
        elif key_code == 0x28:  # 下
            oy += step
        elif key_code == 0x53:  # S 保存
            self._calc_blue_box_from_corners()
            self._save_blue_box()
            self._calibrating_blue_box = False
            self._add_log("蓝色框已保存: %dx%d" % (self._blue_box["width"], self._blue_box["height"]))
            return True
        elif key_code == 0x51:  # Q 退出校准
            self._calibrating_blue_box = False
            self._add_log("退出蓝色框校准")
            return True
        else:
            return False
        self._blue_box_corners[self._selected_corner] = (ox, oy)
        if all(c is not None for c in self._blue_box_corners):
            self._calc_blue_box_from_corners()
        return True'''

src = src.replace(old_key, new_key, 1)

# 5. 修改 _draw_blue_box：处理 None
old_draw = '''    def _draw_blue_box(self, map_frame):
        """在小地图帧上绘制蓝色框（校准模式角点=光点+偏移，跟随光点移动；正常模式画框）"""
        if self._calibrating_blue_box:
            if not self._player_map_pos:
                return
            px, py = self._player_map_pos
            display_corners = []
            for i, (ox, oy) in enumerate(self._blue_box_corners):
                cx, cy = int(px + ox), int(py + oy)
                display_corners.append((cx, cy))
                color = (0, 255, 255) if i == self._selected_corner else (255, 0, 0)
                if 0 <= cx < map_frame.shape[1] and 0 <= cy < map_frame.shape[0]:
                    cv2.circle(map_frame, (cx, cy), 4, color, -1)
                    cv2.putText(map_frame, str(i + 1), (cx + 6, cy - 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
            if len(display_corners) == 4:
                pts = np.array(display_corners, np.int32).reshape((-1, 1, 2))
                cv2.polylines(map_frame, [pts], True, (255, 0, 0), 1)
        elif self._blue_box and self._player_map_pos:
            # 正常模式：以光点为中心画蓝色框，到边贴边
            px, py = self._player_map_pos
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            r = self.map_area_rect
            box_x = int(max(0, min(px - bw // 2, r["width"] - bw)))
            box_y = int(max(0, min(py - bh // 2, r["height"] - bh)))
            cv2.rectangle(map_frame, (box_x, box_y), (box_x + bw, box_y + bh), (255, 0, 0), 1)'''

new_draw = '''    def _draw_blue_box(self, map_frame):
        """在小地图帧上绘制蓝色框（校准模式角点=光点+偏移，跟随光点移动；正常模式画框）"""
        if self._calibrating_blue_box:
            if not self._player_map_pos:
                return
            px, py = self._player_map_pos
            dir_names = ["左上", "右上", "右下", "左下"]
            display_corners = []
            for i, corner in enumerate(self._blue_box_corners):
                if corner is None:
                    continue
                ox, oy = corner
                cx, cy = int(px + ox), int(py + oy)
                display_corners.append((cx, cy))
                color = (0, 255, 255) if i == self._selected_corner else (255, 0, 0)
                if 0 <= cx < map_frame.shape[1] and 0 <= cy < map_frame.shape[0]:
                    cv2.circle(map_frame, (cx, cy), 4, color, -1)
                    cv2.putText(map_frame, dir_names[i], (cx + 6, cy - 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)
            if len(display_corners) >= 3:
                pts = np.array(display_corners, np.int32).reshape((-1, 1, 2))
                cv2.polylines(map_frame, [pts], True, (255, 0, 0), 1)
        elif self._blue_box and self._player_map_pos:
            # 正常模式：以光点为中心画蓝色框，到边贴边
            px, py = self._player_map_pos
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            r = self.map_area_rect
            box_x = int(max(0, min(px - bw // 2, r["width"] - bw)))
            box_y = int(max(0, min(py - bh // 2, r["height"] - bh)))
            cv2.rectangle(map_frame, (box_x, box_y), (box_x + bw, box_y + bh), (255, 0, 0), 1)'''

src = src.replace(old_draw, new_draw, 1)

with io.open(path, 'w', encoding='utf-8') as f:
    f.write(src)
print('DIRECTION MODE APPLIED')
