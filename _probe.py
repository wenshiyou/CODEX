# -*- coding: utf-8 -*-
import io
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
raw = io.open(p, 'rb').read()
if raw.startswith(b'\xef\xbb\xbf'):
    raw = raw[3:]
t = raw.decode('utf-8')
i = t.find('def _move_watchdog_loop')
print('IDX', i)
print(repr(t[i-260:i+40]))
