# -*- coding: utf-8 -*-
# 清单二整套删除:动作权仲裁器/范围迟滞门/帧末移动权收敛/监管软仲裁/影子决策 (用户2026-09-15:全部不要,决策直连)
# 保留:_bound_pull 边界拉回整套、_snap_store 世界快照、监管硬重置/停滞(与仲裁无关)
import io, re
P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
s = io.open(P, encoding='utf-8').read()
orig_len = len(s)

def cut_between(start_anchor, next_anchor, tag):
    """删除[start_anchor行首, next_anchor行首)之间整段(保留next)"""
    global s
    i = s.find(start_anchor); j = s.find(next_anchor)
    assert i != -1 and j != -1 and i < j, 'CUT FAIL %s i=%s j=%s' % (tag, i, j)
    s = s[:i] + s[j:]
    print('cut func/block:', tag)

def del_lines(prefix, expect, tag):
    """删除所有 strip 后以 prefix 开头的行,断言删了 expect 行"""
    global s
    lines = s.splitlines(keepends=True)
    keep = [l for l in lines if not l.lstrip().startswith(prefix)]
    n = len(lines) - len(keep)
    assert n == expect, 'DEL_LINE %s got=%d expect=%d' % (tag, n, expect)
    s = ''.join(keep)
    print('del lines x%d:' % n, tag)

def rep(old, new, tag, n=1):
    global s
    c = s.count(old); assert c == n, 'REP %s got=%d expect=%d' % (tag, c, n)
    s = s.replace(old, new); print('replace:', tag)

# ---- 1) 导入行(只删 action_arbiter,保留 world_snapshot) ----
del_lines('from core.action_arbiter import', 1, 'import action_arbiter')

# ---- 2) 常量 WD_ARBITER_HOLD_MS ----
del_lines('WD_ARBITER_HOLD_MS =', 1, 'WD_ARBITER_HOLD_MS const')

# ---- 3) 字段(初始化区 + 硬重置复位区,全部出现处) ----
del_lines('self._motion_owner = None', 1, '_motion_owner field')
del_lines('self._wd_conflict_req = None', 2, '_wd_conflict_req field+reset')
del_lines("self._wd_arbiter_loser = None", 2, '_wd_arbiter_loser field+reset')
del_lines('self._wd_arbiter_until = 0', 2, '_wd_arbiter_until field+reset')

# ---- 4) 实例 _arbiter/_range_gate/_shadow_arb_log_t/_arbiter_live ----
del_lines('self._arbiter = ActionArbiter', 1, '_arbiter inst')
del_lines('self._range_gate = RangeGate', 1, '_range_gate inst')
del_lines('self._shadow_arb_log_t = 0.0', 1, '_shadow_arb_log_t inst')
del_lines("self._arbiter_live = True", 1, '_arbiter_live inst')
rep("""        # 架构第1块·影子地基:世界快照仓(识别线程唯一出口)+动作权仲裁器+范围迟滞门。
        # 影子阶段只发布快照、只比对仲裁结果,不接发键回调、不夺权,现有行为完全不变。
        self._snap_store = SnapshotStore()""",
"""        # 世界快照仓(识别线程唯一出口)。动作权仲裁器/范围迟滞门已按用户2026-09-15整套删除:打怪/巡路一条线直连,不再有第三方劝架。
        self._snap_store = SnapshotStore()""", 'snap comment')

# ---- 5) F3 一键切换仲裁整块删(F3轮询保留,不再handle) ----
rep("""        if vk == VK_F3:
            # 架构B:仲裁器实控↔老逻辑一键切换(实控=RangeGate按R-50进/R+25出迟滞接管平地开打;关=完全回stop_range单阈值老逻辑)
            self._arbiter_live = not getattr(self, '_arbiter_live', True)
            self._range_gate.reset()   # 切换瞬间清迟滞状态,不沿用上一套判定
            _msg = "动作权仲裁→实控(新)" if self._arbiter_live else "动作权仲裁→老逻辑(退回)"
            print("[F3]", _msg)
            self._add_log(_msg)
            _debug_log("[F3] _arbiter_live=%s" % self._arbiter_live)
            return
""", '', 'F3 arbiter switch block')

