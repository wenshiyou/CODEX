# -*- coding: utf-8 -*-
"""
_fix37 第二批-A：物理删除"硬重置/横跳拉回/全局兜底"干预补丁（运行时已空转）。
- 删 8 个干预函数连续段（AST 定位，删除前断言它们在类内是连续 FunctionDef 子序列）
- 摘 4 处调用/死分支（_combat_tick 全局兜底、主线帧首两个 consume、_wd_check_once 即时松键、选怪 A级锁侧、怪物线程 reset_seq 自清）
- 删专用常量与 init 孤儿字段；保留全部检测/日志、边界守护、解卡/掉台归位(关闭态)、_combat_suppress_side
读 maple_route_ui.py：UTF-8 带 BOM、CRLF；写回同编码同换行。写盘前多重断言，失败不写盘。
"""
import ast
import io
import sys

PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"

with io.open(PATH, 'r', encoding='utf-8-sig', newline='') as f:
    raw = f.read()
nl = '\r\n' if '\r\n' in raw else '\n'
lines = raw.split(nl)
# 注意 split(sep) 不保留行尾；后续 join(nl)。末尾若文件以换行结束，最后元素为 ''，join 还原。
orig_n = len(lines)


def lidx(sub, needle=1, start=0):
    """返回第 needle 个(默认第1个)包含 sub 的行索引(0-based)；needle=0 表示要求唯一。"""
    hits = [i for i in range(start, len(lines)) if sub in lines[i]]
    if needle == 0:
        assert len(hits) == 1, "锚点%r 应唯一, 实际命中 %d 行: %s" % (sub, len(hits), hits)
        return hits[0]
    assert len(hits) >= needle, "锚点%r 命中不足 %d: %s" % (sub, needle, hits)
    return hits[needle - 1]


def line_is_comment(i):
    return lines[i].lstrip().startswith('#')


spans = []  # (a, b 闭区间0-based, 描述)
repls = []  # (i, newtext, 描述) 整行替换

# ---------- O1 怪物线程：硬重置版本号自清分支 ----------
i = lidx("if self._detect_reset_seq != _seen_reset_seq:", 0)
assert '硬重置版本号自清' in lines[i - 1], lines[i - 1]
j = lidx('硬重置seq=', 0, i)
assert j > i
spans.append((i - 1, j, "O1a 怪物线程 reset_seq 自清if块(含上方注释)"))
k = lidx("_seen_reset_seq = 0", 0)
assert lines[k].strip() == '_seen_reset_seq = 0', lines[k]
spans.append((k, k, "O1b _seen_reset_seq 局部初始化"))

# ---------- O2 选怪 A级锁侧死分支 ----------
i = lidx("_ajhs = self._aj_hold_side", 0)
j = lidx("self._aj_hold_side = None", 0, i)
assert j > i and 'elif _ajhs' in lines[j - 1] or 'elif _ajhs' in lines[j]
spans.append((i, j, "O2b 选怪 _ajhs 锁侧过滤块"))
# 上方两行注释（_combat_mons 赋值行保留，注释在它之前）
c2 = lidx("第二层横跳拉回·A级锁侧", 0)
assert line_is_comment(c2) and line_is_comment(c2 + 1), (lines[c2], lines[c2 + 1])
assert '_combat_mons = self._monsters' in lines[c2 + 2], lines[c2 + 2]
spans.append((c2, c2 + 1, "O2a 选怪 A级锁侧注释两行"))

# ---------- O3 _wd_check_once 尾部即时松键 ----------
i = lidx("_req_t0 = self._hard_reset_req", 0)
spans.append((i, i, "O3a _req_t0 行"))
k = lidx("_req = self._hard_reset_req", 0)
assert '锁外即时停手' in lines[k - 2], lines[k - 2]
assert lines[k + 1].lstrip().startswith('if _req and'), lines[k + 1]
assert '_wd_immediate_release' in lines[k + 2], lines[k + 2]
spans.append((k - 2, k + 2, "O3b 锁外即时松键注释+块"))

