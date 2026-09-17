lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

for i in range(len(lines)):
    if '_mc = min(_pick_list, key=lambda c: c[0])' in lines[i]:
        print('找到选梯行:', i+1)
        lines[i] = "                                    # 用户2026-09-16定稿:先按总距离最短,总距离一样再按人离梯Y差最小(第二筛选用Y差不是X差)\n"
        lines.insert(i+1, "                                    _mc = min(_pick_list, key=lambda c: (c[0], abs(c[4] - _psy)))\n")
        break

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('修改完成')
