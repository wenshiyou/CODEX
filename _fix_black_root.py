p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

# 修复1: __init__开头加回 map_area_rect = None
old_init_start = '''class MinimapRouteRecorder:
    def __init__(self):
        self.sct = mss.mss()'''
new_init_start = '''class MinimapRouteRecorder:
    def __init__(self):
        self.map_area_rect = None  # 初始化在自动绑定之前，防止_detect_minimap访问时AttributeError
        self.sct = mss.mss()'''
assert old_init_start in code, 'init start not found'
code = code.replace(old_init_start, new_init_start)
print('Fix1: map_area_rect init at __init__ start')

# 修复2: 删除后面的 map_area_rect = None 重置（会覆盖_detect_minimap结果导致黑屏）
old_later = '''        # 初始化小地图区域为None, 防止下方"if self.map_area_rect"在未赋值时AttributeError崩溃
        self.map_area_rect = None

        if self.map_area_rect:'''
new_later = '''        # map_area_rect已在__init__开头初始化，自动绑定可能已设置值，这里不再重置

        if self.map_area_rect:'''
assert old_later in code, 'later reset not found'
code = code.replace(old_later, new_later)
print('Fix2: remove later map_area_rect reset')

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)
print('Black screen root cause fixed')
