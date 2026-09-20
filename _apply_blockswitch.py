# -*- coding: utf-8 -*-
"""B锁怪总开关(用户2026-09-21):锁怪与识怪分开设置。
- 识怪(YOLO/怪表/血条快照)在锁怪总闸之前独立常跑,本补丁不碰,永远不停;
- 新增 _b_lock_enabled(默认True): False=停锁怪决策、当场清已锁一整套、不出锁怪包;
  并入B线程现有总闸(与硬冻/到顶重锁窗同一清锁分支); True=恢复,B下帧用热怪表重锁。"""
import io, ast

MP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(MP, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()

# 1) init 加开关变量(锁怪字段区)
old1 = (
"        self._b_lock_time = 0                # B私有:当前锁锁定时刻ms\n"
"        self._b_probe_side = random.choice([-1, 1])   # B私有:左右探测侧(决策归B)\n"
)
new1 = (
"        self._b_lock_time = 0                # B私有:当前锁锁定时刻ms\n"
"        self._b_lock_enabled = True          # B锁怪总开关(用户2026-09-21):False=停锁怪决策并当场清已锁+不出包;识怪(YOLO/怪表/血条快照)在锁怪闸之前独立常跑、永不停(识怪与锁怪分开设置)\n"
"        self._b_probe_side = random.choice([-1, 1])   # B私有:左右探测侧(决策归B)\n"
)

# 2) _is_lock_frozen 后插入 setter
old2 = (
"        if cs == 'to_ladder' and getattr(self, '_ladder_jump_phase', None) in ('post_jump', 'realign'):\n"
"            return True\n"
"        return False\n"
"\n"
"\n"
"    def _set_combat_move(self, direction, allow_in_transit=False):\n"
)
new2 = (
"        if cs == 'to_ladder' and getattr(self, '_ladder_jump_phase', None) in ('post_jump', 'realign'):\n"
"            return True\n"
"        return False\n"
"\n"
"    def _set_b_lock_enabled(self, on, why=''):\n"
"        \"\"\"B锁怪总开关(用户2026-09-21),与识怪彻底分开:只控锁怪决策,绝不影响YOLO识怪/怪表/血条快照(那些在锁怪闸之前常跑)。\n"
"        on=False 停止锁怪并【当场】清掉已锁一整套(锁/类别/确认/决策包/出手反馈),主线当帧即不再打旧目标,不必等B下一帧;\n"
"        on=True  恢复锁怪,不清场,B下一帧用一直热着的怪表立即重锁。返回是否发生了切换。\"\"\"\n"
"        on = bool(on)\n"
"        if on == getattr(self, '_b_lock_enabled', True):\n"
"            return False\n"
"        self._b_lock_enabled = on\n"
"        if not on:\n"
"            self._b_lock = None; self._b_lock_tier = None\n"
"            self._b_hp_confirmed = False; self._b_gone = 0; self._b_lock_time = 0\n"
"            self._combat_decision_packet = None; self._combat_exec_feedback = None\n"
"            _debug_log(\"[锁怪开关] 关闭锁怪并清已锁(原因=%s);识怪/怪表/血条照常\" % (why or '?'))\n"
"            self._rlog(\"关闭锁怪·清已锁(%s)\" % (why or '?'), log='behavior')\n"
"        else:\n"
"            _debug_log(\"[锁怪开关] 恢复锁怪(原因=%s);B下帧用热怪表重锁,识怪未停过\" % (why or '?'))\n"
"            self._rlog(\"恢复锁怪(%s)\" % (why or '?'), log='behavior')\n"
"        return True\n"
"\n"
"\n"
"    def _set_combat_move(self, direction, allow_in_transit=False):\n"
)

# 3) B线程总闸并入开关
old3 = (
"                        if self._is_lock_frozen() or int(time.time() * 1000) < getattr(self, '_arrival_relock_until', 0):  # 再叠到顶/下跳落地重锁保护窗(下跳=进descend+2秒):窗内同样清锁不出包、怪表照刷,落稳零等待重锁(用户2026-09-19)\n"
)
new3 = (
"                        if (not getattr(self, '_b_lock_enabled', True)) or self._is_lock_frozen() or int(time.time() * 1000) < getattr(self, '_arrival_relock_until', 0):  # 锁怪总开关关=清锁不出包(识怪/怪表/血条照跑,与锁怪分开);或硬冻/到顶下跳重锁保护窗:窗内清锁不出包、怪表照刷,落稳零等待重锁\n"
)

for old, new, tag in [(old1, new1, "init"), (old2, new2, "setter"), (old3, new3, "gate")]:
    c = s.count(old)
    assert c == 1, "锚点不唯一/缺失 [%s] count=%d" % (tag, c)
    s = s.replace(old, new)

ast.parse(s)
with io.open(MP, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
print("BLOCKSWITCH_OK")
