lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找刚才加的发呆诊断日志，删掉
new_lines = []
i = 0
while i < len(lines):
    if '# 【发呆诊断·用户2026-09-16】打印发呆时为什么has_target为False' in lines[i]:
        # 跳过这三行
        i += 3
        continue
    new_lines.append(lines[i])
    i += 1

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(new_lines)
print('回滚完成')
