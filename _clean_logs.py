lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 删黑框方向日志（14933-14936行）
new_lines = []
skip = 0
for i, line in enumerate(lines):
    if skip > 0:
        skip -= 1
        continue
    if '[黑框方向]' in line:
        # 删掉这行和前面的if行
        new_lines.pop()  # 删掉if getattr...那行
        skip = 3  # 跳过_debug_log那行和后面的参数行
        continue
    new_lines.append(line)

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(new_lines)
print('删黑框方向日志完成')