# ---------- O4 _combat_tick 全局兜底 ----------
i = lidx("if self._global_stall_watchdog(now):", 0)
assert '全局2秒总兜底' in lines[i - 1], lines[i - 1]
assert lines[i + 1].strip() == 'return', lines[i + 1]
spans.append((i - 1, i + 1, "O4 _combat_tick 全局兜底(注释+if+return)"))

# ---------- O5 主线帧首两个 consume ----------
i = lidx("_hard_reset_done = self._consume_hard_reset()", 0)
a = i - 1
while a >= 0 and line_is_comment(a):
    a -= 1
a += 1
assert '监管线硬重置' in ''.join(lines[a:i + 1]), lines[a:i + 1]
spans.append((a, i, "O5a 帧首硬重置 consume 块(含注释)"))
p = lidx("_anti_jitter_done = False", 0)
assert line_is_comment(p - 1) and '第二层横跳拉回' in lines[p - 1], lines[p - 1]
b = lidx("self._consume_anti_jitter(", 0, p)
assert b == p + 2, (p, b, lines[p:b + 1])
spans.append((p - 1, b, "O5b 帧首横跳 consume 块(注释+False+if+调用)"))

# 门控 if 行：把任何含 _done 变量的 `if not _aux_busy ...:` 归一为 `if not _aux_busy:`
for idx in range(len(lines)):
    s = lines[idx]
    st = s.lstrip()
    if st.startswith('if not _aux_busy') and ('_hard_reset_done' in s or '_anti_jitter_done' in s):
        indent = s[:len(s) - len(st)]
        repls.append((idx, indent + 'if not _aux_busy:' + nl, "O5c 门控归一 " + st.strip()))

# ---------- O6 专用常量整行 + 兜底注释 ----------
const_prefixes = [
    'AJ_HOLD_MS =', 'AJ_ESCALATE_MS =', 'ENABLE_GLOBAL_STALL_FALLBACK =',
    'GLOBAL_STALL_MS =', 'GLOBAL_RESET_COOLDOWN_MS =',
]
for pre in const_prefixes:
    hits = [i for i in range(len(lines)) if lines[i].lstrip().startswith(pre)]
    assert len(hits) == 1, "常量 %s 命中 %d" % (pre, len(hits))
    spans.append((hits[0], hits[0], "O6 常量 " + pre))
chits = [i for i in range(len(lines)) if line_is_comment(i) and '全局2秒总兜底看门狗' in lines[i]]
assert len(chits) == 1, chits
spans.append((chits[0], chits[0], "O6 全局兜底注释行"))

# ---------- O7 init 孤儿字段/注释 ----------
# init 字段窗口(0-based)：只在 __init__ 字段区定位；同名清零赋值在待删的 _hard_reset_state/_consume_*
# 或 O2 选怪块里，那些区间会在阶段A区间删除/阶段B函数删除时一并带走，不能在全局按"唯一"断言。
INIT_A, INIT_B = 1380, 1425

def del_field(prefix, desc):
    hits = [i for i in range(INIT_A, INIT_B) if lines[i].lstrip().startswith(prefix)]
    assert len(hits) == 1, "init字段 %s 窗口内命中 %d %s" % (prefix, len(hits), hits)
    spans.append((hits[0], hits[0], "O7 " + desc))

