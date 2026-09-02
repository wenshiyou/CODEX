p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

# 给 _on_mouse 加 try-except，防止单个异常导致整个回调失效(所有按钮点不动)
old_start = '''    def _on_mouse(self, event, x, y, flags, param):
        """鼠标点击回调：标签页切换 + 路线页按钮"""
        # 松开按钮：清除按下状态
        if event == cv2.EVENT_LBUTTONUP:
            self._pressed_btn = None'''
new_start = '''    def _on_mouse(self, event, x, y, flags, param):
        """鼠标点击回调：标签页切换 + 路线页按钮"""
        try:
            self._on_mouse_inner(event, x, y, flags, param)
        except Exception as _e:
            try:
                _debug_log("[鼠标] _on_mouse异常: %s" % _e)
                import traceback
                _debug_log(traceback.format_exc())
            except Exception:
                pass

    def _on_mouse_inner(self, event, x, y, flags, param):
        # 松开按钮：清除按下状态
        if event == cv2.EVENT_LBUTTONUP:
            self._pressed_btn = None'''
assert old_start in code, '_on_mouse start not found'
code = code.replace(old_start, new_start)
print('Fix: _on_mouse try-except wrapper added')

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)
print('Done')
