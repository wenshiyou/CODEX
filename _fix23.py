lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 删除方案二（17515-17531，索引17514-17530），替换成 py_layer = py
# 定位：从"# 打怪距离计算用Y变化率平滑（方案二"开始，到"self._screen_y_ground = py_layer"结束
start = None
end = None
for i, line in enumerate(lines):
    if '方案二·用户2026-09-16' in line and start is None:
        start = i
    if start is not None and 'self._screen_y_ground = py_layer' in line:
        end = i
        break

print('方案二范围(行):', start+1, '到', end+1)

new_block = [
    "        # 人怪Y分层用实时人物Y(用户2026-09-16:删除方案二Y变化率平滑,实测无效且污染地面Y)\n",
    "        py_layer = py\n",
]

new_lines = lines[:start] + new_block + lines[end+1:]
open('maple_route_ui.py', 'w', encoding='utf-8').writelines(new_lines)
print('方案二已删除，替换为 py_layer = py')
