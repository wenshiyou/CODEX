# -*- coding: utf-8 -*-
import io, re, os, time
p = 'debug.log'
lines = io.open(p, encoding='utf-8', errors='ignore').read().splitlines()
recent = []
for l in lines:
    m = re.match(r'\[(\d\d):(\d\d):(\d\d)\]', l)
    if m:
        sec = int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3))
        if sec >= 12*3600+30*60+53:
            recent.append(l)
kw = ['cross', '跨层', '选梯', '白框', '锁定', '目标', '攻击', 'cast', 'pursue',
      '移动', 'reset', '复位', 'climb', '爬梯', '上梯', '下梯', '精准', 'precise',
      '解绑', '回主线', '放弃', '运行', '暂停', '非游戏', '到顶', '抓住', '瞬移', '梯']
hit = [l for l in recent if any(k in l for k in kw)]
print('状态轨迹共%d条, 打印最后120条:' % len(hit))
for l in hit[-120:]:
    print(l[:220])
