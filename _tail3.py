# -*- coding: utf-8 -*-
# 最近3分钟运行态关键日志(去HP/MP/绘制/FPS刷屏),重点:瞬移/攻击/巡游/锁怪/空怪/模式/回退
import re, io, datetime, sys
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
now = datetime.datetime.now()
t_re = re.compile(r'(\d{1,2}):(\d{2}):(\d{2})')
SPAM = ['绘制', 'FPS', 'fps', '帧率', 'HP=', 'MP=', 'HP:', 'MP:']
KW = {
 '瞬移': ['瞬移', 'teleport', 'Teleport', 'TELEPORT'],
 '攻击': ['主攻', '群攻', 'cast', 'Cast', '攻击键', '出手', '普攻', '群技'],
 '巡游': ['巡游', 'roam', 'Roam', '向另', '另一边', '没怪', '无怪移动'],
 '锁怪': ['锁定', '锁怪', 'b_lock', '决策', 'pursue', '追怪'],
 '空怪判活': ['空怪', '无怪', '没有怪', '血条', '伤害', '判活', '换怪', '丢失'],
 '运行开关': ['F10', 'F12', '开始运行', '停止', '运行=True', '运行=False', '启动', 'runtime'],
 '模式': ['随机', '手动', 'route_mode', '台子', '平台'],
 '回退边界': ['越线', '回退', '平台边界', '关锁', '重锁', '锁怪开关'],
 '梯cross': ['上梯', '下跳', '爬梯', 'cross', '横跳', '后脑'],
}
def ltime(line):
    m = t_re.search(line)
    if not m: return None
    h, mi, s = map(int, m.groups())
    t = now.replace(hour=h, minute=mi, second=s, microsecond=0)
    return t
lines = io.open(P, encoding='utf-8', errors='replace').read().splitlines()
recent = []
for ln in lines:
    t = ltime(ln)
    if t is None:
        continue
    d = (now - t).total_seconds()
    if -5 <= d <= 180:
        recent.append((t, ln))
# 去刷屏
def is_spam(ln):
    return any(k in ln for k in SPAM)
clean = [(t, ln) for t, ln in recent if not is_spam(ln)]
out = []
out.append("NOW=%s  最近3分钟行=%d 去刷屏后=%d" % (now.strftime('%H:%M:%S'), len(recent), len(clean)))
# 计数
cnt = {k: 0 for k in KW}
for t, ln in clean:
    for k, kws in KW.items():
        if any(w in ln for w in kws):
            cnt[k] += 1
out.append("计数: " + " ".join("%s=%d" % (k, v) for k, v in cnt.items()))
# MP标志/运行态窗口
mp_bad = [ln for t, ln in clean if ('MP' in ln and ('匹配' in ln or '标志' in ln or '遮挡' in ln or '挡' in ln))]
out.append("MP标志相关行(末3): " + (" | ".join(mp_bad[-3:]) if mp_bad else "无"))
run_toggle = [ln for t, ln in clean if any(w in ln for w in KW['运行开关'])]
out.append("--- 运行开关(末8) ---")
out.extend(run_toggle[-8:])
for k in ['瞬移', '攻击', '巡游', '锁怪', '空怪判活', '回退边界', '梯cross', '模式']:
    seg = [ln for t, ln in clean if any(w in ln for w in KW[k])]
    out.append("--- %s(末12) ---" % k)
    out.extend(seg[-12:])
out.append("=== 去刷屏后原始序列(末120行) ===")
out.extend(ln for t, ln in clean[-120:])
io.open(r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\_tail3.txt", "w", encoding="utf-8").write("\n".join(out))
print("lines_recent=%d clean=%d -> _tail3.txt" % (len(recent), len(clean)))
