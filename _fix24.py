lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 删除屏幕人物Y方案三的死初始化（1302注释 + 1303/1304两行），小地图光点的 _y_smooth_window 不动
new_lines = []
removed = 0
for i, line in enumerate(lines):
    if '屏幕Y一秒最低值平滑缓冲' in line:
        removed += 1
        continue
    if 'self._screen_y_smooth_window = []' in line:
        removed += 1
        continue
    if 'self._screen_y_smooth_window_ms = 1000' in line:
        removed += 1
        continue
    new_lines.append(line)

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(new_lines)
print('删除死初始化行数:', removed)
