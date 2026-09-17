import io
with io.open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 删掉重复的行
# 4243行是重复的"对怪物也生效"，删掉
if 'tk.Checkbutton(blk_top, text="对怪物也生效"' in lines[4242] and 'command' not in lines[4242]:
    lines[4242] = ''
    print('removed duplicate checkbutton line 4242')

# 4246行是重复的_rebuild_blocklist()，删掉
if '_rebuild_blocklist()' in lines[4245]:
    lines[4245] = ''
    print('removed duplicate rebuild line 4245')

with io.open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('done')