# ---- 6) 五个函数定义整段删(按 def 边界切片,保留下一个def) ----
cut_between('    def _converge_movement(self):', '    def _lock_target_ladder_for_cross', '_converge_movement')
cut_between('    def _abort_transit_for_nearby(self):', '    def _is_lock_frozen', '_abort_transit_for_nearby')
cut_between('    def _wd_set_owner(self, owner):', '    def _wd_log(self, key', '_wd_set_owner')
cut_between('    def _wd_consume_conflict(self, now):', '    def _global_stall_watchdog', '_wd_consume_conflict')
cut_between('    def _shadow_combat_decision(self):', '    def _filter_static_monsters', '_shadow_combat_decision')

# ---- 7) 影子决策两处调用 ----
del_lines('self._shadow_combat_decision()', 2, 'shadow calls')

# ---- 8) 换新目标 _range_gate.reset() ----
del_lines('self._range_gate.reset()', 1, 'range_gate.reset at new target')

# ---- 9) 平地开打裁决改直连 ----
rep("""        if getattr(self, '_arbiter_live', False):
            # 架构B·实控:平地"站定开打/走近"统一由迟滞门+动作权仲裁器定(R-50进/R+25出,用户2026-09-12)。
            # y_ok先传True=只管X距离迟滞;Y够不够得到仍由下方主攻Y带/跳高打分支把,不在这里拦。
            _in_fight = self._range_gate.update(t_dist, True, skill_range)
            _o_arb, _ = self._arbiter.update(has_target=True, in_range=_in_fight)
            in_attack_range = (_o_arb == ActionMode.FIGHT)
        else:
            in_attack_range = t_dist <= stop_range""",
"""        # 一条线直连(用户2026-09-15:删动作权仲裁器/迟滞门):距离进停步线就站定开打,不经过第三方劝架
        in_attack_range = t_dist <= stop_range""", 'in_attack_range direct')

# ---- 10) 帧末 _converge_movement 调用 + 实控/影子仲裁日志整块(到"定期维护"前) ----
cut_between('            # 单一移动权·帧末收敛', '            # === 定期维护', 'frame-end converge+arbiter log')

# ---- 11) 提到已删软仲裁的三行注释 ----
rep("""        # 测试期冲突处理(用户2026-09-10):两套方向键互搏冲突统一由监管线程_wd_audit_keys一旦发现即硬重置(即时停手+
        # 帧首_consume_hard_reset清零),不再走"选一方继续"的软仲裁_wd_consume_conflict(函数保留,正式版要恢复软仲裁再启用):
        # self._wd_consume_conflict(now)
""", '', 'stale conflict comment')

io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('WRITE_OK  %d -> %d (-%d chars)' % (orig_len, len(s), orig_len-len(s)))

# ---- 12) 残留自检:这些符号删完必须 0 命中 ----
check = ['action_arbiter','ActionArbiter','ActionMode','RangeGate','self._arbiter','_range_gate',
         '_converge_movement','_move_owner','_shadow_combat_decision','_wd_set_owner','_motion_owner',
         '_wd_consume_conflict','_wd_conflict_req','_wd_arbiter','_shadow_arb_log_t','_arbiter_live',
         '_abort_transit_for_nearby','WD_ARBITER_HOLD_MS']
lines = s.splitlines()
bad = 0
for sym in check:
    hits = [(i+1, l.strip()) for i, l in enumerate(lines) if sym in l]
    if hits:
        bad += len(hits)
        print('!! RESIDUAL %s :' % sym)
        for n, t in hits: print('   ', n, t[:100])
print('CLEAN_CHECK residual=%d (必须为0)' % bad)
