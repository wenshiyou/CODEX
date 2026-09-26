# -*- coding: utf-8 -*-
import io, re
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
d = io.open(p, 'r', encoding='utf-8', errors='ignore').read()
lines = d.splitlines()
print('TOTAL_LINES', len(lines))
print('=== LAST 8 RAW ===')
for x in lines[-8:]:
    print(x[:170])

def lastn(key, n=12, store=None):
    out = []
    for x in lines[-4000:]:
        if key in x:
            out.append(x)
    if store is not None:
        store.extend(out)
    return out[-n:]

print('=== [人物耗时] last 10 ===')
for x in lastn('人物耗时', 10):
    print(x[:150])
print('=== [截图耗时] last 10 ===')
for x in lastn('截图耗时', 10):
    print(x[:170])
print('=== [FPS统计] last 8 ===')
for x in lastn('FPS统计', 8):
    print(x[:170])
print('=== [忙帧监管] count(last4000) / last5 ===')
fb = [x for x in lines[-4000:] if '忙帧监管' in x]
print('count=', len(fb))
for x in fb[-5:]:
    print(x[:160])
print('=== [角色跟踪] last 8 ===')
for x in lastn('角色跟踪', 8):
    print(x[:200])
print('=== 转全图/跳变拦截 count(last4000) ===')
print('转全图=', sum('转全图' in x for x in lines[-4000:]),
      ' 跳变拦截=', sum('跳变拦截' in x for x in lines[-4000:]),
      " src=hold=", sum("src='hold'" in x or '源=hold' in x or '模式=' in x for x in lines[-4000:]))
print('=== [MP界面] last 3 ===')
for x in lastn('MP界面', 3):
    print(x[:140])
print('=== [战斗诊断] last 3 ===')
for x in lastn('战斗诊断', 3):
    print(x[:200])
