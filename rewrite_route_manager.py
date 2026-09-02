with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到旧的 _show_route_manager 方法并替换
old_start = '    def _show_route_manager(self):'
old_end = '        print("[方案管理] 关闭，选中方案: %s" % sorted(self._route_mgr_selected))'

start_idx = content.find(old_start)
end_idx = content.find(old_end) + len(old_end)

if start_idx == -1 or end_idx == -1:
    print("未找到方法边界")
else:
    new_method = '''    def _show_route_manager(self):
        """显示方案管理器弹窗（Tkinter窗口，左键多选，右键改名，双击清除）"""
        import tkinter as tk
        from tkinter import simpledialog, messagebox

        self._route_mgr_selected = set()
        win_w = min(440, UI_W - 20)
        win_h = min(700, UI_H - 20)

        root = tk.Tk()
        root.title("方案管理")
        root.geometry("%dx%d" % (win_w, win_h))
        root.attributes('-topmost', True)

        # 顶部标题
        title_frame = tk.Frame(root, bg="#e0e0e0", height=30)
        title_frame.pack(fill='x')
        tk.Label(title_frame, text="方案管理 (左键多选 右键改名 双击清除)", 
                 bg="#e0e0e0", font=("Microsoft YaHei", 10)).pack(side='left', padx=10)
        tk.Button(title_frame, text="X", command=root.destroy, bg="#c83232", 
                  fg="white", width=3, relief='flat').pack(side='right', padx=5)

        # 滚动区域
        canvas = tk.Canvas(root, bg="#f0f0f0")
        scrollbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg="#f0f0f0")

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 鼠标滚轮滚动
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)

        per_row = 4
        item_frames = {}

        def refresh_items():
            for widget in scroll_frame.winfo_children():
                widget.destroy()
            item_frames.clear()
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
                bg_color = "#f0f0f0"
                border_color = "#FFD700" if selected else "#ffffff"
                text_color = "#000000" if has_data else "#999999"

                item = tk.Frame(scroll_frame, bg=border_color, bd=2)
                item.grid(row=row, column=col, padx=3, pady=3, sticky='nsew')
                inner = tk.Frame(item, bg=bg_color)
                inner.pack(fill='both', expand=True, padx=1, pady=1)
                lbl = tk.Label(inner, text=display, bg=bg_color, fg=text_color,
                               font=("Microsoft YaHei", 9), width=10, height=1)
                lbl.pack(padx=2, pady=5)

                def on_left_click(e, rid=route_id):
                    if rid in self._route_mgr_selected:
                        self._route_mgr_selected.remove(rid)
                    else:
                        self._route_mgr_selected.add(rid)
                    refresh_items()

                def on_right_click(e, rid=route_id):
                    old_name = self._get_route_name(rid)
                    new_name = simpledialog.askstring("改方案名字", "方案%d的新名字:" % rid, 
                                                       initialvalue=old_name, parent=root)
                    if new_name and new_name.strip():
                        self._set_route_name(rid, new_name.strip())
                        refresh_items()

                def on_double_click(e, rid=route_id):
                    if messagebox.askyesno("确认清除", "确定要清除方案%d吗？" % rid, parent=root):
                        self._clear_route_file(rid)
                        if rid in self._route_mgr_selected:
                            self._route_mgr_selected.remove(rid)
                        refresh_items()

                lbl.bind("<Button-1>", on_left_click)
                inner.bind("<Button-1>", on_left_click)
                lbl.bind("<Button-3>", on_right_click)
                inner.bind("<Button-3>", on_right_click)
                lbl.bind("<Double-Button-1>", on_double_click)
                inner.bind("<Double-Button-1>", on_double_click)
                item_frames[route_id] = item

        refresh_items()
        root.mainloop()
        print("[方案管理] 关闭，选中方案: %s" % sorted(self._route_mgr_selected))
'''
    content = content[:start_idx] + new_method + content[end_idx:]
    with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('已替换方案管理器为Tkinter版本')
