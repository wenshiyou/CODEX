# -*- coding: utf-8 -*-
"""梯子特征(随方案)+登顶三背景点 离线算法测试(不启动GUI,object.__new__裸实例)。"""
import numpy as np
import cv2
import maple_route_ui as M

PASS, FAIL = 0, 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print("[PASS]", name, extra)
    else:
        FAIL += 1; print("[FAIL]", name, extra)

bot = object.__new__(M.MinimapRouteRecorder)
bot._monsters = []
bot._ladder_templates = []
bot._ladder_tpl_sim = M.LADDER_TPL_DEFAULT_SIM
bot._climb_box_prev = [None, None, None]
bot._climb_box_centers = [None, None, None]

FW, FH = 1276, 749
hs = M.CLIMB_BOX_SIZE // 2
yT = M.DETECT_TOP_MARGIN + hs
yB = FH - M.DETECT_BOTTOM_MARGIN - hs

def boxes_in_screen(centers):
    for cx, cy in centers:
        if not (hs <= cx <= FW - hs and yT <= cy <= yB):
            return False
    return True

# ---- 1. 选点:中心/最右/最左/最上 都不出屏 ----
c_mid = bot._pick_climb_boxes((638, 374), FH, FW)
check("center 3 points", len(c_mid) == 3, str(c_mid))
check("center in-screen", boxes_in_screen(c_mid))
sep_ok = all(abs(c_mid[i][0]-c_mid[j][0])+abs(c_mid[i][1]-c_mid[j][1]) >= M.CLIMB_BOX_SEP_MIN
             for i in range(3) for j in range(i+1, 3))
check("center separated", sep_ok, str([(c_mid[i],c_mid[j]) for i in range(3) for j in range(i+1,3)]))

c_right = bot._pick_climb_boxes((1270, 374), FH, FW)
check("right-edge 3 points", len(c_right) == 3, str(c_right))
check("right-edge in-screen(no out-of-screen)", boxes_in_screen(c_right), str(c_right))

c_left = bot._pick_climb_boxes((6, 374), FH, FW)
check("left-edge in-screen", boxes_in_screen(c_left), str(c_left))

c_top = bot._pick_climb_boxes((638, 35), FH, FW)
check("top-edge in-screen", boxes_in_screen(c_top), str(c_top))

c_corner = bot._pick_climb_boxes((1270, 35), FH, FW)
check("right-top corner in-screen", boxes_in_screen(c_corner), str(c_corner))

# ---- 2. 三背景点静止/运动判定 ----
def reset_box():
    bot._climb_box_prev = [None, None, None]
    bot._climb_box_centers = [None, None, None]

# 2a. 完全静态:首帧建基准,第二帧全静
reset_box()
still_img = np.full((FH, FW, 3), 100, np.uint8)
_ = bot._climb_boxes_still(still_img, c_mid)                 # 第一帧只建基准
ns, nv = bot._climb_boxes_still(still_img, c_mid)            # 第二帧同样画面
check("static: 3 still/3 valid", ns == 3 and nv == 3, "still=%d valid=%d" % (ns, nv))

# 2b. 纵向滚动(纹理整体向下平移3px=人物真在上下爬):三框都"垂直在动"→0静止(用户2026-09-10方向分解)
_rng = np.random.RandomState(0)
_tex = _rng.randint(40, 210, size=(FH, FW, 3)).astype(np.uint8)  # 丰富纹理,行投影有上下起伏
reset_box()
_ = bot._climb_boxes_still(_tex, c_mid)
_scroll = np.full_like(_tex, 40); _scroll[3:, :] = _tex[:-3, :]   # 内容下移3px=镜头纵向滚动
ns2, nv2 = bot._climb_boxes_still(_scroll, c_mid)
check("vertical-scroll: 0 still(真在爬)", ns2 == 0 and nv2 == 3, "still=%d valid=%d" % (ns2, nv2))

# 2d. 横向被撞(纹理整体向右平移3px;行投影=跨列平均,对横移不敏感→垂直方向没动):三框全"垂直静止",到顶照常触发
reset_box()
_ = bot._climb_boxes_still(_tex, c_mid)
_side = np.full_like(_tex, 40); _side[:, 3:] = _tex[:, :-3]       # 内容右移3px=到顶被怪左右撞
nsb, nvb = bot._climb_boxes_still(_side, c_mid)
check("horizontal-hit: 3 still(被撞不挡到顶)", nsb == 3 and nvb == 3, "still=%d valid=%d" % (nsb, nvb))

# 2c. 两动一静(左下保持):至少1静止 -> 满足"任一静即静"
reset_box()
base = np.full((FH, FW, 3), 80, np.uint8)
# 在右上/右下区域画变化块,左下(c_mid[2])区域保持
nxt = base.copy()
for (cx, cy) in (c_mid[0], c_mid[1]):
    cv2.rectangle(nxt, (cx-hs, cy-hs), (cx+hs, cy+hs), (200, 200, 200), -1)
_ = bot._climb_boxes_still(base, c_mid)
ns3, nv3 = bot._climb_boxes_still(nxt, c_mid)
check("2 moving 1 still: still>=1", ns3 >= 1, "still=%d valid=%d (左下应静止)" % (ns3, nv3))

