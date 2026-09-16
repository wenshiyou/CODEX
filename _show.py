# -*- coding: utf-8 -*-
import io, sys
ls = io.open('maple_route_ui.py', encoding='utf-8').read().splitlines()
key = sys.argv[1]
if len(sys.argv) > 2 and sys.argv[2] == 'list':
    for i, l in enumerate(ls):
        if key in l:
            print(i+1, l.rstrip()[:110])
else:
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 48
    for i, l in enumerate(ls):
        if key in l:
            for k in range(i, min(i+n, len(ls))):
                print(k+1, ls[k])
            break
