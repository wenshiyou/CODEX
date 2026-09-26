# -*- coding: utf-8 -*-
# 二轮：坐标连续性/识别源/出手/丢点分支 统计（最近N秒运行态）
import io, re, sys, datetime, collections

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
WIN_S = int(sys.argv[1]) if len(sys.argv) > 1 else 180
now = datetime.datetime.now()

def parse_t(line):
    m = re.search(r'(\d{2}):(\d{2}):(\d{2})', line)
    if not m: return None
    t = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=int(m.group(3)), microsecond=0)
    if (now - t).total_seconds() > 12 * 3600: t += datetime.timedelta(days=1)
    return t

rows = []
for ln in io.open(P, encoding="utf-8", errors="replace"):
    t = parse_t(ln)
    if t is not None and 0 <= (now - t).total_seconds() <= WIN_S:
        rows.append((t, ln.rstrip()))

diag = [(t, ln) for t, ln in rows if '[战斗诊断]' in ln and '运行=True' in ln]
pts = []
none_frames = 0
for t, ln in diag:
    m = re.search(r'人物=(?:\((\d+),\s*(\d+)\)|None|=None)', ln)
    m2 = re.search(r'人物=\((\d+),\s*(\d+)\)', ln)
    if m2: pts.append((t, int(m2.group(1)), int(m2.group(2))))
    elif ('人物=None' in ln or '人物= -' in ln): none_frames += 1

# 坐标连续性
gaps = []
for i in range(1, len(pts)):
    _, x0, y0 = pts[i-1]; _, x1, y1 = pts[i]
    gaps.append(abs(x1-x0) + abs(y1-y0))
big = [g for g in gaps if g > 50]
zeroish = [i for i in range(1, len(pts)) if gaps[i-1] == 0]

# 识别源分布
src_cnt = collections.Counter()
for t, ln in rows:
    for k in ['name', 'face_r', 'back', 'pet1', 'pet2', 'pet3', 'hold', 'none']:
        if re.search(r'源\s*=\s*%s\b' % k, ln) or ("src=%s" % k) in ln or ("_role_pos_src=%s" % k) in ln:
            src_cnt[k] += 1

kw = collections.Counter()
samples = collections.defaultdict(list)
for t, ln in rows:
    for key, words in [('钉点', ['攻击中基点丢失', '钉点']),
                       ('重认', ['黑框重认', '基点丢失']),
                       ('转全图', ['转全图', '全图只找人名', '全屏找']),
                       ('主攻释放', ['[主攻]']),
                       ('群攻释放', ['[群攻]']),
                       ('Traceback', ['Traceback']),
                       ('平台边界(无关本次)', ['[平台边界]'])]:
        if any(w in ln for w in words):
            kw[key] += 1
            if len(samples[key]) < 4: samples[key].append("%s %s" % (t.strftime('%H:%M:%S'), ln[:120]))

print("窗口最近%ds 运行态诊断帧=%d 带坐标帧=%d 坐标None帧=%d" % (WIN_S, len(diag), len(pts), none_frames))
if gaps:
    print("坐标相邻帧跳变: 最大=%d  >50px帧数=%d  完全不动帧=%d  采样=%d" % (max(gaps), len(big), len(zeroish), len(gaps)))
    # 是否长时间钉死(连续0超过N帧)
    run0 = mx = 0
    for g in gaps:
        run0 = run0 + 1 if g == 0 else 0
        mx = max(mx, run0)
    print("坐标连续不变最长连续帧=%d" % mx)
print("识别源分布(日志可见):", dict(src_cnt))
print("关键计数:", dict(kw))
for k, v in samples.items():
    if k in ('钉点', '重认', '转全图', 'Traceback') and v:
        print("\n[%s 样例]" % k)
        for s in v: print(s)
