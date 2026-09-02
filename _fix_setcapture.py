p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

# 修复：蒙板窗口拖动时调用 SetCapture/ReleaseCapture，确保鼠标拖出窗口后仍能收到 WM_MOUSEMOVE

# 1. 在函数签名设置区域添加 SetCapture/ReleaseCapture
old_sig = '''        user32.EndPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]'''
new_sig = '''        user32.EndPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
        user32.SetCapture.argtypes = [wintypes.HWND]
        user32.SetCapture.restype = wintypes.HWND
        user32.ReleaseCapture.argtypes = []
        user32.ReleaseCapture.restype = wintypes.BOOL'''
assert old_sig in code, 'sig pattern not found'
code = code.replace(old_sig, new_sig)
print('Fix: added SetCapture/ReleaseCapture signatures')

# 2. WM_LBUTTONDOWN 中，点中绿点/蓝点后调用 SetCapture
old_down = '''                        if green_scr and abs(mx - green_scr[0]) <= 15 and abs(my - green_scr[1]) <= 15:
                            self._auto_calib_dragging = 'green'
                            return 0
                        if blue_scr and abs(mx - blue_scr[0]) <= 15 and abs(my - blue_scr[1]) <= 15:
                            self._auto_calib_dragging = 'blue'
                            return 0'''
new_down = '''                        if green_scr and abs(mx - green_scr[0]) <= 15 and abs(my - green_scr[1]) <= 15:
                            self._auto_calib_dragging = 'green'
                            user32.SetCapture(hwnd)  # 捕获鼠标，拖出窗口仍收WM_MOUSEMOVE
                            return 0
                        if blue_scr and abs(mx - blue_scr[0]) <= 15 and abs(my - blue_scr[1]) <= 15:
                            self._auto_calib_dragging = 'blue'
                            user32.SetCapture(hwnd)
                            return 0'''
assert old_down in code, 'down pattern not found'
code = code.replace(old_down, new_down)
print('Fix: SetCapture on WM_LBUTTONDOWN')

# 3. WM_LBUTTONUP 中调用 ReleaseCapture
old_up = '''                elif msg == 0x0202:  # WM_LBUTTONUP
                    if getattr(self, '_auto_calib_dragging', None):
                        self._auto_calib_dragging = None
                        return 0'''
new_up = '''                elif msg == 0x0202:  # WM_LBUTTONUP
                    if getattr(self, '_auto_calib_dragging', None):
                        self._auto_calib_dragging = None
                        user32.ReleaseCapture()  # 释放鼠标捕获
                        return 0'''
assert old_up in code, 'up pattern not found'
code = code.replace(old_up, new_up)
print('Fix: ReleaseCapture on WM_LBUTTONUP')

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)
print('Done')
