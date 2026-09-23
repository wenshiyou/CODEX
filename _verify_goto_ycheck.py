# -*- coding: utf-8 -*-
import ast, io
SRC = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
src = io.open(SRC, "rb").read().decode("utf-8-sig")
tree = ast.parse(src)

# 1) 新常量模块级定义恰好1次
def_count = {}
for st in tree.body:
    if isinstance(st, ast.Assign):
        for t in st.targets:
            if isinstance(t, ast.Name) and t.id in ("LADDER_MM_GOTO_END_TOL", "LADDER_MM_GOTO_UNLOCK_FRAMES"):
                def_count[t.id] = def_count.get(t.id, 0) + 1
assert def_count == {"LADDER_MM_GOTO_END_TOL": 1, "LADDER_MM_GOTO_UNLOCK_FRAMES": 1}, def_count
print("[OK] 两个新常量各定义1次")

# 2) 新self属性名不得与任何方法重名
method_names = set()
for n in ast.walk(tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        method_names.add(n.name)
assert "_ladder_mm_ybad_streak" not in method_names, "新属性与方法重名!"
print("[OK] _ladder_mm_ybad_streak 不与任何方法重名")

# 3) 读盘count
assert src.count("LADDER_MM_GOTO_END_TOL = 14") == 1
assert src.count("LADDER_MM_GOTO_UNLOCK_FRAMES = 2") == 1
assert src.count("self._ladder_mm_ybad_streak = 0") >= 2  # reset + 合格分支/解锁分支
assert src.count("锁后Y不合格连续%d帧") == 1
print("[OK] 补丁三处读盘计数正确, ybad引用次数 =", src.count("_ladder_mm_ybad_streak"))

# 4) goto_tick 内 Y复核 必须排在所有 start_jump 调用之前
for n in ast.walk(tree):
    if isinstance(n, ast.FunctionDef) and n.name == "_ladder_mm_goto_tick":
        seg = ast.get_source_segment(src, n)
        i_y = seg.find("_ladder_mm_ybad_streak")
        i_jump = seg.find("_ladder_mm_start_jump")
        assert 0 <= i_y < i_jump, (i_y, i_jump)
        print("[OK] goto_tick 中Y复核(位置%d)排在起跳调用(位置%d)之前" % (i_y, i_jump))
print("\n遮蔽/顺序/计数扫描全部通过")
