lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()
# 在17613行（_dl = combat_logic.combat_step）前面插入
insert_pos = 17612  # 0-indexed，在第17613行前面插入
new_lines = '''
        # 【根因修复】锁定怪不在当前怪列表里=死了/跑了，直接清锁换目标
        # 不管范围内还是范围外，只要不在怪列表里就drop，不打空气
        if self._combat_locked_target is not None:
            _ltx, _lty = self._combat_locked_target
            _still_in_list = False
            for _m in _combat_mons:
                _mcx = (_m[0] + _m[2]) // 2
                _mcy = _m[3]
                if abs(_mcx - _ltx) < 30 and abs(_mcy - _lty) < 30:
                    _still_in_list = True
                    break
            if not _still_in_list:
                # 锁定怪不在列表里，直接清锁
                self._combat_locked_target = None
                self._combat_target_hp_confirmed = False
                self._combat_gone_frames = 0
                self._combat_target_lock_time = 0
                self._debug_log("[锁怪清仓] 锁定怪不在列表里，直接清锁换目标")
'''
lines.insert(insert_pos, new_lines)
open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('插入完成')
