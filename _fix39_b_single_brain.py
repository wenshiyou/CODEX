# -*- coding: utf-8 -*-
"""
第二批-B(2026-09-17): 把 _move_to 的"跨层脑子"剥掉,全项目只留一个动作决策大脑。
B-1  _move_to 整函数退化为纯同层水平脚 _move_horizontal(AST 定位整段替换)。
B-2  _transit_step 选台块(if self._transit_target:)重写: 同层水平走到点落公共收尾;
     跨层先水平对齐, 对齐后过闸门+失败冷却, 由唯一入口 _enter_to_ladder_up/_enter_descend 发起,
     发起后本帧return、下一帧由上方 _climb_state!=none 分支唯一tick状态机(不递归/不双tick)。
B-3  掉台归位(当前整套硬关闭)调用点改名 _move_horizontal; 跨层回台留待迁独立线程。
过时注释/docstring 逐条改准确(容错: 唯一命中才换, 末尾打印残留人工兜底)。
写盘前核心断言; 保留 UTF-8 BOM + CRLF。
"""
import ast
import io
import sys

PATH = 'maple_route_ui.py'

NEW_FN = '''    def _move_horizontal(self, player_pos, target_x, target_y):
        """纯同层水平移动脚(小地图坐标)·第二批-B收口(2026-09-17)。
        只负责: 水平按左右键走到目标X + 卡住1.5s小跳脱困 + 录制绿线上坡跑跳 + 同层微高差边走边跳。
        【不再有跨层脑子】不判上下层、不tick爬梯状态机、不发起上梯/下跳/瞬移——跨层决策唯一归
        _transit_step(选台)/_try_platform_transition(cross), 爬梯成套动作唯一由_transit_step每帧tick。
        返回True=同层到达(|dx|<=4且|dy|<=6); False=还没到(调用方下一帧继续调)。
        掉台归位当前整套硬关闭(_aux_enable_fall=False/主循环写死False), 其跨层回台待迁独立线程时
        由该线程自行驱动爬梯状态机, 不在本水平脚内决策。"""
        if player_pos is None:
            return False
        px, py = player_pos
        dx = target_x - px
        dy = target_y - py
        now_ms = time.time() * 1000

        # 水平移动
        if abs(dx) > 4:
            if dx > 0:
                if VK_LEFT in self._random_move_keys:
                    self._key_up(VK_LEFT)
                if VK_RIGHT not in self._random_move_keys:
                    self._key_down(VK_RIGHT)
            else:
                if VK_RIGHT in self._random_move_keys:
                    self._key_up(VK_RIGHT)
                if VK_LEFT not in self._random_move_keys:
                    self._key_down(VK_LEFT)

            # === 卡住检测：水平移动时每1.5秒确认X是否变化，没变化=被障碍物卡住→跳跃脱困 ===
            if not getattr(self, '_move_stuck_inited', False) or self._move_stuck_dir != (1 if dx > 0 else -1):
                self._move_stuck_last_x = px
                self._move_stuck_last_time = now_ms
                self._move_stuck_dir = 1 if dx > 0 else -1
                self._move_stuck_inited = True
            elif now_ms - self._move_stuck_last_time > 1500:
                if abs(px - self._move_stuck_last_x) < 5:
                    fight_cfg = self._get_fight_config()
                    jump_key = fight_cfg.get("jump_key", "")
                    if jump_key and now_ms - getattr(self, '_move_stuck_jump_time', 0) > 1200:
                        self._press_game_key(jump_key, duration=150)
                        self._move_stuck_jump_time = now_ms
                        _debug_log("[移动] 卡住：方向=%s X=%.0f 1.5秒未变化，跳跃脱困" % (
                            "右" if dx > 0 else "左", px))
                self._move_stuck_last_x = px
                self._move_stuck_last_time = now_ms

            # === 录制绿线坡度优先(用户2026-09-07；2026-09-10再定稿)：前方【录制绿线】Y波动>6判坡——
            # 低向高(上坡)=按住方向跑+连跳爬过去,这是被地形/台阶挡住过不去的正道解法,跨层去梯子路上被挡同样靠它;
            # 高向低(下坡)=只走不跳。只有"平台对接跳"(按目标点dy,易被光点±几px抖动误判台阶)才在跨层中屏蔽、下限6。
            _in_transit_walk = getattr(self, '_combat_transit', False)
            _grn_slope = self._platform_slope_ahead(px, py, 1 if dx > 0 else -1)
            _grn_jkey = self._get_fight_config().get("jump_key", "")
            if _grn_slope == 'up':
                # 绿线坡跳：跨层/非跨层都生效(过挡正道),仅350ms去重
                if _grn_jkey and now_ms - getattr(self, '_last_green_slope_jump', 0) > 350:
                    self._press_game_key(_grn_jkey, duration=120)
                    self._last_green_slope_jump = now_ms
                    _debug_log("[绿线坡] 前方上坡(低向高) 跑+跳")
            elif _grn_slope == 'down':
                pass  # 下坡只走，不跳，也不进微高差跳
            elif (not _in_transit_walk) and 6 <= abs(dy) <= 20:
                # 微高差平台对接：按目标点dy判(非录制绿线),易被小地图抖动误触发→跨层去梯子时屏蔽、下限提到6
                jump_key = _grn_jkey
                if jump_key:
                    last_jump = getattr(self, '_last_platform_gap_jump', 0)
                    if now_ms - last_jump > 350:
                        self._press_game_key(jump_key, duration=120)
                        self._last_platform_gap_jump = now_ms
                        _debug_log("[平台对接] 微高差%.0fpx，边走边跳" % dy)
        else:
            if VK_LEFT in self._random_move_keys:
                self._key_up(VK_LEFT)
            if VK_RIGHT in self._random_move_keys:
                self._key_up(VK_RIGHT)
            self._move_stuck_inited = False  # 到达目标X，重置卡住检测

        # 同层到达判断(纯水平脚不再调_reset_climb; 爬梯复位由状态机到顶/调用方收尾负责)
        return abs(dx) <= 4 and abs(dy) <= 6
'''

