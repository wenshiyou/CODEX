with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 _show_route_manager 方法的开始和结束
start_marker = '    def _show_route_manager(self):'
end_marker = '        print("[方案管理] 关闭，选中方案: %s" % sorted(self._route_mgr_selected))'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)
if start_idx == -1 or end_idx == -1:
    print("未找到方法边界")
    exit(1)
end_idx = content.find('\n', end_idx) + 1

new_method = '''    def _show_route_manager(self):
        """显示方案管理器弹窗（Tkinter可调整大小窗口，记忆窗口大小，滚动列表，左键多选，右键改名，双击清除）"""
        import tkinter as tk
        from tkinter import simpledialog, messagebox

        self._route_mgr_selected = set()

        # 加载记忆的窗口大小
        size_file = os.path.join(DATA_DIR, "route_mgr_size.json")
        win_w, win_h = 440, 600
        if os.path.exists(size_file):
            try:
                with open(size_file, "r", encoding="utf-8") as f:
                    sd = json.load(f)
                win_w = sd.get("width", 440)
                win_h = sd.get("height", 600)
            except Exception:
                pass

        root = tk.Tk()
        root.title("方案管理")
        root.geometry("%dx%d+150+100" % (win_w, win_h))
        root.minsize(300, 300)

        # 顶部标题
        title_frame = tk.Frame(root, bg="#f0f0f0", height=30)
        title_frame.pack(fill='x', side='top')
        tk.Label(title_frame, text="方案管理 (左键多选 右键改名 双击清除)", 
                 font=("Microsoft YaHei", 10), bg="#f0f0f0").pack(side='left', padx=10)

        # 关闭时保存窗口大小
        def on_close():
            try:
                w = root.winfo_width()
                h = root.winfo_height()
                with open(size_file, "w", encoding="utf-8") as f:
                    json.dump({"width": w, "height": h}, f)
            except Exception:
                pass
            root.destroy()
        root.protocol("WM_DELETE_WINDOW", on_close)

        # 滚动区域
        canvas_frame = tk.Frame(root)
        canvas_frame.pack(fill='both', expand=True, padx=5, pady=5)

        canvas = tk.Canvas(canvas_frame, bg="white", highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)

        inner_frame = tk.Frame(canvas, bg="white")
        canvas_window = canvas.create_window((0, 0), window=inner_frame, anchor='nw')

        def on_inner_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner_frame.bind("<Configure>", on_inner_configure)

        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)

        # 鼠标滚轮滚动
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)

        # 刷新方案列表
        route_buttons = {}
        def refresh_list():
            for widget in inner_frame.winfo_children():
                widget.destroy()
            route_buttons.clear()
            # 每行4个，根据窗口宽度调整
            per_row = max(2, (inner_frame.winfo_width() - 10) // 100) if inner_frame.winfo_width() > 10 else 4
            for idx in range(self.MAX_ROUTES):
                route_id = idx + 1
                row = idx // per_row
                col = idx % per_row
                has_data = self._route_has_file(route_id)
                name = self._get_route_name(route_id)
                if not has_data:
                    display = "%d.(空)" % route_id
                else:
                    display = "%d.%s" % (route_id, name[:6])
                selected = route_id in self._route_mgr_selected
                bg_color = "#FFFF00" if selected else "white"
                fg_color = "black"
                btn = tk.Label(inner_frame, text=display, font=("Microsoft YaHei", 9),
                               bg=bg_color, fg=fg_color, bd=2, relief="solid",
                               width=10, height=1, anchor='center', padx=2, pady=2)
                btn.grid(row=row, column=col, padx=3, pady=3, sticky='nsew')
                # 左键点击切换选中
                def on_left_click(e, rid=route_id):
                    if rid in self._route_mgr_selected:
                        self._route_mgr_selected.remove(rid)
                    else:
                        self._route_mgr_selected.add(rid)
                    refresh_list()
                btn.bind("<Button-1>", on_left_click)
                # 右键改名
                def on_right_click(e, rid=route_id):
                    old_name = self._get_route_name(rid)
                    new_name = simpledialog.askstring("改方案名字", "方案%d的新名字:" % rid, 
                                                       initialvalue=old_name, parent=root)
                    if new_name and new_name.strip():
                        self._set_route_name(rid, new_name.strip())
                        refresh_list()
                btn.bind("<Button-3>", on_right_click)
                # 双击清除
                def on_double_click(e, rid=route_id):
                    if messagebox.askyesno("确认清除", "确定要清除方案%d吗？" % rid, parent=root):
                        self._clear_route_file(rid)
                        if rid in self._route_mgr_selected:
                            self._route_mgr_selected.remove(rid)
                        refresh_list()
                btn.bind("<Double-Button-1>", on_double_click)
                route_buttons[route_id] = btn
            # 设置列权重
            for c in range(per_row):
                inner_frame.grid_columnconfigure(c, weight=1)

        refresh_list()
        root.mainloop()
        print("[方案管理] 关闭，选中方案: %s" % sorted(self._route_mgr_selected))

'''

content = content[:start_idx] + new_method + content[end_idx:]

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('已重写方案管理器为Tkinter版本')
