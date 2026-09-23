# -*- coding: utf-8 -*-
import io
lines = io.open('debug.log','rb').read().decode('utf-8','ignore').splitlines()
kw = ['爬梯','选梯','跨层','走向梯子','直跳','跑跳','抓住','失败','路线','梯']
hit = [l for l in lines if ('12:33:' in l or '12:34:' in l) and any(k in l for k in kw)]
io.open('_lad.txt','w',encoding='utf-8').write('\n'.join(hit[-120:]))
print('lines=',len(hit))
