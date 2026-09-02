with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''        if _in(BTN_SAVE, x, y):
            self._dropdown = "save" if self._dropdown != "save" else None; return
        if _in(BTN_PLAN, x, y):
            self._dropdown = "route" if self._dropdown != "route" else None; return'''

new = '''        if _in(BTN_SAVE, x, y):
            try:
                self._save()
                self._show_save_result("保存成功")
            except Exception as e:
                self._show_save_result("保存失败请重试")
            return
        if _in(BTN_PLAN, x, y):
            self._show_route_manager(); return'''

if old in content:
    content = content.replace(old, new, 1)
    print('已修改点击处理')
else:
    print('未找到旧代码')

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
