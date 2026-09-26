# -*- coding: utf-8 -*-
# 分析 debug.log 最近 N 秒运行态：基点钉点/重认、坐标连续性、攻击出手、异常
import io, re, sys, time, datetime, collections

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
WIN_S = int(sys.argv[1]) if len(sys.argv) > 1 else 180
now = datetime.datetime.now()

def parse_t(line):
    m = re.search(r'(\d{2}):(\d{2}):(\d{2})', line)
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
    t = now.replace(hour=h, minute=mi, second=s, microsecond=0)
    if (now - t).total_seconds() > 12 * 3600:  # 跨天
        t += datetime.timedelta(days=1)
    return t

lines = io.open(P, encoding="utf-8", errors="replace").read().splitlines()
recent = []
for ln in lines:
    t = parse_t(ln)
    if t is not None and 0 <= (now - t).total_seconds() <= WIN_S:
        recent.append((t, ln))
    elif t is None and recent:
        recent.append((recent[-1][0], ln))  # traceback 续行

print("窗口: 最近%d秒, 命中行 %d, now=%s" % (WIN_S, len(recent), now.strftime('%H:%M:%S')))

KEEP = ['运行', 'F10', 'F12', '基点', '人物坐标', '黑框', '全图', '人名', '主攻', '群攻',
        '锁怪', '发呆', '异常', 'Traceback', 'Error', '错误', '跨层', '钉点', '重认',
        '横带', '前台', 'MP底', '转全图', '重捕', '恢复', '锁梯', '上梯', '空打']
NOISE = ['HP', 'MP=', '绘制', 'fps', 'FPS']

buckets = collections.defaultdict(list)
cnt = collections.Counter()
run_state = []
mp_block = 0
for t, ln in recent:
    if ('运行' in ln) or ('F10' in ln) or ('F12' in ln):
        run_state.append("%s %s" % (t.strftime('%H:%M:%S'), ln.strip()[:120]))
    if '横带' in ln or 'MP底' in ln or ('MP' in ln and ('0.' in ln) and ('挡' in ln or '前台' in ln)):
        mp_block += 1
    if '攻击中基点丢失' in ln:
        buckets['hold攻击钉点'].append("%s %s" % (t.strftime('%H:%M:%S'), ln.strip()[:140])); cnt['hold'] += 1
    elif '黑框重认中' in ln or ('基点丢失' in ln):
        buckets['relock重认'].append("%s %s" % (t.strftime('%H:%M:%S'), ln.strip()[:140])); cnt['relock'] += 1
    elif '转全图' in ln or ('全图' in ln and '找' in ln):
        buckets['转全图'].append("%s %s" % (t.strftime('%H:%M:%S'), ln.strip()[:140])); cnt['full'] += 1
    elif '人物坐标' in ln:
        cnt['char_pos'] += 1; buckets['char_pos'].append("%s %s" % (t.strftime('%H:%M:%S'), ln.strip()[:80]))
    elif ('主攻' in ln and '释放' in ln):
        cnt['atk1'] += 1
    elif ('群攻' in ln and '释放' in ln):
        cnt['aoe'] += 1
    elif 'Traceback' in ln or 'Error' in ln or '错误' in ln or '异常' in ln:
        buckets['error'].append("%s %s" % (t.strftime('%H:%M:%S'), ln.strip()[:160])); cnt['error'] += 1

print("\n== 计数 ==", dict(cnt), " MP挡窗相关行=", mp_block)
print("\n== 运行状态切换 ==")
for x in run_state[-12:]:
        print(x)
for k in ['hold攻击钉点', 'relock重认', '转全图', 'error']:
    v = buckets[k]
    print("\n== %s (%d) ==" % (k, len(v)))
    for x in v[-12:]:
        print(x)
print("\n== 人物坐标 首6/末6 ==")
cp = buckets['char_pos']
for x in cp[:6] + (['...'] if len(cp) > 12 else []) + cp[-6:]:
    print(x)
