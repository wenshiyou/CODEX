# -*- coding: utf-8 -*-
# 临时诊断:对比"录制保存的绝对像素坐标范围"与"当前小地图裁剪框宽高",验证保存后错位是否因裁剪框基准变化
import json, glob, os
_d = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.chdir(_d)
try:
    r = json.load(open('minimap_region.json', encoding='utf-8'))
    print('REGION minimap =', r.get('minimap'))
    print('REGION map     =', r.get('map'))
    mw = (r.get('map') or {}).get('width'); mh = (r.get('map') or {}).get('height')
    print('当前 map 块宽高 = %s x %s' % (mw, mh))
except Exception as e:
    print('region 读取失败:', e); mw = mh = None
print('-' * 60)
for f in sorted(glob.glob('route_*_platforms.json')):
    d = json.load(open(f, encoding='utf-8'))
    pts = [p for pf in d.get('platforms', []) for p in pf.get('points', [])]
    if pts:
        x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
        y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
        flag = ''
        if mw and (x1 > mw + 2 or y1 > mh + 2):
            flag = '  <<< 点超出当前块! 录制时块更大/基准不同'
        print('%s 平台点n=%d X[%.1f~%.1f] Y[%.1f~%.1f]%s' % (f, len(pts), x0, x1, y0, y1, flag))
    else:
        print(f, '空')
print('-' * 60)
for f in sorted(glob.glob('route_*_ladders.json')):
    d = json.load(open(f, encoding='utf-8'))
    ls = d.get('ladders', [])
    print(f, ['(x%.1f y%.1f~%.1f)' % (l['x'], l['y_top'], l['y_bottom']) for l in ls])
