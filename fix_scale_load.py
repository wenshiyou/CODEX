with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    new_lines.append(line)
    # 第1263行（索引1262）是 self._calib_top_pt = cd.get("calib_top")
    if i == 1262 and 'calib_top_pt = cd.get' in line:
        indent = '                '  # 16空格
        new_lines.append(indent + '_sx = cd.get("scale_x")\n')
        new_lines.append(indent + '_sy = cd.get("scale_y")\n')
        new_lines.append(indent + 'if _sx is not None and _sy is not None:\n')
        new_lines.append(indent + '    self._calibrated_scale_x = _sx\n')
        new_lines.append(indent + '    self._calibrated_scale_y = _sy\n')
        new_lines.append(indent + '    self._map_screen_scale = _sx\n')
        new_lines.append(indent + '    print("[切换] 方案%d 加载倍率: scale_x=%.4f scale_y=%.4f" % (route_id, _sx, _sy))\n')

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('已插入倍率加载代码')
