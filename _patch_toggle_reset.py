# -*- coding: utf-8 -*-
# 临时补丁(不提交git): F10/F12 运行边界干净复位战斗瞬时态, 修"爬梯中途停止->再启动锁怪总开关泄漏、有怪永不锁永不打"
import io, sys, ast

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
raw = io.open(P, 'rb').read().decode('utf-8-sig')
s = raw.replace('\r\n', '\n')

# ---- 锚点A: 在 _set_b_lock_enabled 之后、_set_combat_move 之前插入集中复位方法 ----
oldA = '''            _debug_log("[锁怪开关] 恢复锁怪(原因=%s);B下帧用热怪表重锁,识怪未停过" % (why or '?'))
            self._rlog("恢复锁怪(%s)" % (why or '?'), log='behavior')
        return True


    def _set_combat_move(self, direction, allow_in_transit=False):'''

newA = '''            _debug_log("[锁怪开关] 恢复锁怪(原因=%s);B下帧用热怪表重锁,识怪未停过" % (why or '?'))
            self._rlog("恢复锁怪(%s)" % (why or '?'), log='behavior')
        return True

    def _reset_runtime_combat_state(self, why=''):
        """F10启动/F12停止(所有启停路径经_start_random/_stop_random汇聚)的战斗瞬时态干净复位。
        根因(2026-09-23真机):进上梯_set_b_lock_enabled(False)后若爬梯中途被F12停止,到顶/失败两个开锁出口
        都没走到;_reset_climb只复位_climb_state、不恢复锁怪开关,再F10启动后B门控(not _b_lock_enabled)每帧
        清锁不出包->识怪照跑却永不锁永不打(停在梯上十分钟有怪不打)。故启停边界必须:锁怪开关开回、清跨层/
        瞬移/重锁窗与上一局旧锁旧包。识怪怪表/血条快照不清——B用一直热着的怪表下帧立即重锁、零等待。"""
        self._set_b_lock_enabled(True, why or '运行边界复位')
        # 跨层行进/重锁保护窗不跨局残留(否则新一局还沿旧台路线走、或长时间清锁不出包)
        self._combat_transit = False
        self._transit_target = None
        self._arrival_relock_until = 0
        self._no_transit_until = 0
        # 瞬移瞬时态全清:失败封禁/后摇/待校验/冷却不带入下一局
        self._combat_tp_pending = None
        self._combat_tp_fail_key = None
        self._combat_tp_fail_cnt = 0
        self._combat_tp_block_until = 0
        self._combat_tp_post_until = 0
        self._combat_last_h_teleport = 0
        self._char_relocate_until = 0
        # 全新边界清上一局旧锁/决策包/锁梯(到顶开锁故意不清场是为热表重锁,启停则必须清)
        self._b_lock = None; self._b_lock_tier = None
        self._b_hp_confirmed = False; self._b_gone = 0; self._b_lock_time = 0
        self._combat_decision_packet = None; self._combat_exec_feedback = None
        self._locked_ladder = None
        self._ladder_mm_lock_id = None; self._ladder_mm_cand_id = None
        self._ladder_mm_cand_streak = 0; self._ladder_mm_pick_t = 0
        self._ladder_mm_ybad_streak = 0; self._ladder_mm_bad = {}


    def _set_combat_move(self, direction, allow_in_transit=False):'''

# ---- 锚点B: _start_random ----
oldB = '''        self._release_all_keys()
        self._reset_climb()
        self._random_running = True'''
newB = '''        self._release_all_keys()
        self._reset_climb()
        self._reset_runtime_combat_state('F10启动·干净开场')
        self._random_running = True'''

# ---- 锚点C: _stop_random ----
oldC = '''        self._release_all_keys()
        self._reset_climb()
        self._random_running = False'''
newC = '''        self._release_all_keys()
        self._reset_climb()
        self._reset_runtime_combat_state('F12停止·收场复位')
        self._random_running = False'''

for name, old in (('A', oldA), ('B', oldB), ('C', oldC)):
    c = s.count(old)
    assert c == 1, "锚点%s 命中数=%d(应为1), 未写盘" % (name, c)

s2 = s.replace(oldA, newA).replace(oldB, newB).replace(oldC, newC)

# 写盘(CRLF + utf-8-sig)
out = s2.replace('\n', '\r\n')
io.open(P, 'w', encoding='utf-8-sig', newline='').write(out)
print("[写盘] OK, 字符数 %d -> %d" % (len(raw), len(out)))

# ---- 校验1: py_compile ----
import py_compile
py_compile.compile(P, doraise=True)
print("[py_compile] OK")

# ---- 校验2: 读盘 count ----
chk = io.open(P, 'rb').read().decode('utf-8-sig').replace('\r\n', '\n')
assert chk.count("def _reset_runtime_combat_state") == 1
assert chk.count("self._reset_runtime_combat_state(") == 3  # 定义1+start1+stop1
assert chk.count("_reset_runtime_combat_state('F10启动·干净开场')") == 1
assert chk.count("_reset_runtime_combat_state('F12停止·收场复位')") == 1
print("[读盘count] 方法定义1 + start/stop调用各1 OK")

# ---- 校验3: AST 解析, 新方法内每个 self._x 必须在方法外全文也出现过(防拼错造新属性漏清真字段) ----
tree = ast.parse(chk)
fn = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MinimapRouteRecorder')
newfn = next(n for n in fn.body if isinstance(n, ast.FunctionDef) and n.name == '_reset_runtime_combat_state')
seg = ast.get_source_segment(chk, newfn)
attrs = set()
for n in ast.walk(newfn):
    if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'self':
        attrs.add(n.attr)
outside = chk.replace(seg, '')
missing = [a for a in attrs if ('self.' + a) not in outside and a != '_set_b_lock_enabled']
# _set_b_lock_enabled 是方法调用, 单独核
assert ('def _set_b_lock_enabled' in outside), "_set_b_lock_enabled 方法在外部不存在"
bad = [a for a in attrs if ('self.' + a) not in outside and ('def ' + a) not in outside]
assert not bad, "以下名字在新方法外从未出现(疑似拼写错误): %s" % bad
print("[AST属性核对] 新方法引用 %d 个 self 成员, 全部在方法外存在: %s" % (len(attrs), sorted(attrs)))
print("ALL OK")
