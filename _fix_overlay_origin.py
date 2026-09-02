p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

# 修复1：去掉 SetWindowOrgEx（所有绘制坐标都是截图坐标系=蒙板客户区坐标系，不需要转屏幕坐标）
old1 = '''                        # 设置窗口原点=蒙板窗口屏幕左上角，后续GDI绘制用屏幕坐标自动转换为客户区坐标
                        if self.window_rect:
                            _wr = self.window_rect
                            gdi32.SetWindowOrgEx(hdc, _wr['left'], _wr['top'], None)'''
new1 = '''                        # 蒙板客户区坐标 = 截图坐标系（以游戏窗口左上角为原点），所有绘制直接用截图坐标'''
assert old1 in code, 'fix1 pattern not found'
code = code.replace(old1, new1)
print('Fix1: removed SetWindowOrgEx (use client coords = screenshot coords)')

# 修复2：引导文字改回客户区坐标（去掉SetWindowOrgEx后不能用屏幕坐标）
old2 = '''                            if step_txt:
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
new2 = '''                            if step_txt:
                                gdi32.SetTextColor(hdc, 0x0000FF)  # 红色文字（BGR格式）
                                gdi32.SetBkMode(hdc, 1)  # 透明背景
                                # 文字显示在窗口最上方白边（水平居中，垂直靠上），客户区坐标
                                txt_x = max(10, rect.right // 2 - 280)
                                txt_y = 15
                                gdi32.TextOutW(hdc, txt_x, txt_y, step_txt, len(step_txt))'''
assert old2 in code, 'fix2 pattern not found'
code = code.replace(old2, new2)
print('Fix2: hint text back to client coords')

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)
print('Done')
