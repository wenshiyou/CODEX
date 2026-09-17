lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 删光点测速日志
new_lines = []
skip = 0
for i, line in enumerate(lines):
    if skip > 0:
        skip -= 1
        continue
    if '[光点测速]' in line:
        # 删掉这行和前面的if行
        new_lines.pop()  # 删掉if not hasattr...那行
        skip = 2  # 跳过_debug_log那行
        continue
    new_lines.append(line)

# 删距离诊断日志
final_lines = []
skip = 0
for i, line in enumerate(final_lines):
    if skip > 0:
        skip -= 1
        continue
    if '[距离诊断]' in line:
        final_lines.pop()  # 删掉if not hasattr...那行
        skip = 2  # 跳过_debug_log那行
        continue
    final_lines.append(line)

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(final_lines)
print('删光点测速和距离诊断日志完成')
