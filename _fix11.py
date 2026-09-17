lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找"if not has_target:"这一行
for i in range(len(lines)):
    if 'if not has_target:' in lines[i] and '# === 完全无目标' in lines[i-1]:
        print('找到位置:', i+1)
        # 在后面加发呆诊断日志
        new_lines = lines[:i+1] + [
            '            # 【发呆诊断·用户2026-09-16】打印发呆时为什么has_target为False\n',
            '            _add_log("[发呆诊断] 无目标: 怪数=%d 人物位置=%s (怪空或人空)" % (\n',
            '                len(self._monsters), self._player_screen_pos))\n'
        ] + lines[i+1:]
        lines = new_lines
        break

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('修改完成')
