lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找调用_combat_tick的那一段
for i in range(len(lines)):
    if 'if not _aux_busy and not _hard_reset_done:' in lines[i] and 'self._combat_tick()' in lines[i+1]:
        print('找到位置:', i+1)
        # 在else里加日志
        lines.insert(i+2, '                else:\n')
        lines.insert(i+3, '                    _debug_log("[打怪检查] 不打怪: _aux_busy=%s _hard_reset_done=%s (_fall_returning=%s _unblocking=%s _bound_pulling=%s)" % (\n')
        lines.insert(i+4, '                        _aux_busy, _hard_reset_done, _fall_returning, _unblocking, _bound_pulling))\n')
        break

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('修改完成')
