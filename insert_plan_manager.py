import os

with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

plan_manager_code = '''
    # === 方案管理器 ===
    ROUTE_NAMES_FILE = os.path.join(DATA_DIR, "route_names.json")
    MAX_ROUTES = 100

    def _load_route_names(self):
        """加载方案名字映射 {id: name}"""
        names = {}
        if os.path.exists(self.ROUTE_NAMES_FILE):
            try:
                with open(self.ROUTE_NAMES_FILE, "r", encoding="utf-8") as f:
                    names = json.load(f)
            except Exception:
                pass
        return {str(k): v for k, v in names.items()}

    def _save_route_names(self, names):
        """保存方案名字映射"""
        try:
            with open(self.ROUTE_NAMES_FILE, "w", encoding="utf-8") as f:
                json.dump(names, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print("[方案] 保存名字失败: %s" % e)

    def _get_route_name(self, route_id):
        """获取方案显示名字"""
        names = self._load_route_names()
        return names.get(str(route_id), "方案%d" % route_id)

    def _set_route_name(self, route_id, name):
        """设置方案名字"""
        names = self._load_route_names()
        names[str(route_id)] = name
        self._save_route_names(names)

    def _show_route_manager(self):
        """显示方案管理器弹窗（独立OpenCV窗口）"""
        import tkinter as tk
        from tkinter import simpledialog

        self._route_mgr_selected = set()
        self._route_mgr_scroll = 0
        self._route_mgr_running = True

        win_name = "方案管理"
        win_w = min(440, UI_W - 20)
        win_h = min(700, UI_H - 20)
        cv2.namedWindow(win_name, cv2.WINDOW_AUTOSIZE)
        cv2.moveWindow(win_name, 100, 100)

        def on_mouse(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                if win_w - 30 <= x < win_w - 5 and 5 <= y < 25:
                    self._route_mgr_running = False
                    return
                sb_x = win_w - 15
                sb_y = 35
                sb_h = win_h - 50
                if sb_x <= x < sb_x + 10 and sb_y <= y < sb_y + sb_h:
                    per_page = (win_h - 50) // 30
                    max_scroll = max(0, self.MAX_ROUTES - per_page)
                    if max_scroll > 0:
                        rel = (y - sb_y) / sb_h
                        self._route_mgr_scroll = max(0, min(max_scroll, int(rel * max_scroll)))
                    return
                per_row = 4
                item_w = (win_w - 30) // per_row
                item_h = 28
                start_y = 35
                col = x // item_w
                row = (y - start_y) // item_h
                if 0 <= col < per_row and row >= 0:
                    idx = self._route_mgr_scroll + row * per_row + col
                    if 0 <= idx < self.MAX_ROUTES:
                        route_id = idx + 1
                        if route_id in self._route_mgr_selected:
                            self._route_mgr_selected.remove(route_id)
                        else:
                            self._route_mgr_selected.add(route_id)
            elif event == cv2.EVENT_RBUTTONDOWN:
                per_row = 4
                item_w = (win_w - 30) // per_row
                item_h = 28
                start_y = 35
                col = x // item_w
                row = (y - start_y) // item_h
                if 0 <= col < per_row and row >= 0:
                    idx = self._route_mgr_scroll + row * per_row + col
                    if 0 <= idx < self.MAX_ROUTES:
                        route_id = idx + 1
                        old_name = self._get_route_name(route_id)
                        root = tk.Tk()
                        root.withdraw()
                        new_name = simpledialog.askstring("改方案名字", "方案%d的新名字:" % route_id, initialvalue=old_name, parent=root)
                        root.destroy()
                        if new_name and new_name.strip():
                            self._set_route_name(route_id, new_name.strip())
            elif event == cv2.EVENT_MOUSEWHEEL:
                per_page = (win_h - 50) // 30
                max_scroll = max(0, self.MAX_ROUTES - per_page)
                if flags > 0:
                    self._route_mgr_scroll = max(0, self._route_mgr_scroll - 1)
                else:
                    self._route_mgr_scroll = min(max_scroll, self._route_mgr_scroll + 1)

        cv2.setMouseCallback(win_name, on_mouse)

        while self._route_mgr_running:
            img = np.ones((win_h, win_w, 3), dtype=np.uint8) * 240
            cv2.rectangle(img, (0, 0), (win_w, 30), (200, 200, 200), -1)
            cv2.putText(img, "Route Manager (L=select R=rename)", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
            cv2.rectangle(img, (win_w - 30, 5), (win_w - 5, 25), (0, 0, 200), -1)
            cv2.putText(img, "X", (win_w - 22, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            per_row = 4
            item_w = (win_w - 30) // per_row
            item_h = 28
            start_y = 35
            per_page = (win_h - 50) // item_h
            total_items = per_page * per_row
            start_idx = self._route_mgr_scroll
            for i in range(total_items):
                idx = start_idx + i
                if idx >= self.MAX_ROUTES:
                    break
                route_id = idx + 1
                row = i // per_row
                col = i % per_row
                x1 = col * item_w + 2
                y1 = start_y + row * item_h + 2
                x2 = x1 + item_w - 4
                y2 = y1 + item_h - 4
                selected = route_id in self._route_mgr_selected
                has_data = self._route_has_file(route_id)
                if selected:
                    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 255), 2)
                else:
                    cv2.rectangle(img, (x1, y1), (x2, y2), (255, 255, 255), 1)
                name = self._get_route_name(route_id)
                if not has_data:
                    name = "(empty)" + name
                color = (0, 0, 0) if has_data else (150, 150, 150)
                display = "%d:%s" % (route_id, name[:8])
                cv2.putText(img, display, (x1 + 3, y1 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
            sb_x = win_w - 15
            sb_y = 35
            sb_h = win_h - 50
            cv2.rectangle(img, (sb_x, sb_y), (sb_x + 10, sb_y + sb_h), (200, 200, 200), -1)
            max_scroll = max(1, self.MAX_ROUTES - per_page)
            thumb_h = max(20, int(sb_h * per_page / self.MAX_ROUTES))
            thumb_y = sb_y + int((self._route_mgr_scroll / max_scroll) * (sb_h - thumb_h))
            cv2.rectangle(img, (sb_x, thumb_y), (sb_x + 10, thumb_y + thumb_h), (100, 100, 100), -1)
            cv2.imshow(win_name, img)
            key = cv2.waitKey(30) & 0xFF
            if key == 27:
                self._route_mgr_running = False
        cv2.destroyWindow(win_name)
        print("[方案管理] 关闭，选中方案: %s" % sorted(self._route_mgr_selected))

'''

content = content.replace('    def run(self):', plan_manager_code + '    def run(self):', 1)

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('已插入方案管理器代码')