# B-2 选台块新逻辑(8空格 if 起始; 同层到达不return落公共收尾, 跨层发起return)
NEW_SEL = '''        if self._transit_target:
            # 选台模式:目标=录制台点(真实小地图坐标)。第二批-B(2026-09-17):走路脚退化为纯同层_move_horizontal,
            # 跨层决策收口到本唯一大脑——同层水平走;跨层先水平对齐,对齐后过闸门+失败冷却,再由唯一入口发起
            # 上梯/下跳;发起后本帧return,下一帧由上方 _climb_state!=none 分支唯一tick状态机(不递归/不双tick)。
            _sel_tx, _sel_ty = self._transit_target[0], self._transit_target[1]
            _sel_mdx = _sel_tx - mpx
            _sel_mdy = _sel_ty - mpy
            _SEL_SAME_FLOOR_DY = 8    # 同层Y阈值(与旧移动脚一致)
            _SEL_ALIGN_DX = 25        # 跨层前水平对齐阈值(与旧垂直兜底一致)
            if abs(_sel_mdy) <= _SEL_SAME_FLOOR_DY:
                # 1) 同层:纯水平脚走到台点,到点_reset_lock_after_arrival后落下方公共收尾重锁
                if not self._move_horizontal((mpx, mpy), _sel_tx, _sel_ty):
                    return
                self._reset_lock_after_arrival()
            elif abs(_sel_mdx) > _SEL_ALIGN_DX:
                # 2) 跨层但水平没对齐:先纯水平走,不发起跨层
                self._move_horizontal((mpx, mpy), _sel_tx, _sel_ty)
                return
            else:
                # 3) 水平已对齐、确有落差:过上下闸门+爬梯失败冷却后由唯一入口发起,本帧return(下帧状态机tick)
                _sel_vdir = 'up' if _sel_mdy < 0 else 'down'
                if self._bound_blocked_vertical(_sel_vdir):
                    self._release_move_conflicts()
                    self._rlog_throttle('sel_bound_gate', "选台:已到%s边界,不跨层,松键等待" % (
                        '上' if _sel_vdir == 'up' else '下'), 1000, log='behavior')
                    return
                if getattr(self, '_climb_fail_pause_until', 0) and now_ms < self._climb_fail_pause_until:
                    self._release_move_conflicts()
                    return
                if _sel_mdy < 0:
                    # 选台无屏幕怪参照:怪参照传None→to_ladder退化为"梯→人最近"选梯(与旧移动脚上入口等价,不新写选梯)
                    self._enter_to_ladder_up(mpx, mpy, now_ms, None, None)
                    _debug_log("[选台跨层] 目标在上层dy=%.0f且水平对齐,进to_ladder屏幕选梯上" % _sel_mdy)
                else:
                    self._enter_descend(_sel_tx, _sel_ty, mpx, mpy, now_ms)
                    _debug_log("[选台跨层] 目标在下层dy=%.0f,进descend原地先下跳、跳不了走梯" % _sel_mdy)
                return
'''

