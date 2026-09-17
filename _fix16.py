lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找_combat_tick函数开头
for i in range(len(lines)):
    if 'def _combat_tick(self):' in lines[i]:
        print('找到位置:', i+1)
        # 在第一个return前面加日志
        for j in range(i, i+10):
            if 'if not self._running or self.hwnd is None:' in lines[j]:
                lines.insert(j+1, '            _debug_log("[打怪检查] 不打怪: running=%s hwnd=%s" % (self._running, self.hwnd))\n')
                break
        break

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('修改完成')
