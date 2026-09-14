# -*- coding: utf-8 -*-
import sys, io
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
ls = io.open(p, encoding='utf-8', errors='ignore').read().splitlines()
def show(tag, n, kws):
    d=[l for l in ls if any(k in l for k in kws)]
    print('=== %s 最近%d(共%d) ==='%(tag,n,len(d))); print('\n'.join(d[-n:]) if d else '(无)'); print()
show('帧率/耗时', 15, ['FPS','fps','帧率','绘制','识别A','识别B','耗时','周期','分段'])
show('[角色跟踪]', 6, ['[角色跟踪]'])
show('[光点]', 6, ['[光点]'])
show('[怪分类]', 3, ['[怪分类]'])
show('Traceback', 3, ['Traceback'])
