# -*- coding: utf-8 -*-
import io, os
p = 'debug.log'
if not os.path.exists(p):
    print('NO debug.log'); raise SystemExit
lines = io.open(p, encoding='utf-8', errors='ignore').read().splitlines()
kw = ['梯', '跨层', 'transit', 'to_lad', 'lad', '选', '白框', '起跳', '跑跳', '直跳', '对位',
      'climb', '失败', 'realign', 'post_jump', '抓', '屏幕', 'snap', '对齐', 'cross', '上梯', '下梯']
hit = [l for l in lines if any(k in l for k in kw)]
for l in hit[-90:]:
    print(l[:160])
print('--- total lines=%d hit=%d ---' % (len(lines), len(hit)))
