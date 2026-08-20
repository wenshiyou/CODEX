with open('test_minimap_route.py', 'r', encoding='utf-8') as f:
    c = f.read()

# 调整底部边框检测
old1 = 'bottom_y = find_hborder(inner, oh - 3, int(oh * 0.5), -1)'
new1 = 'bottom_y = find_hborder(inner, oh - 15, int(oh * 0.5), -1, 140, 0.8)'
c = c.replace(old1, new1)

# 增加底部内缩
old2 = "'height': bottom_y - top_y - pad * 2"
new2 = "'height': bottom_y - top_y - pad * 2 - 10"
c = c.replace(old2, new2)

with open('test_minimap_route.py', 'w', encoding='utf-8') as f:
    f.write(c)

print('adjusted bottom border')
print('old1 found:', old1 in open('test_minimap_route.py', encoding='utf-8').read() if old1 else 'replaced')
