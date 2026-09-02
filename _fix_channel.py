p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

old = '''            img = load_png(p)
            if img is not None:
                self._ui_bgs[tab] = cv2.resize(img, (UI_W, UI_H))'''
new = '''            img = load_png(p)
            if img is not None:
                if img.ndim == 3 and img.shape[2] == 4:
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                self._ui_bgs[tab] = cv2.resize(img, (UI_W, UI_H))'''
assert old in code, 'pattern not found'
code = code.replace(old, new)
print('Fix: UI bg 4-channel to 3-channel')

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)
print('Done')
