# -*- coding: utf-8 -*-
"""第一步：删除主循环调用和蒙板绘制（让锁光点功能不生效，框不显示）"""
filepath = r"C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py"
with open(filepath, "r", encoding="utf-8") as f:
    lines = f.readlines()

# 要删除的行号范围（1-based，包含两端）
ranges = [
    (8502, 8518),   # 主循环：镜头检测+光点锁定
    (8520, 8536),   # 主循环：偏移分析日志
    (5771, 5791),   # 蒙板1：三个检测框绘制+注释
    (5865, 5886),   # 蒙板2：人物绿框+映射光点
    (4490, 4490),   # 小地图：绿框绘制调用
    (3935, 3945),   # 小地图鼠标事件：蓝框点击处理
    (3855, 3862),   # F4校准热键
]

# 合并范围
ranges.sort()
merged = []
for start, end in ranges:
    if merged and start <= merged[-1][1] + 1:
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    else:
        merged.append((start, end))

# 从后往前删
removed_count = 0
for start, end in reversed(merged):
    del lines[start-1:end]
    removed_count += end - start + 1

with open(filepath, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("第一步完成，删除%d行" % removed_count)
print("范围：%s" % merged)
