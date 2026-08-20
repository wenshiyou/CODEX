"""
从已有截图中裁剪"小地图"文字模板，用于双特征点定位
"""
import cv2
import numpy as np
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 从完整小地图截图中裁剪文字模板
src = cv2.imread("user_minimap_full.png")
if src is None:
    src = cv2.imread("user_full_minimap.png")

print("Source shape:", src.shape)

# "小地图"文字在左上角，裁剪一个稍大的区域
# 文字大约从 (2,2) 开始，宽约45，高约18
template = src[1:20, 2:52].copy()
cv2.imwrite("data/templates/minimap_title.png", template)
print("Template saved: data/templates/minimap_title.png, shape:", template.shape)

# 同时保存一个带标注的验证图
dbg = src.copy()
cv2.rectangle(dbg, (2, 1), (52, 20), (0, 0, 255), 1)
cv2.imwrite("debug_template_check.png", dbg)
print("Debug check saved: debug_template_check.png")
