lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找"锁怪清仓"的代码块，删掉
new_lines = []
skip = 0
for i, line in enumerate(lines):
    if skip > 0:
        skip -= 1
        continue
    if '# 【根因修复】锁定怪不在当前怪列表里' in line:
        # 跳过整个代码块（从注释到_debug_log那行）
        skip = 20  # 大概20行
        continue
    new_lines.append(line)

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(new_lines)
print('删除锁怪清仓代码完成')