OLD_FALL = '            self._move_to(mmp, _t[0], _t[1])'
NEW_FALL = '            self._move_horizontal(mmp, _t[0], _t[1])  # 第二批-B:纯同层水平回台;跨层回台待迁独立线程(归位当前整套硬关闭)'

PAIRS = [
    ('用_move_to回原台',
     '用_move_horizontal回原台(同层;跨层回台待迁独立线程)'),
    ('喂给_move_to',
     '喂给_move_horizontal'),
    ('# 状态块整体从_move_to搬出,块内沿用_now_ms局部名,这里做别名(不影响_move_to自身)',
     '# 状态块早期从移动函数搬进_climb_state_machine,块内沿用_now_ms局部名作别名(第二批-B:移动脚已不再tick状态机)'),
    ('用于_combat_tick/_move_to等每帧热路径',
     '用于_combat_tick/_transit_step等每帧热路径'),
    ('归transit(_transit_step/_move_to)',
     '归transit(_transit_step/_move_horizontal)'),
    ('归位期间复用主线同一套 _move_to(自动找梯/跳/瞬移)回home台最近点',
     '归位当前整套硬关闭;启用后同层用纯水平脚 _move_horizontal 回home台最近点(跨层回台待迁独立线程)'),
    ('# 归位自身复用_move_to回台时也会让_climb_state变成攀爬态,但那时_combat_transit=False,必须继续归位、不能被误停',
     '# (归位当前整套硬关闭;将来迁独立线程后跨层回台由该线程自管状态机)判掉台只认主线_combat_transit=True为正常离开'),
    ('复用_move_to攀爬状态机（跳/瞬移/梯子，带Y验证）',
     'ladder段由_climb_state_machine成套动作驱动(唯一tick点),选台同层/水平对齐段用纯水平脚_move_horizontal'),
    ('保留_move_to旧路径',
     '交_transit_step选台分支(水平脚_move_horizontal+跨层状态机)'),
    ('state保持none交_move_to旧路径',
     'state保持none交_transit_step选台分支(水平脚+跨层状态机)'),
    ('爬梯在_move_to内部处理',
     '爬梯由_transit_step每帧唯一tick _climb_state_machine处理'),
    ('（_move_to自动跳/瞬移/爬梯）',
     '（_transit_step驱动状态机爬梯/水平脚走路）'),
    ('跨层行进由_transit_step持续驱动_move_to(持续按↑到顶)',
     '跨层行进由_transit_step每帧唯一tick _climb_state_machine(持续按↑到顶)'),
]


