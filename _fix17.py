lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 在拟人休息return前加日志
for i in range(len(lines)):
    if "if getattr(self, '_aux_enable_rest', True) and now < getattr(self, '_rest_until', 0):" in lines[i]:
        print('找到拟人休息位置:', i+1)
        lines.insert(i+3, '            _debug_log("[打怪检查] 不打怪: 拟人休息中, 还剩%.1f秒" % ((self._rest_until - now) / 1000.0))\n')
        break

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('修改完成')
