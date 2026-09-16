# -*- coding: utf-8 -*-
import io, os, time
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug.log')
lines = io.open(p, encoding='utf-8', errors='ignore').read().splitlines()
mt = time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(p)))
print('mtime=%s total=%d  物理最后30行:' % (mt, len(lines)))
for ln in lines[-30:]:
    print(ln)
