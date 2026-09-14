# -*- coding: utf-8 -*-
import io
lines = io.open('debug.log', encoding='gbk', errors='ignore').read().splitlines()
def cnt(k):
    xs = [l for l in lines if k in l]
    return len(xs), (xs[-1][:24] if xs else '-')
for k in ['读回保存裁剪框', '自动绑定成功', '窗口已绑定', '显著变化', '光点连续丢失', '前台窗口已绑定']:
    n, t = cnt(k)
    print('%-12s n=%-3d last=%s' % (k, n, t))
print('--- 最后10行 ---')
for l in lines[-10:]:
    print(l[:95])
