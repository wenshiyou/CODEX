lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找combat_step调用的位置
combat_step_line = None
for i, line in enumerate(lines):
    if '_dl = combat_logic.combat_step(' in line:
        combat_step_line = i
        break

print(f"combat_step在第{combat_step_line+1}行")

# 在combat_step前面插入锁怪检查和根因修复
insert_lines = '''
        # 【调试】锁定怪是否在当前怪列表里——每0.6秒
        if not hasattr(self, '_lock_in_list_last') or now - self._lock_in_list_last > 600:
            self._lock_in_list_last = now
            _lt = self._combat_locked_target
            if _lt:
                _lx, _ly = _lt
                _in_list = False
                for _m in _combat_mons:
                    _mcx = (_m[0] + _m[2]) // 2
                    _mcy = _m[3]
                    if abs(_mcx - _lx) < 30 and abs(_mcy - _ly) < 30:
                        _in_list = True
                        break
                _debug_log("[锁怪检查] 锁定=(%d,%d) 在怪列表=%s 怪列表总数=%d" % (_lx, _ly, _in_list, len(_combat_mons)))

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
                _debug_log("[锁怪清仓] 锁定怪不在列表里，直接清锁换目标")

'''

lines.insert(combat_step_line, insert_lines)
open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('插入完成')
