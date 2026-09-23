# -*- coding: utf-8 -*-
# 离线断言：锁后全程Y复核。抽取真实 _pick_ladder_minimap/_ladder_mm_band/_ladder_mm_goto_tick，动作全部桩化。
import ast, io, types, textwrap

SRC = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
src = io.open(SRC, "rb").read().decode("utf-8-sig")
tree = ast.parse(src)

funcs = {}
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        for st in node.body:
            if isinstance(st, ast.FunctionDef) and st.name in (
                    "_pick_ladder_minimap", "_ladder_mm_band", "_ladder_mm_goto_tick"):
                funcs[st.name] = ast.get_source_segment(src, st)
assert len(funcs) == 3, funcs.keys()

# 模块级全大写数字常量
g = {}
for st in tree.body:
    if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
        n = st.targets[0].id
        if isinstance(st.value, ast.Constant) and isinstance(st.value.value, (int, float)) and n.isupper():
            g[n] = st.value.value
for k, v in {"VK_LEFT": 0x25, "VK_UP": 0x26, "VK_RIGHT": 0x27, "VK_DOWN": 0x28}.items():
    g.setdefault(k, v)
g["_debug_log"] = lambda *a, **k: None
for nm, code in funcs.items():
    exec(textwrap.dedent(code), g)
pick, band, goto = g["_pick_ladder_minimap"], g["_ladder_mm_band"], g["_ladder_mm_goto_tick"]

T1 = {"id": 1, "x": 100, "y_top": 80, "y_bottom": 100}   # 下层梯:光点py=100时梯底贴光点
T2 = {"id": 2, "x": 100, "y_top": 50, "y_bottom": 70}    # 上层梯:光点py=72时梯底差2

class Fake:
    def __init__(self, ladders):
        self.ladders = ladders
        self._ladder_mm_lock_id = None
        self._ladder_mm_cand_id = None
        self._ladder_mm_cand_streak = 0
        self._ladder_mm_no_pick_t = 0
        self._ladder_mm_pick_t = 0
        self._ladder_mm_prev_px = None
        self._ladder_mm_prev_ad = None
        self._ladder_mm_dir_sign = None
        self._ladder_mm_approach_streak = 0
        self._ladder_mm_still_frames = 0
        self._ladder_mm_fine_phase = ""
        self._ladder_mm_ybad_streak = 0
        self._ladder_run_jumped = False
        self._ladder_vert_jumped = False
        self._ladder_target_mon_x = None
        self._player_screen_pos = None
        self._ladder_jump_cfg = {}
        self._random_move_keys = set()
        self.jumps = []
        self.resets = 0
        self.fail_decided = False
    # 真实静态逻辑(挂实例属性,不绑定self)
    _pick_ladder_minimap = staticmethod(pick)
    _ladder_mm_band = staticmethod(band)
    def _ladder_mm_pin(self, ld):
        self._climb_ladder_x, self._climb_ladder_y_top, self._climb_ladder_y_bottom = ld["x"], ld["y_top"], ld["y_bottom"]
    def _key_up(self, vk): pass
    def _key_down(self, vk): pass
    def _hold_toward_ladder(self, d): pass
    def _ladder_mm_start_jump(self, kind, d, py, now_ms, jump_key, vx=0.0):
        self.jumps.append((kind, py, abs(d))); return False
    def _ladder_mm_fine_tick(self, d, ad, vl, py, now_ms, jump_key): return False
    def _reset_climb(self): self.resets += 1
    def _decide_climb_fail_action(self): self.fail_decided = True
    def _rlog(self, *a, **k): pass

def run(fs, seq):
    """seq: [(px,py), ...] 每帧+50ms"""
    t = 1000
    for px, py in seq:
        goto(fs, px, py, t, "C"); t += 50

# S1 Y恒对、水平走近:应正常锁id1并在跨rj(7)时跑跳,锁不被Y解锁
fs = Fake([dict(T1)])
seq = [(80, 100), (82, 100)]                      # 2帧建锁
seq += [(x, 100) for x in range(84, 96, 2)]       # 84..94, ad 16->6 跨7
run(fs, seq)
assert fs._ladder_mm_lock_id == 1, fs._ladder_mm_lock_id
assert fs._ladder_mm_ybad_streak == 0
assert any(k == "run" for k, _, _ in fs.jumps), fs.jumps
print("[PASS] S1 Y对:锁id1不被Y误解锁,跨7线带速跑跳 ->", fs.jumps)

# S2 锁后漂高(py=72,梯底差28)连续2帧:解锁、绝不起跳
fs = Fake([dict(T1)])
run(fs, [(80, 100), (82, 100)])                   # 锁id1
assert fs._ladder_mm_lock_id == 1
run(fs, [(82, 72), (82, 72)])                     # 连续2帧Y不合格
assert fs._ladder_mm_lock_id is None, fs._ladder_mm_lock_id
assert fs.jumps == [], fs.jumps
print("[PASS] S2 锁后漂高连续2帧:解锁重选、不在错误Y起跳")

# S3 单帧Y抖动(85)后回正(100):不误解,仍锁id1
fs = Fake([dict(T1)])
run(fs, [(80, 100), (82, 100)])
run(fs, [(82, 85), (82, 100)])
assert fs._ladder_mm_lock_id == 1, fs._ladder_mm_lock_id
assert fs.jumps == []
print("[PASS] S3 单帧Y抖动:不触发解锁,锁保持id1")

# S4 锁后漂低(py=116,梯底差16)连续2帧:解锁
fs = Fake([dict(T1)])
run(fs, [(80, 100), (82, 100)])
run(fs, [(82, 116), (82, 116)])
assert fs._ladder_mm_lock_id is None
assert fs.jumps == []
print("[PASS] S4 锁后漂低连续2帧:解锁重选")

# S5 漂高解锁后,当前高度(py=72)够得着的是上层T2:连续2帧重选锁id2
fs = Fake([dict(T1), dict(T2)])
run(fs, [(80, 100), (82, 100)])                   # 先锁T1
assert fs._ladder_mm_lock_id == 1
run(fs, [(82, 72), (82, 72)])                     # T1不合格解锁
assert fs._ladder_mm_lock_id is None
run(fs, [(82, 72), (82, 72)])                     # 未锁重选:T2合格,2帧锁id2
assert fs._ladder_mm_lock_id == 2, fs._ladder_mm_lock_id
print("[PASS] S5 解锁后用最新光点重选到当前高度够得着的梯 id2")

print("\n全部Y复核断言通过")
