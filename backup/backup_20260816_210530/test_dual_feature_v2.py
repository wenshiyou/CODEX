"""
双特征点定位测试 v2
左上："小地图"文字模板匹配 + 信息栏偏移
右下：蓝色圆弧模板匹配 + 蓝色颜色检测辅助
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
print("Title tpl: %dx%d, Arc tpl: %dx%d" % (tw, th, aw, ah))

frame = cv2.imread("debug_detect.png")
fh, fw = frame.shape[:2]

# ===== 左上：找"小地图"文字 =====
roi_title = frame[0:120, 0:300]
res_title = cv2.matchTemplate(roi_title, title_tpl, cv2.TM_CCOEFF_NORMED)
_, max_val, _, max_loc = cv2.minMaxLoc(res_title)
title_x, title_y = max_loc
print("Title match: val=%.3f at (%d,%d)" % (max_val, title_x, title_y))

# 信息栏高度偏移（"小地图"文字下方还有地图名称栏）
INFO_BAR_H = 24
content_left = title_x
content_top = title_y + th + INFO_BAR_H
print("Content top-left: (%d, %d)  [title_y+%d+%d]" % (content_left, content_top, th, INFO_BAR_H))

# ===== 右下：蓝色圆弧 + 颜色检测 =====
# 先在预估区域做模板匹配
arc_x1 = max(0, content_left + 120)
arc_y1 = max(0, content_top + 120)
arc_x2 = min(fw, content_left + 260)
arc_y2 = min(fh, content_top + 280)
roi_arc = frame[arc_y1:arc_y2, arc_x1:arc_x2]
res_arc = cv2.matchTemplate(roi_arc, arc_tpl, cv2.TM_CCOEFF_NORMED)
_, max_val_arc, _, max_loc_arc = cv2.minMaxLoc(res_arc)
arc_x = arc_x1 + max_loc_arc[0]
arc_y = arc_y1 + max_loc_arc[1]
print("Arc template match: val=%.3f at (%d,%d)" % (max_val_arc, arc_x, arc_y))

# 蓝色颜色检测：在圆弧附近找最右下的蓝色像素
hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
# 蓝色范围
lower_blue = np.array([90, 80, 80])
upper_blue = np.array([130, 255, 255])
blue_mask = cv2.inRange(hsv, lower_blue, upper_blue)

# 在右下角搜索区域内找蓝色像素的最右下点
search_x1 = max(0, content_left + 100)
search_y1 = max(0, content_top + 100)
search_x2 = min(fw, content_left + 250)
search_y2 = min(fh, content_top + 280)
search_roi = blue_mask[search_y1:search_y2, search_x1:search_x2]
ys, xs = np.where(search_roi > 0)
if len(xs) > 0:
    # 最右下的蓝色点
    color_right = search_x1 + xs.max()
    color_bottom = search_y1 + ys.max()
    print("Blue color bottom-right: (%d, %d), %d blue pixels" % (color_right, color_bottom, len(xs)))
else:
    color_right = color_bottom = None
    print("No blue pixels found in search region")

# 综合：用模板匹配和颜色检测的结果，取更合理的
# 圆弧右下角应该是小地图的右下角
if color_right is not None:
    # 颜色检测的最右下蓝色点通常就是边框右下角
    content_right = color_right
    content_bottom = color_bottom
    print("Using color detection for bottom-right")
else:
    content_right = arc_x + aw
    content_bottom = arc_y + ah
    print("Using template match for bottom-right")

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
print("\n=== Result ===")
print("minimap: %dx%d at (%d,%d)" % (minimap_rect["width"], minimap_rect["height"], minimap_rect["left"], minimap_rect["top"]))
print("map_area: %dx%d at (%d,%d)" % (map_area_rect["width"], map_area_rect["height"], map_area_rect["left"], map_area_rect["top"]))

# ===== 可视化 =====
dbg = frame.copy()
cv2.rectangle(dbg, (title_x, title_y), (title_x + tw, title_y + th), (0, 0, 255), 1)
cv2.rectangle(dbg, (arc_x, arc_y), (arc_x + aw, arc_y + ah), (0, 255, 255), 1)
if color_right is not None:
    cv2.circle(dbg, (color_right, color_bottom), 4, (255, 0, 255), -1)
cv2.rectangle(dbg, (minimap_rect["left"], minimap_rect["top"]),
              (minimap_rect["left"] + minimap_rect["width"], minimap_rect["top"] + minimap_rect["height"]),
              (255, 0, 0), 1)
cv2.rectangle(dbg, (map_area_rect["left"], map_area_rect["top"]),
              (map_area_rect["left"] + map_area_rect["width"], map_area_rect["top"] + map_area_rect["height"]),
              (0, 255, 0), 2)
cv2.imwrite("debug_dual_v2.png", dbg)

map_crop = frame[map_area_rect["top"]:map_area_rect["top"] + map_area_rect["height"],
                 map_area_rect["left"]:map_area_rect["left"] + map_area_rect["width"]]
cv2.imwrite("debug_dual_map_v2.png", map_crop)
print("Saved debug_dual_v2.png and debug_dual_map_v2.png")
