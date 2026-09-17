lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找17722行附近，删掉没注释干净的那行
for i in range(len(lines)):
    if i >= 17719 and i <= 17723:
        print(i+1, repr(lines[i]))

# 删除多余的那行（self._clear_locked_ladder前面缩进不对的）
new_lines = []
for i, line in enumerate(lines):
    # 找到注释掉的if后面那行没注释的_clear_locked_ladder
    if i > 0 and "#     self._clear_locked_ladder('改打技能范围内近身怪')" in lines[i-1]:
        if "self._clear_locked_ladder('改打技能范围内近身怪')" in line and not line.strip().startswith('#'):
            print('删除多余行:', i+1, repr(line))
            continue
    new_lines.append(line)

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(new_lines)
print('修复完成')
