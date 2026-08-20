"""
双特征点定位测试脚本
左上："小地图"文字模板匹配
右下：蓝色圆弧模板匹配
用已有截图验证，不启动游戏
"""
import cv2
import numpy as np
import os
import sys

sys.stdout.reconfigure(line_buffering=True)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 加载模板
title_tpl = cv2.imread("data/templates/minimap_title.png")
arc_tpl = cv2.imread("data/templates/minimap_blue_arc.png")
print("Title template:", title_tpl.shape)
print("Arc template:", arc_tpl.shape)

th, tw = title_tpl.shape[:2]
ah, aw = arc_tpl.shape[:2]

# 用已有完整窗口截图测试
frame = cv2.imread("debug_detect.png")
if frame is None:
    print("ERROR: debug_detect.png not found")
    sys.exit(1)
fh, fw = frame.shape[:2]
print("Frame:", fw, "x", fh)

# ===== 左上：找"小地图"文字 =====
# 搜索区域：窗口左上角 0~300 x 0~100
roi_title = frame[0:100, 0:300]
res_title = cv2.matchTemplate(roi_title, title_tpl, cv2.TM_CCOEFF_NORMED)
_, max_val, _, max_loc = cv2.minMaxLoc(res_title)
print("Title match: max_val=%.3f loc=%s" % (max_val, max_loc))

title_x = max_loc[0]
title_y = max_loc[1]
# 文字左下角 = 地图内容区域左上角
content_left = title_x
content_top = title_y + th
print("Content top-left (from title bottom-left): (%d, %d)" % (content_left, content_top))

# ===== 右下：找蓝色圆弧 =====
# 搜索区域：从文字位置向右下扩展，小地图大约 200x250
# 圆弧应该在 content_left+150 ~ content_left+250, content_top+150 ~ content_top+280
arc_search_x1 = max(0, content_left + 100)
arc_search_y1 = max(0, content_top + 100)
arc_search_x2 = min(fw, content_left + 280)
arc_search_y2 = min(fh, content_top + 300)
roi_arc = frame[arc_search_y1:arc_search_y2, arc_search_x1:arc_search_x2]
res_arc = cv2.matchTemplate(roi_arc, arc_tpl, cv2.TM_CCOEFF_NORMED)
_, max_val_arc, _, max_loc_arc = cv2.minMaxLoc(res_arc)
print("Arc match: max_val=%.3f loc=%s (in roi)" % (max_val_arc, max_loc_arc))

arc_x = arc_search_x1 + max_loc_arc[0]
arc_y = arc_search_y1 + max_loc_arc[1]
# 圆弧右下角 = 小地图右下角
content_right = arc_x + aw
content_bottom = arc_y + ah
print("Content bottom-right (from arc bottom-right): (%d, %d)" % (content_right, content_bottom))

# ===== 计算最终区域 =====
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
print("minimap_rect:", minimap_rect)
print("map_area_rect:", map_area_rect)
print("Map size: %d x %d" % (map_area_rect["width"], map_area_rect["height"]))

# ===== 可视化验证 =====
dbg = frame.copy()
# 画文字模板匹配框（红色）
cv2.rectangle(dbg, (title_x, title_y), (title_x + tw, title_y + th), (0, 0, 255), 1)
# 画圆弧模板匹配框（黄色）
cv2.rectangle(dbg, (arc_x, arc_y), (arc_x + aw, arc_y + ah), (0, 255, 255), 1)
# 画小地图外框（蓝色）
cv2.rectangle(dbg, (minimap_rect["left"], minimap_rect["top"]),
              (minimap_rect["left"] + minimap_rect["width"], minimap_rect["top"] + minimap_rect["height"]),
              (255, 0, 0), 1)
# 画地图内容区（绿色）
cv2.rectangle(dbg, (map_area_rect["left"], map_area_rect["top"]),
              (map_area_rect["left"] + map_area_rect["width"], map_area_rect["top"] + map_area_rect["height"]),
              (0, 255, 0), 1)
# 标注两个特征点
cv2.circle(dbg, (content_left, content_top), 3, (0, 0, 255), -1)
cv2.circle(dbg, (content_right, content_bottom), 3, (0, 255, 255), -1)

cv2.imwrite("debug_dual_feature.png", dbg)
print("\nSaved debug_dual_feature.png")

# 裁剪出地图内容区看看
map_crop = frame[map_area_rect["top"]:map_area_rect["top"] + map_area_rect["height"],
                 map_area_rect["left"]:map_area_rect["left"] + map_area_rect["width"]]
cv2.imwrite("debug_dual_map.png", map_crop)
print("Saved debug_dual_map.png (map content crop)")
