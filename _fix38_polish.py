# -*- coding: utf-8 -*-
"""_fix38 第二批-A 打磨：清两处过时注释、删帧首三个 if 块内多余空行。带断言、保留 BOM/CRLF。"""
import ast
import io

PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, 'r', encoding='utf-8-sig', newline='') as f:
    raw = f.read()
nl = '\r\n' if '\r\n' in raw else '\n'
lines = raw.split(nl)


def find1(sub, mode='in'):
    if mode == 'in':
        hits = [i for i, c in enumerate(lines) if sub in c]
    else:
        hits = [i for i, c in enumerate(lines) if c.lstrip().startswith(sub)]
    assert len(hits) == 1, (sub, hits)
    return hits[0]


repl, dele = {}, set()

# 注释1：横跳"置拉回令交主线consume"→只记录不干预
i = find1('独立先判,置拉回令交主线consume')
ind = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
repl[i] = ind + '# 原地左右横跳探测不依赖当前intent(换向间隙intent可能已clear),独立先判,只记录报异常栏、不置令不干预'

# 注释2：combat_tick 内两行过时注释合一（删第二行、改第一行）
i = find1('硬重置只认左右互搏冲突')
assert '_consume_hard_reset' in lines[i + 1], lines[i + 1]
ind = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
repl[i] = ind + '# 单向走不动(地形挡)不在此处理,靠录制绿线6px跑跳+卡住跳脱困;监管线(按键互搏/停滞/横跳)只检测记录报异常栏,不发键不重置(干预已于2026-09-17物理删除)。'
dele.add(i + 1)

# 帧首三个 if not _aux_busy: 块内多余空行
for sub in ['self._random_step(self._player_map_pos)', 'self._combat_tick()',
            'self._stall_observer(time.time() * 1000)']:
    i = find1(sub, mode='startswith')
    assert lines[i - 1].strip() == '', (sub, lines[i - 1])
    assert lines[i - 2].strip() == 'if not _aux_busy:', (sub, lines[i - 2])
    dele.add(i - 1)

assert not (set(repl) & dele)
out = [repl[k] if k in repl else c for k, c in enumerate(lines) if k not in dele]
text = nl.join(out)

for gone in ['置拉回令交主线consume', '_consume_hard_reset 跨线程清零', '硬重置只认左右互搏']:
    assert gone not in text, gone
# 三处锚点上一行必须就是 if 行
ol = text.split(nl)
for sub in ['self._random_step(self._player_map_pos)', 'self._combat_tick()',
            'self._stall_observer(time.time() * 1000)']:
    j = next(k for k, c in enumerate(ol) if c.lstrip().startswith(sub))
    assert ol[j - 1].strip() == 'if not _aux_busy:', (sub, ol[j - 1])
ast.parse(text)

with io.open(PATH, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(text)
print("POLISH_OK 行数 %d -> %d" % (len(lines), len(ol)))
