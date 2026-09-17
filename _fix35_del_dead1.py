# -*- coding: utf-8 -*-
"""第一批精简：删除零引用旧人物模板匹配链/旧整框vote/旧随机巡路归位/旧人物特征窗/零碎旧函数，
截断 _random_step 为新系统占位，删除 Y一秒最低值平滑残留。带断言，不满足不写盘。"""
import ast, io, sys
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
raw = io.open(P, "r", encoding="utf-8-sig", newline="").read()
nl = "\r\n" if "\r\n" in raw else "\n"
lines = raw.split(nl)
tree = ast.parse(raw)

# 整函数物理删除（AST 已核实零外部调用；其内部调用的共享 helper 一律保留）
del_funcs = [
    # A. 旧人物模板匹配链（人物白框现走 _get_player_screen_pos 人名/脸/后脑 + 小地图光点）
    "_char_three_score", "_findpic", "_color_ratio_confirm",
    "_findpic_roi_fast", "_findpic_full_fast", "_match_character",
    # B. 旧整框 vote 定脚（已被 _get_player_screen_pos 取代，零调用）
    "_load_char_vote_set", "_vote_match_character",
    # C. 旧随机巡路/人性化转身/被撞归位整簇（新系统一条线，恒不进入）
    "_random_enhanced_tick", "_do_human_turn", "_do_return_to_start",
    "_jump_once", "_try_ladder_return", "_try_platform_return",
    # E. 零碎零引用旧功能
    "_calc_character_monster_distance", "_clear_route_file",
    "_get_slope_direction", "_role_eval_live",
    # F. 旧人物特征窗/采集窗（菜单现走 _open_role_recognize_window）
    "_open_char_feature_window", "_char_feature_capture",
]
# D. _random_step 截断为新系统占位（旧 idle/moving/attacking/returning 状态机整段移除）
repl_funcs = {
    "_random_step": [
        "    def _random_step(self, player_pos):",
        '        """随机模式每帧占位。【一条线原则·用户2026-09-09】新系统(_use_new_system恒True)下所有角色行动',
        "        (走/跳/瞬移/上下梯/打怪)统一由 _combat_tick 主线按 识别→锁怪→巡路→打怪 串行发出,本函数不再产生",
        '        任何旁路行动,直接返回;旧随机巡路/转身/归位状态机已物理删除(需要回看走 git/本地快照)。"""',
        "        if not self._random_running:",
        "            return",
        "        if getattr(self, '_use_new_system', True):",
        "            return",
    ],
}

found = {}
for n in ast.walk(tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if n.name in del_funcs or n.name in repl_funcs:
            if n.name in found:
                print("!! 重名函数，中止:", n.name); sys.exit(2)
            found[n.name] = n
missing = [x for x in del_funcs + list(repl_funcs) if x not in found]
if missing:
    print("!! 未找到目标函数，中止:", missing); sys.exit(2)

ops = []  # (start1, end1, repl_lines_or_None)
for name in del_funcs:
    n = found[name]; s = n.lineno
    for d in n.decorator_list:
        s = min(s, d.lineno)
    ops.append((s, n.end_lineno, None))
for name, repl in repl_funcs.items():
    n = found[name]; s = n.lineno
    for d in n.decorator_list:
        s = min(s, d.lineno)
    ops.append((s, n.end_lineno, repl))

# G. Y“一秒最低值”平滑残留（用户已否决，人物线程里空算 + init 两行），按内容锚点删
def find_line(needle):
    for i, l in enumerate(lines):
        if needle in l:
            return i
    return -1

i1 = find_line("self._y_smooth_window = []")
assert i1 >= 0 and "_y_smooth_window_ms" in lines[i1 + 1], "Y平滑 init 锚点失败"
ops.append((i1 + 1, i1 + 2, None))

j1 = find_line("压入缓冲，清掉超过1秒")  # 仅人物线程段有此措辞，避开 __init__ 分组注释
assert j1 >= 0, "person Y平滑注释锚点失败"
assert "_now_ms = time.time()" in lines[j1 + 1], lines[j1 + 1]
assert "_y_smooth_window.append" in lines[j1 + 2], lines[j1 + 2]
assert "while self._y_smooth_window" in lines[j1 + 3], lines[j1 + 3]
assert "_y_smooth_window.pop(0)" in lines[j1 + 4], lines[j1 + 4]
ops.append((j1 + 1, j1 + 5, None))

# 区间互不重叠校验
ops_sorted = sorted(ops)
for k in range(1, len(ops_sorted)):
    if ops_sorted[k][0] <= ops_sorted[k - 1][1]:
        print("!! 删除区间重叠，中止:", ops_sorted[k - 1], ops_sorted[k]); sys.exit(3)

before = len(lines)
for s, e, repl in sorted(ops, key=lambda x: x[0], reverse=True):
    if repl is None:
        del lines[s - 1:e]
    else:
        lines[s - 1:e] = repl
after = len(lines)
new_text = nl.join(lines)

# 写盘前断言：目标函数全消失、在用函数全保留、Y平滑无残留
nt = ast.parse(new_text)
defs = {n.name for n in ast.walk(nt) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
still = [x for x in del_funcs if x in defs]
assert not still, ("目标函数仍存在，中止: %s" % still)
assert "_random_step" in defs
must_present = ["_match_monster", "_get_player_screen_pos", "_capture_window", "_stop_random",
                "_scan_ladder_marks", "_stop_detection_thread", "_recognize_loop", "_person_loop",
                "_capture_character_feature", "_match_monster"]
gone = [x for x in must_present if x not in defs]
assert not gone, ("误删在用函数，中止: %s" % sorted(set(gone)))
assert "_y_smooth_window" not in new_text, "Y平滑仍有残留，中止"

io.open(P, "w", encoding="utf-8-sig", newline="").write(new_text)
print("OK 整函数删除%d个 截断%d个 Y平滑2处; 行数 %d -> %d (净删 %d)" %
      (len(del_funcs), len(repl_funcs), before, after, before - after))
