# -*- coding: utf-8 -*-
# 探针2: 只在"游戏在前端(MP正常)+脚本在运行"时段, 找光点连续静止>=2s的真呆住窗口, 打印卡在哪
import re, io
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log'
ts_re = re.compile(r'^\[(\d\d):(\d\d):(\d\d)\]')
mov_re = re.compile(r'光点位移=\((-?\d+),(-?\d+)\)')
dec_re = re.compile(r'\[打怪决策\]\s*状态=(\w+)')

sec = {}
order = []
with io.open(p, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = ts_re.match(line)
        if not m:
            continue
        t = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3))
        # 只看 08:41 - 09:14
        if not (8*3600+41*60 <= t <= 9*3600+14*60):
            continue
        d = sec.get(t)
        if d is None:
            d = {'mp_bad': 0, 'mov': 0, 'mov_samples': 0, 'dec': [], 'keep': []}
            sec[t] = d; order.append(t)
        if '判定非游戏画面' in line or '匹配度0.000' in line:
            d['mp_bad'] += 1
        mm = mov_re.search(line)
        if mm:
            d['mov_samples'] += 1
            if abs(int(mm.group(1))) + abs(int(mm.group(2))) > 0:
                d['mov'] += 1
        dm = dec_re.search(line)
        if dm:
            d['dec'].append(dm.group(1))
        # 保留有信息量的行
        if any(k in line for k in ('[打怪决策]', '[选梯·小地图]', '爬梯', '后脑', '抓住梯', '到顶',
                                   '锁后Y不合格', '找不到够得着', '放弃回主线', '回主线', '解卡', '卡住',
                                   'cross', '上梯', '下跳', '人物=None', '锁定小地图梯', '没锁', '无锁',
                                   '不出包', '清锁', '巡游', '同层无怪', '运行', '停止', '空打', '异常',
                                   '没上去', '失败', '总超时', '横跳', '锁梯')):
            d['keep'].append(line.rstrip('\n'))

# 连续静止窗: mp正常(mp_bad==0) 且 有光点采样且全静止(mov==0,mov_samples>0)
def still(t):
    d = sec.get(t)
    return bool(d and d['mp_bad'] == 0 and d['mov_samples'] > 0 and d['mov'] == 0)

windows = []
cur = []
for t in range(min(order), max(order)+1):
    if still(t):
        cur.append(t)
    else:
        if len(cur) >= 2:
            windows.append(cur)
        cur = []
if len(cur) >= 2:
    windows.append(cur)

print('游戏在前端时的真静止窗口(>=2s)个数:', len(windows))
for w in windows:
    a, b = w[0], w[-1]
    decs = [s for t in w for s in sec[t]['dec']]
    print('\n' + '='*90)
    print('静止 %02d:%02d:%02d-%02d:%02d:%02d 持续%ds 决策序列=%s' % (
        a//3600,a%3600//60,a%60, b//3600,b%3600//60,b%60, b-a+1,
        (','.join(decs) if decs else '无任何打怪决策')))
    # 窗口前2秒也打印(看是怎么进来的)
    for t in range(max(min(order), a-2), min(max(order), b+1)+1):
        d = sec.get(t)
        if not d:
            continue
        tag = '静止' if still(t) else ('挡窗' if d['mp_bad'] else '在动')
        for line in d['keep']:
            print('  [%s] %s' % (tag, line))