del_field('self._wd_stall_req = None', 'init _wd_stall_req')
del_field('self._hard_reset_req = None', 'init _hard_reset_req')
del_field('self._hard_reset_last_t = ', 'init _hard_reset_last_t')
del_field('self._wd_antijitter_req = None', 'init _wd_antijitter_req')
del_field('self._aj_hold_side = None', 'init _aj_hold_side')
del_field('self._aj_stage = 0', 'init _aj_stage')
del_field('self._aj_last_trigger_t = ', 'init _aj_last_trigger_t')
del_field('self._detect_reset_seq = 0', 'init _detect_reset_seq')
# 硬重置字段上方整段注释
hits = [i for i in range(len(lines)) if line_is_comment(i) and '监管线掌控的跨线程硬重置' in lines[i]]
assert len(hits) == 1, hits
spans.append((hits[0], hits[0], "O7 init 硬重置注释行"))
# 横跳两行注释：第二行(_aj_hold_side 说明)删，第一行改写
hits = [i for i in range(len(lines)) if line_is_comment(i) and '_aj_hold_side=主线A级锁侧态' in lines[i]]
assert len(hits) == 1, hits
spans.append((hits[0], hits[0], "O7 init 横跳注释第二行"))
c1 = lidx('# 横跳探测(第二层监管)', 0)
indent_c1 = lines[c1][:len(lines[c1]) - len(lines[c1].lstrip())]
repls.append((c1, indent_c1 + '# 横跳探测(第二层监管,只记录不干预):_wd_x_flips=主线登记的X换向[(t,小地图X)];_wd_aj_last_req=日志节流' + nl,
              "O7 init 横跳注释第一行改写"))

# ---------- 保留函数 docstring 中对已删函数的引用改写 ----------
# _stall_observer docstring 提 _global_stall_watchdog
i = lidx('判据口径与_global_stall_watchdog一致', 0)
repls.append((i, lines[i].replace(
    '判据口径与_global_stall_watchdog一致(那个是干预型、总开关关着只关不删),本方法只观测。',
    '判据=有任务在身却连续无任一进展心跳;本方法只观测报【异常】栏、绝不发键(2026-09-17干预型兜底已物理删除)。'),
    "改写 _stall_observer docstring 对已删兜底的引用"))
# _wd_check_antijitter docstring 末句提 _consume_anti_jitter
i = lidx('真正松键/锁侧/重置由主线_consume_anti_jitter执行', 0)
repls.append((i, lines[i].replace(
    '跳后1秒(in_gate)不判;置令冷却AJ_TRIG_COOLDOWN;真正松键/锁侧/重置由主线_consume_anti_jitter执行。',
    '跳后1秒(in_gate)不判;AJ_TRIG_COOLDOWN仅作日志节流;全程只记录、绝不松键/锁侧/重置(干预已于2026-09-17删除)。'),
    "改写 _wd_check_antijitter docstring 对已删 consume 的引用"))

# ---------- 区间自检：不重叠、有序 ----------
spans.sort()
for (a1, b1, d1), (a2, b2, d2) in zip(spans, spans[1:]):
    assert b1 < a2, "区间重叠: %r [%d,%d] vs %r [%d,%d]" % (d1, a1, b1, d2, a2, b2)

# ---------- 应用整行替换 ----------
for (idx, txt, desc) in sorted(repls):
    lines[idx] = txt

# ---------- 倒序删区间 ----------
for (a, b, desc) in sorted(spans, reverse=True):
    del lines[a:b + 1]

text = nl.join(lines)

# ---------- 阶段B：AST 删除 8 个连续干预函数 ----------
TARGETS = ['_global_stall_watchdog', '_global_stall_reset', '_mark_hard_reset_locked',
           '_wd_immediate_release', '_request_hard_reset', '_consume_hard_reset',
           '_consume_anti_jitter', '_hard_reset_state']

tree = ast.parse(text)
classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
hosts = [c for c in classes
         if any(isinstance(n, ast.FunctionDef) and n.name == '_global_stall_watchdog' for n in c.body)]
assert len(hosts) == 1, "含目标方法的类数量=%d（总类数=%d）" % (len(hosts), len(classes))
cls = hosts[0]
funcs = [n for n in cls.body if isinstance(n, ast.FunctionDef)]
fnames = [n.name for n in funcs]
for t in TARGETS:
    assert t in fnames, "阶段B 找不到函数 %s" % t
