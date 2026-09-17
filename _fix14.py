lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找发呆监控日志那三行
new_lines = []
i = 0
while i < len(lines):
    if '_add_log("[发呆监控] 发呆%d秒 | %s | 怪数=%d 人物=%s 锁定怪=%s 锁定梯=%s" % (' in lines[i]:
        # 跳过这三行，替换成一行
        new_lines.append('                _add_log("[发呆监控] 发呆%d秒,当前状态: %s" % (_idle_s, _reason))\n')
        i += 3
        continue
    new_lines.append(lines[i])
    i += 1

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(new_lines)
print('回滚完成')
