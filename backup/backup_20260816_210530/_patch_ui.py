import re

path = r"C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot\maple_route_ui.py"
with open(path, "r", encoding="utf-8") as f:
    src = f.read()

new_on_mouse = '''    def _on_mouse(self, event, x, y, flags, param):
        """鼠标点击回调：标签页切换 + 路线页按钮"""
        # 1. 顶部标签页切换
        if event == cv2.EVENT_LBUTTONDOWN:
            for tab, (tx, ty, tw, th) in self._tab_areas.items():
                if tx <= x < tx + tw and ty <= y < ty + th:
                    if tab != self._current_tab:
                        self._current_tab = tab
                        self._ui_bg = self._ui_bgs[tab]
                        self._dropdown = None
                        print("[标签页] 切换到:", tab)
                    return

        if self._current_tab != "route":
            return

        # 2. 手动框选模式（小地图合成区域内拖拽）
        if self._selecting:
            mx = int((x - UI_MAP_X) / UI_MAP_SCALE)
            my = int((y - UI_MAP_Y) / UI_MAP_SCALE)
            if my < 22:
                if event == cv2.EVENT_LBUTTONDOWN and mx < 48:
                    self._selecting = False
                    self._select_rect = None
                    self._select_dragging = False
            elif my >= MAP_H:
                if event == cv2.EVENT_LBUTTONDOWN:
                    self._selecting = False
                    self._select_rect = None
                    self._select_dragging = False
                    if getattr(self, '_was_random_running', False) and self.route_mode == "随机":
                        self._start_random()
            else:
                if event == cv2.EVENT_LBUTTONDOWN:
                    self._select_dragging = True
                    self._select_rect = (mx, my, mx, my)
                elif event == cv2.EVENT_MOUSEMOVE and self._select_dragging:
                    x1, y1, _, _ = self._select_rect
                    self._select_rect = (x1, y1, mx, my)
                elif event == cv2.EVENT_LBUTTONUP:
                    self._select_dragging = False
                    x1, y1, _, _ = self._select_rect
                    self._select_rect = (x1, y1, mx, my)
                    self._confirm_select()
                return

        if event != cv2.EVENT_LBUTTONDOWN:
            return

        # 3. 小地图区域内点击（刷新/手动）
        if UI_MAP_X <= x < UI_MAP_X + UI_MAP_W and UI_MAP_Y <= y < UI_MAP_Y + UI_MAP_H:
            mx = int((x - UI_MAP_X) / UI_MAP_SCALE)
            my = int((y - UI_MAP_Y) / UI_MAP_SCALE)
            if my < 22:
                if mx < 48:
                    print("[鼠标] 刷新")
                    self._auto_refresh = True
                    self._detect_minimap()
                    self.frame_count = 0
                    self.last_player_pos = None
                    return
                elif 50 <= mx < 98:
                    print("[鼠标] 手动框选")
                    self.manual_select_region()
                    return
            return

        # 4. 下拉菜单优先
        if self._dropdown is not None:
            btn_col_map = {"save": 2, "route": 3, "mode": 2, "clear_route": 3}
            col = btn_col_map[self._dropdown]
            col_x1 = UI_BTN_START_X + col * (UI_BTN_COL_W + UI_BTN_GAP)
            col_x2 = col_x1 + UI_BTN_COL_W
            items = self._dropdown_items()
            n = len(items)
            menu_h = n * DROPDOWN_ITEM_H
            menu_y1 = UI_BTN_ROW1_Y - menu_h
            if col_x1 <= x < col_x2 and menu_y1 <= y < UI_BTN_ROW1_Y:
                item_idx = (y - menu_y1) // DROPDOWN_ITEM_H
                if 0 <= item_idx < n:
                    self._handle_dropdown_item(self._dropdown, item_idx)
                self._dropdown = None
                return
            if col_x1 <= x < col_x2 and UI_BTN_ROW1_Y <= y < UI_BTN_ROW1_Y + UI_BTN_H:
                self._dropdown = None
                return
            self._dropdown = None

        # 5. 第一排按钮（平台/梯子/保存▼/方案▼）
        if UI_BTN_ROW1_Y <= y < UI_BTN_ROW1_Y + UI_BTN_H:
            col = (x - UI_BTN_START_X) // (UI_BTN_COL_W + UI_BTN_GAP)
            if col == 0:
                print("[鼠标] 平台")
                self._handle_hotkey(VK_F5)
            elif col == 1:
                print("[鼠标] 梯子")
                self._handle_hotkey(VK_F6)
            elif col == 2:
                self._dropdown = "save" if self._dropdown != "save" else None
            elif col == 3:
                self._dropdown = "route" if self._dropdown != "route" else None
            return

        # 6. 第二排按钮（清除平台/清除梯子/模式▼/清除方案▼）
        if UI_BTN_ROW2_Y <= y < UI_BTN_ROW2_Y + UI_BTN_H:
            col = (x - UI_BTN_START_X) // (UI_BTN_COL_W + UI_BTN_GAP)
            if col == 0:
                self._pop_platform()
            elif col == 1:
                self._pop_ladder()
            elif col == 2:
                self._dropdown = "mode" if self._dropdown != "mode" else None
            elif col == 3:
                self._dropdown = "clear_route" if self._dropdown != "clear_route" else None
            return

        # 7. 运行/停止
        if UI_RUN_Y <= y < UI_RUN_Y + UI_RUN_H:
            if UI_RUN_X <= x < UI_RUN_X + UI_RUN_W:
                print("[鼠标] 运行")
                if self.route_mode == "随机":
                    self._start_random()
                return
            if UI_STOP_X <= x < UI_STOP_X + UI_STOP_W:
                print("[鼠标] 停止")
                self._stop_random()
                return

        # 8. 子标签页（人物特征/特征清除/怪物数据）
        if UI_SUBTAB_Y <= y < UI_SUBTAB_Y + UI_SUBTAB_H:
            if 14 <= x < 112:
                print("[鼠标] 人物特征")
                self._capture_character_feature()
            elif 114 <= x < 212:
                print("[鼠标] 特征清除")
                self._clear_character_features()
            elif 214 <= x < 316:
                print("[鼠标] 怪物数据")
                self._add_log("YOLO模型未就绪")
            return

        # 9. 窗口绑定
        if UI_WINBIND_X <= x < UI_WINBIND_X + UI_WINBIND_W and UI_WINBIND_Y <= y < UI_WINBIND_Y + UI_WINBIND_H:
            print("[鼠标] 窗口绑定")
            self._bind_window()
            return

'''