# 连续性：TARGETS 必须是类内顶层 FunctionDef 名序列的连续子序列
pos = fnames.index(TARGETS[0])
assert fnames[pos:pos + len(TARGETS)] == TARGETS, "8 函数不连续: %s" % fnames[pos - 1:pos + len(TARGETS) + 1]
fmap = {n.name: n for n in funcs}
first, last = fmap[TARGETS[0]], fmap[TARGETS[-1]]


def start_line(node):
    if node.decorator_list:
        return min(d.lineno for d in node.decorator_list)
    return node.lineno


sa = start_line(first) - 1
sb = last.end_lineno - 1
tlines = text.split(nl)
# 边界 sanity：sa 行是 def/@，sb 行非空
assert tlines[sa].lstrip().startswith('def ') or tlines[sa].lstrip().startswith('@'), tlines[sa]
assert tlines[sb].strip() != '', tlines[sb]
del tlines[sa:sb + 1]
# 收敛删除点相邻空行：最多保留一个空行分隔
while sa + 1 < len(tlines) and tlines[sa].strip() == '' and tlines[sa + 1].strip() == '':
    del tlines[sa + 1]
if sa < len(tlines) and tlines[sa].strip() == '' and (sa == 0 or tlines[sa - 1].strip() == ''):
    del tlines[sa]
text = nl.join(tlines)

# ---------- 写盘前断言 ----------
MUST_GONE = [
    'def _global_stall_watchdog', 'def _global_stall_reset', 'def _mark_hard_reset_locked',
    'def _wd_immediate_release', 'def _request_hard_reset', 'def _consume_hard_reset',
    'def _consume_anti_jitter', 'def _hard_reset_state',
    'self._consume_hard_reset', 'self._consume_anti_jitter', 'self._global_stall_watchdog',
    'self._hard_reset_state', 'self._wd_immediate_release', 'self._request_hard_reset',
    'self._mark_hard_reset_locked', 'self._global_stall_reset',
    '_hard_reset_req', '_hard_reset_last_t', '_hard_reset_done', '_anti_jitter_done',
    '_detect_reset_seq', '_seen_reset_seq', '_aj_hold_side', '_aj_stage',
    '_aj_last_trigger_t', '_wd_antijitter_req', '_wd_stall_req',
    'ENABLE_GLOBAL_STALL_FALLBACK', 'GLOBAL_STALL_MS', 'GLOBAL_RESET_COOLDOWN_MS',
    'AJ_HOLD_MS', 'AJ_ESCALATE_MS',
]
leftover = {}
for tok in MUST_GONE:
    c = text.count(tok)
    if c:
        leftover[tok] = c
assert not leftover, "仍有残留标识符: %s" % leftover

MUST_KEEP = [
    'def _stall_observer', 'def _wd_check_once', 'def _wd_check_axis',
    'def _wd_check_antijitter', 'def _wd_audit_keys', 'def _move_watchdog_loop',
    'def _start_move_watchdog', 'def _stop_move_watchdog',
    'def _bound_pull_tick', 'def _bound_guard_loop', 'def _bound_check_once',
    'def _reset_climb', 'def _unblock_tick', 'def _fall_return_tick',
    'def _abort_unreachable_target', '_combat_suppress_side',
    'self._wd_x_flips', 'self._wd_aj_last_req', 'STALL_OBSERVE_MS',
    'GLOBAL_MOVE_PX', 'GLOBAL_MAP_D', 'GLOBAL_SKILL_HB_MS',
    'AJ_WIN_MS', 'AJ_FLIP_MIN', 'AJ_NET_MAP_DX', 'AJ_TRIG_COOLDOWN',
    '_combat_mons = self._monsters',
]
for tok in MUST_KEEP:
    assert tok in text, "应保留但丢失: %s" % tok

# 语法可解析
ast.parse(text)

with io.open(PATH, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(text)

print("OK 原始行数=%d 删除区间=%d 替换行=%d 删函数8个" % (orig_n, len(spans), len(repls)))
print("新行数=%d 净删=%d" % (len(text.split(nl)), orig_n - len(text.split(nl))))
