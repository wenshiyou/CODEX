# -*- coding: utf-8 -*-
"""Step6c: AST精确物理删除白框dead方法cluster(18个),保留夹在中间的后脑/卡梯/mm新方法/黑框方法。
相邻(间隔仅空行)目标方法自动合并为连续区间整段删;孤立方法删除并吞后随<=2空行。保BOM/CRLF。"""
import ast, io
P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(P, 'r', encoding='utf-8-sig', newline='') as f:
    src = f.read()
tree = ast.parse(src)
NAMES = {
 '_ladder_approach_step','_ladder_realign_jump','_ladder_debug_diff_log','_realign_release_move',
 '_ladder_realign_step','_enter_desc_lad_scr','_desc_align_ladder_screen','_match_ladder_screen_x',
 '_ladder_use_yolo','_init_ladder_yolo','_read_ladder_class_id','_detect_ladder_yolo',
 '_freeze_ladder_patch','_scan_ladder_marks','_merge_nearby_ladders','_dir_band_pick_ladder',
 '_scr_nudge_timing','_ladder_align_by_screen'}
nodes = []
for n in ast.walk(tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in NAMES:
        nodes.append((n.lineno, n.end_lineno, n.name))
found = {x[2] for x in nodes}
missing = NAMES - found
assert not missing, 'NOT FOUND: %s' % missing
nodes.sort()
lines = src.splitlines(keepends=True)

# 合并相邻(间隔仅空行)的目标区间
segs = []
for s, e, name in nodes:
    if segs:
        ps, pe = segs[-1]
        between = ''.join(lines[pe:s-1])  # 0-based: pe .. s-2
        if between.strip() == '':
            segs[-1] = (ps, e)
            continue
    segs.append((s, e))

# 构造删除行索引集合(1-based -> 0-based),孤立区间吞后随<=2空行
drop = set()
for s, e in segs:
    for ln in range(s, e+1):
        drop.add(ln-1)
    j = e  # 0-based 指向 end 后第一行
    swallowed = 0
    while j < len(lines) and lines[j].strip() == '' and swallowed < 2:
        drop.add(j); j += 1; swallowed += 1

out = [ln for i, ln in enumerate(lines) if i not in drop]
new_src = ''.join(out)
ast.parse(new_src)  # 语法校验
with io.open(P, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(new_src)
print('STEP6c OK: removed %d methods in %d contiguous segments, dropped %d lines' % (
    len(nodes), len(segs), len(drop)))
for s, e in segs:
    print('  seg %d-%d (%d lines)' % (s, e, e-s+1))
