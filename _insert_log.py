lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()
# 在17664行（空怪诊断注释）前面插入
insert_pos = 17663  # 0-indexed，在第17664行前面插入
new_lines = '''
        # 【调试】锁定怪是否在当前怪列表里——每0.6秒
        if not hasattr(self, '_lock_in_list_last') or now - self._lock_in_list_last > 600:
            self._lock_in_list_last = now
            _lt = self._combat_locked_target
            if _lt:
                _lx, _ly = _lt
                _in_list = False
                for _m in self._monsters:
                    _mcx = (_m[0] + _m[2]) // 2
                    _mcy = _m[3]
                    if abs(_mcx - _lx) < 30 and abs(_mcy - _ly) < 30:
                        _in_list = True
                        break
                _debug_log("[锁怪检查] 锁定=(%d,%d) 在怪列表=%s 怪列表总数=%d" % (_lx, _ly, _in_list, len(self._monsters)))
'''
lines.insert(insert_pos, new_lines)
open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('插入完成')
