p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

# 修复：全局拖动检测中，鼠标坐标直接用屏幕坐标，不转窗口坐标
# 因为基点bx,by是屏幕坐标，green_scr/blue_scr也是屏幕坐标
old = '''                # 鼠标拖动检测（全局GetAsyncKeyState，不依赖蒙板窗口消息）
                left_down = user32.GetAsyncKeyState(0x01) & 0x8000  # VK_LBUTTON
                cursor = POINT()
                user32.GetCursorPos(ctypes.byref(cursor))
                # 全局坐标转窗口坐标（减窗口左上角，和蒙板绘制/_capture_window一致）
                if self.window_rect:
                    mx = cursor.x - self.window_rect['left']
                    my = cursor.y - self.window_rect['top']
                else:
                    mx, my = cursor.x, cursor.y'''

new = '''                # 鼠标拖动检测（全局GetAsyncKeyState，不依赖蒙板窗口消息）
                left_down = user32.GetAsyncKeyState(0x01) & 0x8000  # VK_LBUTTON
                cursor = POINT()
                user32.GetCursorPos(ctypes.byref(cursor))
                # 直接用屏幕坐标（基点bx/by、green_scr/blue_scr都是屏幕坐标，必须一致）
                mx, my = cursor.x, cursor.y'''

assert old in code, 'pattern not found'
code = code.replace(old, new)
print('Fix: global drag detection use screen coordinates (not window coords)')

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)
print('Done')
