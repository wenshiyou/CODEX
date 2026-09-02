with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 修改底部边界：向下移15px（从-15改成0）
old1 = '                bottom = search_y1 + loc_btm[1] - 15'
new1 = '                bottom = search_y1 + loc_btm[1]  # 底部边界定在模板顶部（向下移15px回原位）'
if old1 in content:
    content = content.replace(old1, new1, 1)
    print('已修改底部边界')
else:
    print('未找到底部边界旧代码')

# 修改右边界：向左移5px
old2 = '        right = big_x + bw'
new2 = '        right = big_x + bw - 5  # 右边界向左移5px'
if old2 in content:
    content = content.replace(old2, new2, 1)
    print('已修改右边界')
else:
    print('未找到右边界旧代码')

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
