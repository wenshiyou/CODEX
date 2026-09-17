lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找方案三的代码
for i in range(len(lines)):
    if '# 打怪距离计算用一秒最低Y（地面值，过滤起跳峰值），上梯检测仍用原始Y' in lines[i]:
        print('找到位置:', i+1)
        # 替换成方案二
        lines[i] = '        # 打怪距离计算用Y变化率平滑（方案二·用户2026-09-16）：检测Y变化率，跳起来了就用上一帧地面Y；上梯检测仍用原始Y\n'
        lines[i+1] = '        _climb_now = getattr(self, \'_climb_state\', \'none\')\n'
        lines[i+2] = '        if _climb_now in (\'climbing\', \'to_ladder\', \'jump_up\'):\n'
        lines[i+3] = '            # 上梯子时用原始Y，不用平滑\n'
        lines[i+4] = '            py_layer = py\n'
        lines[i+5] = '        else:\n'
        lines[i+6] = '            # 方案二：检测Y变化率\n'
        lines[i+7] = '            _y_last = getattr(self, \'_screen_y_last_raw\', None)\n'
        lines[i+8] = '            if _y_last is not None and abs(py - _y_last) > 10:\n'
        lines[i+9] = '                # Y变化超过10px/帧，说明跳起来了，用上一帧地面Y\n'
        lines[i+10] = '                py_layer = getattr(self, \'_screen_y_ground\', py)\n'
        lines[i+11] = '            else:\n'
        lines[i+12] = '                # Y变化小，正常走路，用当前Y\n'
        lines[i+13] = '                py_layer = py\n'
        lines[i+14] = '            # 更新上一帧原始Y和地面Y\n'
        lines[i+15] = '            self._screen_y_last_raw = py\n'
        lines[i+16] = '            self._screen_y_ground = py_layer\n'
        break

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('修改完成')
