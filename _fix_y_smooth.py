lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 1. 初始化改成方案2
for i in range(len(lines)):
    if 'self._screen_y_smooth_window = []  # [(时间戳ms, y), ...] 最近1秒' in lines[i]:
        print('找到初始化位置:', i+1)
        lines[i] = '        # 屏幕Y平滑缓冲（方案2·检测Y变化率·用户2026-09-16）：\n'
        lines.insert(i+1, '        # 打怪/选梯/边界用地面Y，过滤起跳峰值；上梯检测仍用原始Y\n')
        lines.insert(i+2, '        self._screen_y_last_raw = None      # 上一帧原始Y\n')
        lines.insert(i+3, '        self._screen_y_ground = None       # 当前地面Y（平滑后的值）\n')
        lines.insert(i+4, '        self._screen_y_jump_thresh = 10     # Y变化超过此阈值=跳起来了(px/帧)\n')
        # 删除原来的窗口长度行
        for j in range(i+5, i+8):
            if '_screen_y_smooth_window_ms' in lines[j]:
                del lines[j]
                break
        break

# 2. 打怪距离计算用地面Y
for i in range(len(lines)):
    if 'py_layer = min(y for _, y in self._screen_y_smooth_window)' in lines[i]:
        print('找到打怪距离计算位置:', i+1)
        lines[i] = '            py_layer = self._screen_y_ground if self._screen_y_ground is not None else py\n'
        break

# 3. 找压入缓冲的位置，改成方案2逻辑
for i in range(len(lines)):
    if 'self._screen_y_smooth_window.append((_now_ms, self._raw_char_pos[1]))' in lines[i]:
        print('找到压入缓冲位置:', i+1)
        # 替换这一段
        lines[i] = '                            # 方案2·检测Y变化率：判断是不是跳起来了\n'
        lines.insert(i+1, '                            _raw_y = self._raw_char_pos[1]\n')
        lines.insert(i+2, '                            if self._screen_y_last_raw is not None:\n')
        lines.insert(i+3, '                                _dy = abs(_raw_y - self._screen_y_last_raw)\n')
        lines.insert(i+4, '                                if _dy < self._screen_y_jump_thresh:\n')
        lines.insert(i+5, '                                    # Y变化小=正常走路，更新地面Y\n')
        lines.insert(i+6, '                                    self._screen_y_ground = _raw_y\n')
        lines.insert(i+7, '                                # Y变化大=跳起来了，地面Y保持不变，用上一帧地面Y\n')
        lines.insert(i+8, '                            else:\n')
        lines.insert(i+9, '                                # 第一帧，直接初始化\n')
        lines.insert(i+10, '                                self._screen_y_ground = _raw_y\n')
        lines.insert(i+11, '                            self._screen_y_last_raw = _raw_y\n')
        # 删除原来的清旧值代码
        for j in range(i+12, i+20):
            if 'while self._screen_y_smooth_window' in lines[j]:
                del lines[j]
                del lines[j]
                break
        break

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('修改完成')
