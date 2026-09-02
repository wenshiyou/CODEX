with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_map = '''        new_map = {
            "left": left,
            "top": top + TITLE_PAD,
            "width": right - left,
            "height": bottom - top - TITLE_PAD
        }'''

new_map = '''        new_map = {
            "left": left + 1,
            "top": top + TITLE_PAD + 1,
            "width": right - left - 2,
            "height": bottom - top - TITLE_PAD - 2
        }'''

content = content.replace(old_map, new_map)

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
