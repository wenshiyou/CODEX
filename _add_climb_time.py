import time
lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 1. 开始录梯子时，记录开始时间
for i in range(len(lines)):
    if 'self.recording_ladder = True' in lines[i] and 'self.ladder_points = []' in lines[i+1]:
        print('找到开始录梯位置:', i+1)
        # 在print前插入记录开始时间
        lines.insert(i+2, '                self._ladder_record_start = time.time() * 1000  # 记录录梯开始时间，用于计算爬梯时长\n')
        break

# 2. 结束录梯子时，计算时间差，加到new_ld里
for i in range(len(lines)):
    if 'nl = self.extract_ladder(self.ladder_points)' in lines[i]:
        print('找到结束录梯位置:', i+1)
        # 找后面的new_ld = nl[0]
        for j in range(i, i+10):
            if 'new_ld = nl[0]' in lines[j]:
                print('找到new_ld行:', j+1)
                # 在new_ld = nl[0]后面插入计算爬梯时间
                insert_lines = [
                    '                    # 计算爬梯时长，保存到梯子数据里，以后自动爬时用这个时间+2秒做兜底\n',
                    '                    _climb_time_ms = (time.time() * 1000) - getattr(self, \'_ladder_record_start\', 0)\n',
                    '                    new_ld["climb_time_ms"] = int(_climb_time_ms)\n',
                    '                    _debug_log("[梯录] 爬梯时长=%dms" % int(_climb_time_ms))\n',
                ]
                lines[j+1:j+1] = insert_lines
                break
        break

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('修改完成')
