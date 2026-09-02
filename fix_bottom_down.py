with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '                bottom = search_y1 + loc_btm[1] - 15'
new = '                bottom = search_y1 + loc_btm[1]  # 底部边界定在模板顶部（向下移15，从-15改回0）'

if old in content:
    content = content.replace(old, new, 1)
    print('已修改底部边界：向下移15')
else:
    print('未找到旧代码')

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
