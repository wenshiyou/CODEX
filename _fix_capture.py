p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

old = '''        r = self.map_area_rect
        reg = {
            "left": self.window_rect["left"] + r["left"],'''
new = '''        r = self.map_area_rect
        if not r or r.get("width", 0) <= 0 or r.get("height", 0) <= 0:
            return np.zeros((MAP_H, FIXED_W, 3), dtype=np.uint8)
        reg = {
            "left": self.window_rect["left"] + r["left"],'''
assert old in code, 'pattern not found'
code = code.replace(old, new)
print('Fix: _capture_map None check added')

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)
print('Done')
