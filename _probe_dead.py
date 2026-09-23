# -*- coding: utf-8 -*-
"""探查: AST列出指定行区间内类方法名与行范围,识别白框dead cluster完整边界(不改文件)。"""
import ast, io
P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(P, 'r', encoding='utf-8-sig', newline='') as f:
    src = f.read()
tree = ast.parse(src)
ranges = [(5130, 5740), (5840, 6010), (10560, 11120)]
targets = {
 '_ladder_approach_step','_ladder_realign_jump','_ladder_debug_diff_log','_realign_release_move',
 '_ladder_realign_step','_enter_desc_lad_scr','_desc_align_ladder_screen','_match_ladder_screen_x',
 '_ladder_use_yolo','_freeze_ladder_patch','_scan_ladder_marks','_dir_band_pick_ladder',
 '_scr_nudge_timing','_ladder_align_by_screen'}
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        s, e = node.lineno, node.end_lineno
        if any(lo <= s <= hi for lo, hi in ranges):
            mark = ' <<< TARGET' if node.name in targets else ''
            print('%5d-%-5d %s%s' % (s, e, node.name, mark))
