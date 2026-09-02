# -*- coding: utf-8 -*-
"""删除锁光点整套功能：三点检测 + 人物绿框(蒙板2) + 小地图绿框
保留：人物特征黄点、药品框、怪物框、输入框、倍率、平台录制等
"""
import re

filepath = r"C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py"
with open(filepath, "r", encoding="utf-8") as f:
    lines = f.readlines()

# 记录删除的行号（1-based）
removed = []

# ========== 第一步：删除主循环中的调用 ==========
# 1. 删除 self._detect_camera_motion(_frame) 调用
# 2. 删除 self._player_lock_pos = self.lock_screen_from_dot() 相关块
# 3. 删除 _detect_camera_motion 调用后的日志

i = 0
new_lines = []
while i < len(lines):
    line = lines[i]

    # 删除 _detect_camera_motion 调用
    if "self._detect_camera_motion(_frame)" in line:
        removed.append(i+1)
        # 检查前后是否有相关的日志/条件
        # 往前看是否有 if 条件包裹
        j = i - 1
        while j >= 0 and (lines[j].strip().startswith("#") or lines[j].strip() == ""):
            j -= 1
        # 往后看是否有相关的print/debug
        k = i + 1
        while k < len(lines) and ("镜头检测" in lines[k] or "_bg_motion_count" in lines[k] or lines[k].strip() == ""):
            removed.append(k+1)
            k += 1
        i = k
        continue

    # 删除 _player_lock_pos = self.lock_screen_from_dot() 块
    if "self._player_lock_pos = self.lock_screen_from_dot()" in line:
        removed.append(i+1)
        # 往后看相关的日志/条件块
        k = i + 1
        while k < len(lines):
            if "光点锁定" in lines[k] or "_player_lock_pos" in lines[k] or "lock_screen" in lines[k] or lines[k].strip() == "":
                removed.append(k+1)
                k += 1
            else:
                break
        i = k
        continue

    # 删除蒙板2绘制人物绿框的块
    if "人物定位大框（绿色空心矩形" in line or "人物定位大框已移到第二个蒙板" in line:
        removed.append(i+1)
        k = i + 1
        while k < len(lines):
            if "_player_lock_pos" in lines[k] or "PLAYER_BOX" in lines[k] or "_lock_x" in lines[k] or "_lock_y" in lines[k] or "Rectangle(hdc2" in lines[k] or lines[k].strip() == "":
                removed.append(k+1)
                k += 1
            else:
                break
        i = k
        continue

    # 删除蒙板1绘制三个检测框的块
    if "镜头死区检测三个背景框" in line:
        removed.append(i+1)
        k = i + 1
        while k < len(lines):
            if "_bg_regions" in lines[k] or "_bg_motion_count" in lines[k] or "_bg_dragging" in lines[k] or "检测框" in lines[k] or "Rectangle(hdc" in lines[k] or "TextOut" in lines[k] or lines[k].strip() == "":
                removed.append(k+1)
                k += 1
            else:
                break
        i = k
        continue

    # 删除小地图绘制绿框的调用
    if "self._draw_blue_box(display)" in line:
        removed.append(i+1)
        i += 1
        continue

    # 删除小地图鼠标事件中的蓝框处理
    if "self._calibrating_blue_box and event == cv2.EVENT_LBUTTONDOWN" in line:
        removed.append(i+1)
        k = i + 1
        while k < len(lines) and ("_handle_blue_box_click" in lines[k] or "calibrating_blue_box" in lines[k]):
            removed.append(k+1)
            k += 1
        i = k
        continue

    # 删除F4蓝框校准热键
    if "_calibrating_blue_box" in line and ("F4" in line or "VK_F4" in line or "0x73" in line):
        removed.append(i+1)
        k = i + 1
        while k < len(lines) and ("_start_blue_box_calibration" in lines[k] or "_save_and_exit_blue_box" in lines[k] or "calibrating_blue_box" in lines[k]):
            removed.append(k+1)
            k += 1
        i = k
        continue

    # 删除主循环中的蓝框校准按键处理
    if "self._calibrating_blue_box:" in line and "_handle_blue_box_key" in lines[i+1] if i+1 < len(lines) else False:
        removed.append(i+1)
        removed.append(i+2)
        i += 2
        continue

    new_lines.append(line)
    i += 1

# 写回
with open(filepath, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("第一步完成：删除主循环调用和蒙板绘制")
print("删除行数：%d" % len(removed))
print("删除的行号：%s" % removed[:30])
