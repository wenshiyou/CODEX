"""
三特征点定位测试 v3
左边界 = "小地图"文字左侧
右边界 = "大地图"文字右侧
上边界 = "小地图"文字下方
下边界 = 从上边界向下350px内找右下角蓝色圆弧
"""
import cv2
import numpy as np
import os
import sys

sys.stdout.reconfigure(line_buffering=True)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

minimap_tpl = cv2.imread("data/templates/minimap_title.png")  # 小地图 38x14
bigmap_tpl = cv2.imread("data/templates/bigmap_title.png")    # 大地图 36x11
arc_tpl = cv2.imread("data/templates/minimap_blue_arc.png")   # 蓝色圆弧 8x9
mh, mw = minimap_tpl.shape[:2]
bh, bw = bigmap_tpl.shape[:2]
ah, aw = arc_tpl.shape[:2]
print("Templates: 小地图%dx%d 大地图%dx%d 圆弧%dx%d" % (mw, mh, bw, bh, aw, ah))

frame = cv2.imread("debug_detect.png")
fh, fw = frame.shape[:2]
print("Frame: %dx%d" % (fw, fh))

# ===== 1. 找"小地图"文字 =====
roi = frame[0:120, 0:300]
res = cv2.matchTemplate(roi, minimap_tpl, cv2.TM_CCOEFF_NORMED)
_, val_m, _, loc_m = cv2.minMaxLoc(res)
mini_x, mini_y = loc_m
print("小地图: val=%.3f at (%d,%d)" % (val_m, mini_x, mini_y))

# ===== 2. 找"大地图"文字 =====
# 在小地图右侧搜索
roi2_x1 = mini_x + mw
roi2_x2 = min(fw, mini_x + 200)
roi2 = frame[mini_y - 5:mini_y + mh + 10, roi2_x1:roi2_x2]
res2 = cv2.matchTemplate(roi2, bigmap_tpl, cv2.TM_CCOEFF_NORMED)
_, val_b, _, loc_b = cv2.minMaxLoc(res2)
big_x = roi2_x1 + loc_b[0]
big_y = mini_y - 5 + loc_b[1]
print("大地图: val=%.3f at (%d,%d)" % (val_b, big_x, big_y))

# ===== 3. 计算边界 =====
left = mini_x                    # 左边界 = 小地图文字左侧
right = big_x + bw               # 右边界 = 大地图文字右侧
top = mini_y + mh                # 上边界 = 小地图文字下方
print("\n边界: left=%d right=%d top=%d" % (left, right, top))
print("宽度: %d" % (right - left))

# ===== 4. 在 top 向下350px范围内找右下角圆弧 =====
arc_search_y1 = top
arc_search_y2 = min(fh, top + 350)
arc_search_x1 = max(0, right - 60)   # 在右边界附近搜索
arc_search_x2 = min(fw, right + 20)
roi_arc = frame[arc_search_y1:arc_search_y2, arc_search_x1:arc_search_x2]
res_arc = cv2.matchTemplate(roi_arc, arc_tpl, cv2.TM_CCOEFF_NORMED)
_, val_a, _, loc_a = cv2.minMaxLoc(res_arc)
arc_x = arc_search_x1 + loc_a[0]
arc_y = arc_search_y1 + loc_a[1]
bottom = arc_y + ah
print("圆弧: val=%.3f at (%d,%d), bottom=%d" % (val_a, arc_x, arc_y, bottom))

# ===== 5. 最终区域 =====
minimap_rect = {
    "left": left, "top": mini_y,
    "width": right - left, "height": bottom - mini_y
}
# 地图内容区：去掉标题栏（小地图文字下方到地图内容）
TITLE_PAD = 30  # 信息栏高度（图标+地图名称）
map_area_rect = {
    "left": left + 3,
    "top": top + TITLE_PAD,
    "width": right - left - 6,
    "height": bottom - top - TITLE_PAD - 3
}
print("\n=== 结果 ===")
print("minimap: %dx%d at (%d,%d)" % (minimap_rect["width"], minimap_rect["height"], minimap_rect["left"], minimap_rect["top"]))
print("map_area: %dx%d at (%d,%d)" % (map_area_rect["width"], map_area_rect["height"], map_area_rect["left"], map_area_rect["top"]))

# ===== 可视化 =====
dbg = frame.copy()
# 小地图文字框（红）
cv2.rectangle(dbg, (mini_x, mini_y), (mini_x + mw, mini_y + mh), (0, 0, 255), 1)
# 大地图文字框（橙）
cv2.rectangle(dbg, (big_x, big_y), (big_x + bw, big_y + bh), (0, 165, 255), 1)
# 圆弧框（黄）
cv2.rectangle(dbg, (arc_x, arc_y), (arc_x + aw, arc_y + ah), (0, 255, 255), 1)
# 外框（蓝）
cv2.rectangle(dbg, (minimap_rect["left"], minimap_rect["top"]),
              (minimap_rect["left"] + minimap_rect["width"], minimap_rect["top"] + minimap_rect["height"]),
              (255, 0, 0), 1)
# 内容区（绿）
cv2.rectangle(dbg, (map_area_rect["left"], map_area_rect["top"]),
              (map_area_rect["left"] + map_area_rect["width"], map_area_rect["top"] + map_area_rect["height"]),
              (0, 255, 0), 2)
# 350px搜索范围线
cv2.line(dbg, (left, top + 350), (right, top + 350), (255, 0, 255), 1)
cv2.putText(dbg, "350px search range", (left, top + 345), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 255), 1)

cv2.imwrite("debug_triple_v3.png", dbg)

map_crop = frame[map_area_rect["top"]:map_area_rect["top"] + map_area_rect["height"],
                 map_area_rect["left"]:map_area_rect["left"] + map_area_rect["width"]]
cv2.imwrite("debug_triple_map_v3.png", map_crop)
print("\nSaved debug_triple_v3.png and debug_triple_map_v3.png")