# ---- 3. 定向ROI梯子X匹配:怪在右只搜右,怪在左只搜左 ----
def make_scene_with_rope(rope_cx, rope_cy):
    """均匀灰背景 + 一根有竖纹的绳索竖条(宽12 高90)。返回(frame, 模板)。"""
    img = np.full((FH, FW, 3), 90, np.uint8)
    x1, y1 = rope_cx - 6, rope_cy - 45
    cv2.rectangle(img, (x1, y1), (x1+12, y1+90), (60, 60, 60), -1)
    cv2.line(img, (rope_cx, y1), (rope_cx, y1+90), (220, 220, 220), 2)  # 中间亮竖线
    tpl = img[y1:y1+90, x1:x1+12].copy()
    return img, tpl

# 3a. 怪在右,绳索在人物右侧120px、上方100px(在上行头顶窗内) -> 匹配回X
ppx, ppy = 500, 400
rope_x, rope_y = ppx + 120, ppy - 100
scene, tpl = make_scene_with_rope(rope_x, rope_y)
bot._ladder_templates = [{"id": 0, "img": tpl, "width": 12, "height": 90}]
got = bot._match_ladder_screen_x(scene, (ppx, ppy), 1, monster_x=ppx + 300)  # 怪在右
check("monster-right: match rope on right", got is not None and abs(got - rope_x) <= 3,
      "got=%s expect~%d" % (got, rope_x))

# 3b. 怪在左,但绳索在人物右侧(右侧不该搜) -> None
got2 = bot._match_ladder_screen_x(scene, (ppx, ppy), 1, monster_x=ppx - 300)
check("monster-left: ignore rope on right", got2 is None, "got=%s" % got2)

# 3c. 怪在左,绳索在人物左侧 -> 能找到
rope_x3, rope_y3 = ppx - 120, ppy - 100
scene3, tpl3 = make_scene_with_rope(rope_x3, rope_y3)
bot._ladder_templates = [{"id": 0, "img": tpl3, "width": 12, "height": 90}]
got3 = bot._match_ladder_screen_x(scene3, (ppx, ppy), 1, monster_x=ppx - 300)
check("monster-left: match rope on left", got3 is not None and abs(got3 - rope_x3) <= 3,
      "got=%s expect~%d" % (got3, rope_x3))

# 3d. 下行:绳索在脚下(+20~+150)能找到,在头顶(下行不搜)找不到
rope_dx, rope_dy = ppx + 100, ppy + 100
sceneD, tplD = make_scene_with_rope(rope_dx, rope_dy)
bot._ladder_templates = [{"id": 0, "img": tplD, "width": 12, "height": 90}]
gotD = bot._match_ladder_screen_x(sceneD, (ppx, ppy), -1, monster_x=ppx + 300)
check("down: match rope below", gotD is not None and abs(gotD - rope_dx) <= 3, "got=%s" % gotD)
rope_up_x, rope_up_y = ppx + 100, ppy - 100
sceneU, tplU = make_scene_with_rope(rope_up_x, rope_up_y)
bot._ladder_templates = [{"id": 0, "img": tplU, "width": 12, "height": 90}]
gotU = bot._match_ladder_screen_x(sceneU, (ppx, ppy), -1, monster_x=ppx + 300)
check("down: ignore rope above", gotU is None, "got=%s(下行不搜头顶)" % gotU)

# ---- 4. 三点折线选梯【怪→梯→人】:怪发出/人结束,X总程最短(用户2026-09-11;签名 mon 在前) ----
# 4a. 怪在左:人怪之间的梯(红线短)胜出,人外侧绕远梯(蓝线)淘汰
rows = bot._pick_ladder_by_triangle(200, 350, [(500, 350), (900, 350)], 800, 400, 1)
check("triangle: between-ladder wins over detour", rows and rows[0][1] == 500, str([(r[1], r[0]) for r in rows]))
# 4b. 人怪之间多把梯、总程相同→tie-break先比【怪→梯】近(怪发出,先连对怪层),故选离怪近的400而非离人近的600
rows_b = bot._pick_ladder_by_triangle(200, 350, [(400, 350), (600, 350)], 800, 400, 1)
check("triangle: tie -> nearer to MONSTER(monster-first)", rows_b and rows_b[0][1] == 400,
      str([(r[1], 'm2l=%d' % r[4], 'l2p=%d' % r[5]) for r in rows_b]))
# 4c. 上行滤掉脚下梯(wy>psy+40),只留头顶梯
rows_c = bot._pick_ladder_by_triangle(300, 300, [(550, 300), (600, 500)], 800, 400, 1)
check("triangle: up filters below-feet ladder", len(rows_c) == 1 and rows_c[0][1] == 550, str([r[1] for r in rows_c]))
# 4d. 下行滤掉头顶梯(wy<psy-40),只留脚下梯
rows_d = bot._pick_ladder_by_triangle(800, 500, [(500, 500), (520, 300)], 300, 400, -1)
check("triangle: down filters above-head ladder", len(rows_d) == 1 and rows_d[0][1] == 500, str([r[1] for r in rows_d]))
# 4e. 怪在右:中间梯胜出、左侧绕远淘汰
rows_e = bot._pick_ladder_by_triangle(800, 350, [(500, 350), (100, 350)], 300, 400, 1)
check("triangle: monster-right between wins", rows_e and rows_e[0][1] == 500, str([r[1] for r in rows_e]))
# 4f. 全部被方向滤掉→空列表(回落到倍率兜底,不崩)
rows_f = bot._pick_ladder_by_triangle(800, 200, [(500, 200)], 300, 400, -1)
check("triangle: no candidate -> []", rows_f == [], str(rows_f))

print("\n==== RESULT: PASS=%d FAIL=%d ====" % (PASS, FAIL))
