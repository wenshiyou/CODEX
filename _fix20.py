lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找方案三往_smooth_window写数据的代码，删掉
new_lines = []
skip = 0
for i, line in enumerate(lines):
    if skip > 0:
        skip -= 1
        continue
    if '# 屏幕Y一秒最低值平滑：压入缓冲，清掉超过1秒的旧值' in line:
        print('找到方案三写入代码，行:', i+1)
        # 跳过这行和后面5行（if + 3行代码）
        skip = 5
        continue
    new_lines.append(line)

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(new_lines)
print('删除完成，共删除6行')
