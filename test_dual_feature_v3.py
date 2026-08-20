"""
双特征点定位测试 v3
左上："小地图"文字模板匹配 + 信息栏偏移
右下：蓝色圆弧模板匹配（主）+ 局部蓝色验证（辅）
"""
import cv2
import numpy as np
import os
import sys

sys.stdout.reconfigure(line_buffering=True)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

title_tpl = cv2.imread("data/templates/minimap_title.png")
arc_tpl = cv2.imread("data/templates/minimap_blue_arc.png")
th, tw = title_tpl.shape[:2]
ah, aw = arc_tpl.shape[:2]

frame = cv2.imread("debug_detect.png")
fh, fw = frame.shape[:2]

# ===== 左上：找"小地图"文字 =====
roi_title = frame[0:120, 0:300]
res_title = cv2.matchTemplate(roi_title, title_tpl, cv2.TM_CCOEFF_NORMED)
_, max_val, _, max_loc = cv2.minMaxLoc(res_title)
title_x, title_y = max_loc
print("Title: val=%.3f at (%d,%d)" % (max_val, title_x, title_y))

INFO_BAR_H = 24
content_left = title_x
content_top = title_y + th + INFO_BAR_H
print("Content top-left: (%d, %d)" % (content_left, content_top))

# ===== 右下：蓝色圆弧模板匹配 =====
# 小地图尺寸预估：宽约180-200，高约200-240
# 圆弧应该在 content_left+150 ~ content_left+220, content_top+130 ~ content_top+200
arc_x1 = max(0, content_left + 140)
arc_y1 = max(0, content_top + 120)
arc_x2 = min(fw, content_left + 230)
arc_y2 = min(fh, content_top + 220)
roi_arc = frame[arc_y1:arc_y2, arc_x1:arc_x2]
res_arc = cv2.matchTemplate(roi_arc, arc_tpl, cv2.TM_CCOEFF_NORMED)
_, max_val_arc, _, max_loc_arc = cv2.minMaxLoc(res_arc)
arc_x = arc_x1 + max_loc_arc[0]
arc_y = arc_y1 + max_loc_arc[1]
print("Arc: val=%.3f at (%d,%d), roi=(%d,%d,%d,%d)" % (
    max_val_arc, arc_x, arc_y, arc_x1, arc_y1, arc_x2, arc_y2))

# 圆弧右下角 = 小地图右下角
content_right = arc_x + aw
content_bottom = arc_y + ah
print("Content bottom-right: (%d, %d)" % (content_right, content_bottom))

# 合理性检查
map_w = content_right - content_left
map_h = content_bottom - content_top
print("Map size: %d x %d" % (map_w, map_h))

# 如果尺寸不合理（太小或太大），用默认值兜底
if map_w < 100 or map_w > 250 or map_h < 100 or map_h > 280:
    print("WARNING: size abnormal, using fallback")
    content_right = content_left + 180
    content_bottom = content_top + 170

# ===== 计算区域 =====
map_area_rect = {
    "left": content_left,
    "top": content_top,
    "width": content_right - content_left,
    "height": content_bottom - content_top
}
minimap_rect = {
    "left": title_x,
    "top": title_y,
    "width": content_right - title_x,
    "height": content_bottom - title_y
}
print("\nminimap: %dx%d at (%d,%d)" % (minimap_rect["width"], minimap_rect["height"], minimap_rect["left"], minimap_rect["top"]))
print("map_area: %dx%d at (%d,%d)" % (map_area_rect["width"], map_area_rect["height"], map_area_rect["left"], map_area_rect["top"]))

# ===== 可视化 =====
dbg = frame.copy()
cv2.rectangle(dbg, (title_x, title_y), (title_x + tw, title_y + th), (0, 0, 255), 1)
cv2.rectangle(dbg, (arc_x, arc_y), (arc_x + aw, arc_y + ah), (0, 255, 255), 2)
cv2.rectangle(dbg, (minimap_rect["left"], minimap_rect["top"]),
              (minimap_rect["left"] + minimap_rect["width"], minimap_rect["top"] + minimap_rect["height"]),
              (255, 0, 0), 1)
cv2.rectangle(dbg, (map_area_rect["left"], map_area_rect["top"]),
              (map_area_rect["left"] + map_area_rect["width"], map_area_rect["top"] + map_area_rect["height"]),
              (0, 255, 0), 2)
# 特征点
cv2.circle(dbg, (content_left, content_top), 3, (0, 0, 255), -1)
cv2.circle(dbg, (content_right, content_bottom), 3, (0, 255, 255), -1)
cv2.imwrite("debug_dual_v3.png", dbg)

map_crop = frame[map_area_rect["top"]:map_area_rect["top"] + map_area_rect["height"],
                 map_area_rect["left"]:map_area_rect["left"] + map_area_rect["width"]]
cv2.imwrite("debug_dual_map_v3.png", map_crop)
print("Saved debug_dual_v3.png and debug_dual_map_v3.png")