def main():
    s = io.open(PATH, encoding='utf-8-sig', newline='').read()

    # ---- B-1 ----
    tree = ast.parse(s)
    hits = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_move_to']
    assert len(hits) == 1, '期望唯一 _move_to 定义, 实际 %d' % len(hits)
    node = hits[0]
    a, b = node.lineno, node.end_lineno
    lines = s.splitlines(keepends=True)
    assert lines[a - 1].lstrip().startswith('def _move_to('), '起点行不符: %r' % lines[a - 1]
    new_fn = NEW_FN
    if not new_fn.endswith('\n'):
        new_fn += '\n'
    lines[a - 1:b] = [new_fn]
    s = ''.join(lines)
    print('[B-1] 整函数替换 行%d-%d -> _move_horizontal' % (a, b))

    # ---- B-2 锚点切片(真实结构: if self._transit_target: ... self._reset_lock_after_arrival()) ----
    start_anchor = '        if self._transit_target:\n            # 选台模式:目标=录制台点'
    assert s.count(start_anchor) == 1, '选台起始双行锚命中 %d' % s.count(start_anchor)
    ls = s.find(start_anchor)
    c = ls
    end_anchor = '            self._reset_lock_after_arrival()\n'
    e = s.find(end_anchor, c)
    assert e != -1, '选台块收尾锚未找到'
    be = e + len(end_anchor)
    assert 'self._move_to(' in s[ls:be], '切出的选台块不含_move_to调用'
    new_sel = NEW_SEL
    if not new_sel.endswith('\n'):
        new_sel += '\n'
    s = s[:ls] + new_sel + s[be:]
    print('[B-2] 选台块重写完成(切片%d字符 -> %d字符)' % (be - ls, len(new_sel)))

    # ---- B-3 ----
    assert s.count(OLD_FALL) == 1, '掉台归位调用命中 %d' % s.count(OLD_FALL)
    s = s.replace(OLD_FALL, NEW_FALL)
    print('[B-3] 掉台归位调用改名完成')

    # ---- 注释(容错: 唯一命中才换, 0命中打印跳过, 多命中报错) ----
    n_changed = 0
    for old, new in PAIRS:
        cnt = s.count(old)
        if cnt == 1:
            s = s.replace(old, new)
            n_changed += 1
        elif cnt == 0:
            print('[注释跳过] 未命中: %r' % old[:40])
        else:
            raise AssertionError('注释片段歧义命中%d次: %r' % (cnt, old[:40]))
    print('[注释] 替换 %d/%d 条' % (n_changed, len(PAIRS)))

    # ---- 残留 _move_to 扫描(写盘前) ----
    leftovers = [(i, l) for i, l in enumerate(s.split('\n'), 1) if '_move_to' in l]
    if leftovers:
        print('[残留 _move_to] 共%d行(应为0, 需人工核对):' % len(leftovers))
        for i, l in leftovers:
            print('   %d: %s' % (i, l.strip()[:100]))

    # ---- 核心断言 ----
    assert s.count('def _move_to(') == 0, '仍存在 def _move_to'
    assert s.count('def _move_horizontal(') == 1, '_move_horizontal 定义数异常'
    assert s.count('self._move_to(') == 0, '仍存在 self._move_to 调用'
    assert s.count('self._climb_state_machine(') == 1, \
        '爬梯状态机tick点=%d(应为1)' % s.count('self._climb_state_machine(')
    fn_tree = ast.parse(s)
    nh = [n for n in ast.walk(fn_tree) if isinstance(n, ast.FunctionDef) and n.name == '_move_horizontal']
    assert len(nh) == 1
    seg = ast.get_source_segment(s, nh[0])
    for forbidden in ['self._climb_state_machine(', 'self._enter_descend(',
                      'self._enter_to_ladder_up(', 'self._do_teleport(',
                      'self._bound_block_up(', 'self._bound_block_down(',
                      'self._reset_climb(', '"to_ladder"', "'to_ladder'"]:
        assert forbidden not in seg, '纯水平脚仍含跨层逻辑: %s' % forbidden
    for needle in ['self._move_horizontal((mpx, mpy)', 'self._bound_blocked_vertical(_sel_vdir)',
                   'self._enter_to_ladder_up(mpx, mpy, now_ms, None, None)',
                   'self._enter_descend(_sel_tx, _sel_ty, mpx, mpy, now_ms)']:
        assert needle in s, '选台新块缺接线: %s' % needle
    ast.parse(s)
    print('[断言] 全部通过')

    if leftovers:
        print('[注意] 仍有注释残留, 本次不写盘, 先补注释再跑')
        sys.exit(2)
    _has_bom = io.open(PATH, 'rb').read(3) == b'\xef\xbb\xbf'
    _enc = 'utf-8-sig' if _has_bom else 'utf-8'
    io.open(PATH, 'w', encoding=_enc, newline='').write(s)
    print('[写盘] 完成(encoding=%s, LF)' % _enc)


if __name__ == '__main__':
    try:
        main()
    except AssertionError as ex:
        print('[断言失败]', ex)
        sys.exit(1)