new_draw = '''    def draw(self, map_area, player_pos):
        frame = self._ui_bg.copy()

        if self._current_tab != "route":
            return frame

        # === 渲染小地图内容 ===
        display = map_area.copy()
        h, w = display.shape[:2]
        for p in self.platforms:
            x1 = int(max(0, min(p["x_min"], w - 1)))
            x2 = int(max(0, min(p["x_max"], w - 1)))
            y = int(max(0, min(p["y_base"], h - 1)))
            cv2.line(display, (x1, y), (x2, y), COLOR_PLATFORM, 1)
        for l in self.ladders:
            x = int(max(0, min(l["x"], w - 1)))
            y1 = int(max(0, min(l["y_top"], h - 1)))
            y2 = int(max(0, min(l["y_bottom"], h - 1)))
            cv2.line(display, (x, y1), (x, y2), COLOR_LADDER, 1)
        if self.recording_platform and len(self.platform_points) > 1:
            cv2.polylines(display, [np.array(self.platform_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        if self.recording_ladder and len(self.ladder_points) > 1:
            cv2.polylines(display, [np.array(self.ladder_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        if player_pos:
            cv2.circle(display, player_pos, 2, COLOR_PLAYER, -1)
            cv2.circle(display, player_pos, 4, (0, 0, 255), 1)
        map_display = cv2.resize(display, (FIXED_W, MAP_H), interpolation=cv2.INTER_NEAREST)

        # 随机模式运行状态
        if self._random_running:
            state_text = {"idle": "选方案中", "moving": "移动中", "attacking": "攻击中", "returning": "返回起点"}.get(self._random_state, self._random_state)
            progress = "%d/%d" % (min(self._random_platform_idx + 1, len(self.platforms)), len(self.platforms)) if self.platforms else "0/0"
            status = "随机: %s 平台%s" % (state_text, progress)
            cv2.rectangle(map_display, (0, MAP_H - 20), (FIXED_W, MAP_H), (25, 25, 25), -1)
            cv2.putText(map_display, status, (6, MAP_H - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1)

        # 左上角文字按钮
        cv2.rectangle(map_display, (0, 0), (195, 22), (25, 25, 25), -1)
        refresh_color = (0, 255, 0) if self._auto_refresh else (0, 165, 255)
        cv2.putText(map_display, "刷新", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, refresh_color, 1)
        cv2.putText(map_display, "手动", (52, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
        if self.route_mode == "随机":
            cv2.putText(map_display, "随机", (100, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
        else:
            route_text = "方案" + "一二三"[self.current_route - 1]
            cv2.putText(map_display, route_text, (100, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)

        # 手动框选拖拽矩形
        if self._selecting and self._select_rect and self._select_dragging:
            x1, y1, x2, y2 = self._select_rect
            cv2.rectangle(map_display, (x1, y1), (x2, y2), (0, 255, 255), 1)

        # === 缩放到UI尺寸并合成到背景 ===
        map_scaled = cv2.resize(map_display, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H, UI_MAP_X:UI_MAP_X+UI_MAP_W] = map_scaled

        # === 下拉菜单 ===
        if self._dropdown is not None:
            items = self._dropdown_items()
            n = len(items)
            btn_col_map = {"save": 2, "route": 3, "mode": 2, "clear_route": 3}
            col = btn_col_map[self._dropdown]
            col_x1 = UI_BTN_START_X + col * (UI_BTN_COL_W + UI_BTN_GAP)
            col_x2 = col_x1 + UI_BTN_COL_W
            menu_h = n * DROPDOWN_ITEM_H
            menu_y1 = UI_BTN_ROW1_Y - menu_h
            cv2.rectangle(frame, (col_x1, menu_y1), (col_x2 - 1, UI_BTN_ROW1_Y - 1), (58, 58, 58), -1)
            cv2.rectangle(frame, (col_x1, menu_y1), (col_x2 - 1, UI_BTN_ROW1_Y - 1), (110, 110, 110), 1)
            for i, text in enumerate(items):
                iy = menu_y1 + i * DROPDOWN_ITEM_H
                if i > 0:
                    cv2.line(frame, (col_x1 + 3, iy), (col_x2 - 4, iy), (85, 85, 85), 1)
                is_current = False
                if self._dropdown == "route" and (i + 1) == self.current_route:
                    is_current = True
                elif self._dropdown == "mode" and text == self.route_mode:
                    is_current = True
                if is_current:
                    cv2.rectangle(frame, (col_x1 + 1, iy + 1), (col_x2 - 2, iy + DROPDOWN_ITEM_H - 1), (0, 70, 0), -1)
                color = (0, 255, 0) if is_current else (240, 240, 240)
                cv2.putText(frame, text, (col_x1 + 6, iy + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1)

        # === 日志区域 ===
        if self._logs:
            log_y = UI_LOG_Y + 14
            for log in self._logs[-4:]:
                cv2.putText(frame, log, (UI_LOG_X + 4, log_y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (60, 60, 60), 1)
                log_y += 14

        return frame

'''

# Replace _on_mouse method
pattern_mouse = re.compile(r'    def _on_mouse\(self, event, x, y, flags, param\):.*?(?=\n    def draw\()', re.DOTALL)
src = pattern_mouse.sub(new_on_mouse, src)

# Replace draw method
pattern_draw = re.compile(r'    def draw\(self, map_area, player_pos\):.*?(?=\n    def manual_select_region\()', re.DOTALL)
src = pattern_draw.sub(new_draw, src)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)

print("Replaced _on_mouse and draw methods")
