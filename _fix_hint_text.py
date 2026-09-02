p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

# 修复：引导文字坐标改用屏幕坐标（因为SetWindowOrgEx把所有坐标当屏幕坐标处理）
old = '''                            if step_txt:
                                gdi32.SetTextColor(hdc, 0x0000FF)  # 红色文字（BGR格式）
                                gdi32.SetBkMode(hdc, 1)  # 透明背景
                                # 文字显示在窗口最上方白边（水平居中，垂直靠上）
                                txt_x = max(10, rect.right // 2 - 280)
                                txt_y = 15  # 窗口最上方白边
                                gdi32.TextOutW(hdc, txt_x, txt_y, step_txt, len(step_txt))'''

new = '''                            if step_txt:
                                gdi32.SetTextColor(hdc, 0x0000FF)  # 红色文字（BGR格式）
                                gdi32.SetBkMode(hdc, 1)  # 透明背景
                                # 文字显示在窗口最上方白边（水平居中，垂直靠上）
                                # SetWindowOrgEx已设原点为窗口屏幕左上角，此处必须用屏幕坐标
                                if self.window_rect:
                                    _wr = self.window_rect
                                    txt_x = _wr['left'] + max(10, rect.right // 2 - 280)
                                    txt_y = _wr['top'] + 15
                                else:
                                    txt_x = max(10, rect.right // 2 - 280)
                                    txt_y = 15
                                gdi32.TextOutW(hdc, txt_x, txt_y, step_txt, len(step_txt))'''

assert old in code, 'pattern not found'
code = code.replace(old, new)
print('Fix: calib hint text use screen coordinates')

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)
print('Done')
