# -*- coding: utf-8 -*-
import io
L = io.open('maple_route_ui.py', encoding='utf-8', newline='').read().splitlines()
for i, l in enumerate(L):
    if '_ladder_realign_step' in l:
        kind = 'METHOD' if (l.strip().startswith('def ') or '_ladder_realign_step(' in l) else 'FIELD'
        print('%s @%d %s' % (kind, i + 1, l.strip()[:120]))
