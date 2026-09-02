p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

old = '''        # 轻量模式：区域变化小于3px则不更新（防抖），不写文件不写图
        if not debug:
            old = self.map_area_rect
            if (abs(old["left"] - new_map["left"]) <= 3 and
                abs(old["top"] - new_map["top"]) <= 3 and
                abs(old["width"] - new_map["width"]) <= 3 and
                abs(old["height"] - new_map["height"]) <= 3):
                return'''

new = '''        # 轻量模式：区域变化小于3px则不更新（防抖），不写文件不写图
        if not debug:
            old = self.map_area_rect
            if old is not None and (abs(old["left"] - new_map["left"]) <= 3 and
                abs(old["top"] - new_map["top"]) <= 3 and
                abs(old["width"] - new_map["width"]) <= 3 and
                abs(old["height"] - new_map["height"]) <= 3):
                return'''

assert old in code, 'pattern not found'
code = code.replace(old, new)
with open(p, 'w', encoding='utf-8') as f:
    f.write(code)
print('Fixed: map_area_rect None check added')
