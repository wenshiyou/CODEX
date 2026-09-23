# -*- coding: utf-8 -*-
import io
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
b = io.open(p, 'rb').read()
bom = b[:3] == b'\xef\xbb\xbf'
s = b.decode('utf-8-sig').replace('\r\n', '\n')

EDITS = []

# 1) 滑块上限 150->500
EDITS.append((
    '滑块上限150->500',
    'tk.Scale(f, from_=0, to=150, orient="horizontal", variable=v, length=110, showvalue=False,',
    'tk.Scale(f, from_=0, to=500, orient="horizontal", variable=v, length=110, showvalue=False,'
))

# 2) 黑框X半径默认值 40->500
EDITS.append((
    '黑框X半径默认40->500',
    '"lock_box_rx": 40,     # 黑框X半径',
    '"lock_box_rx": 500,    # 黑框X半径(用户2026-09-23:放大到500)'
))

# 3) 黑框Y半径默认值 40->500
EDITS.append((
    '黑框Y半径默认40->500',
    '"lock_box_ry": 40,     # 黑框Y半径',
    '"lock_box_ry": 500,    # 黑框Y半径(用户2026-09-23:放大到500)'
))

# 4) 核心:局部1秒找不到->全图不停扫(用短锚点)
old4 = '        need_full = (last is None) or (now - tr["last_full"] > research) \\\n            or ((tr["miss"] >= faststep) and (now - tr["last_full"] > _FULL_GAP_MS))'
new4 = (
    '        # 用户2026-09-23:局部连续找不到1秒->进全图不停扫模式(人物发呆不动,全图扫不抢CPU,扫到为止)\n'
    '        if tr["miss"] >= faststep:\n'
    '            if not tr.get("_full_persistent"):\n'
    '                if tr.get("_miss_t", 0) == 0:\n'
    '                    tr["_miss_t"] = now\n'
    '                elif now - tr["_miss_t"] > 1000:\n'
    '                    tr["_full_persistent"] = True\n'
    '                    _debug_log("[角色跟踪] 局部1秒找不到->全图不停扫到为止")\n'
    '        else:\n'
    '            tr["_miss_t"] = 0\n'
    '            tr["_full_persistent"] = False\n'
    '        need_full = (last is None) or (now - tr["last_full"] > research) \\\n'
    '            or tr.get("_full_persistent", False) \\\n'
    '            or ((tr["miss"] >= faststep) and (now - tr["last_full"] > _FULL_GAP_MS))'
)
EDITS.append(('局部1秒找不到->全图不停扫', old4, new4))

# 5) 找到后重置全图不停扫标志
old5 = '            tr["miss"] = 0; tr["score"] = ps; tr["last_t"] = now\n            if need_full:\n                tr["last_full"] = now'
new5 = '            tr["miss"] = 0; tr["score"] = ps; tr["last_t"] = now\n            tr["_miss_t"] = 0; tr["_full_persistent"] = False\n            if need_full:\n                tr["last_full"] = now'
EDITS.append(('找到后重置全图不停扫', old5, new5))

for desc, old, new in EDITS:
    c = s.count(old)
    if c != 1:
        print('FAIL [%s] count=%d' % (desc, c))
        raise SystemExit(1)
    s = s.replace(old, new)

o = s.replace('\n', '\r\n')
io.open(p, 'wb').write((b'\xef\xbb\xbf' if bom else b'') + o.encode('utf-8'))
print('OK: %d处全部替换' % len(EDITS))
for desc, _, _ in EDITS:
    print('  -', desc)
