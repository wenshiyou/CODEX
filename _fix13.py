lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找发呆监控日志那一行
for i in range(len(lines)):
    if '_add_log("[发呆监控] 发呆%d秒,当前状态: %s" % (_idle_s, _reason))' in lines[i]:
        print('找到位置:', i+1)
        # 改成打印更多信息
        lines[i] = '                _add_log("[发呆监控] 发呆%d秒 | %s | 怪数=%d 人物=%s 锁定怪=%s 锁定梯=%s" % (\n'
        lines.insert(i+1, '                    _idle_s, _reason, len(self._monsters), self._player_screen_pos,\n')
        lines.insert(i+2, '                    self._combat_locked_target, self._locked_ladder))\n')
        break

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('修改完成')
