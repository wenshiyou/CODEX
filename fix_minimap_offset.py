with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 修改底部边界：向上移15px
old1 = '                # 底部边界定在模板图片顶部（去掉灰色边框区域）\n                bottom = search_y1 + loc_btm[1]'
new1 = '                # 底部边界定在模板图片顶部再向上移15px（去掉灰色边框区域）\n                bottom = search_y1 + loc_btm[1] - 15'
if old1 in content:
    content = content.replace(old1, new1, 1)
    print('已修改底部边界')
else:
    print('未找到底部边界旧代码')

# 修改TITLE_PAD：从45改成53（向下移8px）
old2 = '        TITLE_PAD = 45'
new2 = '        TITLE_PAD = 53  # 从上边界向下移53px开始截取（原45，向下移8px）'
if old2 in content:
    content = content.replace(old2, new2, 1)
    print('已修改TITLE_PAD')
else:
    print('未找到TITLE_PAD旧代码')

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
