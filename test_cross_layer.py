# -*- coding: utf-8 -*-
"""跨层改造单测：选梯逻辑(上下行筛选) + cross_candidates返回 + 边界滞回
运行：python test_cross_layer.py
"""
import sys
import types
import random

sys.path.insert(0, '.')
import combat_logic as cl

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] " + name)
    else:
        FAIL += 1
        print("[FAIL] " + name)


# ==========================================================================
# 一、_find_nearest_ladder 选梯逻辑（抽方法绑定到mock对象测试）
# ==========================================================================
def make_mock_bot(ladders, player_map_pos=None):
    """构造只含选梯所需属性的mock对象"""
    class MockBot:
        pass
    bot = MockBot()
    bot.ladders = ladders
    bot._player_map_pos = player_map_pos
    # 绑定 _find_nearest_ladder 方法（从源码复制逻辑，确保测的是真实逻辑）
    import maple_route_ui as mui
    bot._find_nearest_ladder = types.MethodType(mui.MinimapRouteRecorder._find_nearest_ladder, bot)
    return bot


# 梯子数据（小地图坐标：y_top<y_bottom，顶端Y小）
LADDERS = [
    {"x": 100, "y_top": 50, "y_bottom": 120},   # 梯1：顶端50，底端120
    {"x": 300, "y_top": 50, "y_bottom": 120},   # 梯2：同层，X=300（更近）
    {"x": 200, "y_top": 200, "y_bottom": 280},  # 梯3：顶端200（到不了上层50）
    {"x": 500, "y_top": 50, "y_bottom": 120},   # 梯4：同层，X=500（远）
]


def test_ladder_up_reach():
    """上行：人物在梯1下端下方15内（够得着），目标层Y=50（顶端≈目标层），选X最近的梯2"""
    bot = make_mock_bot(LADDERS, player_map_pos=(280, 130))  # 人在(280,130)，比梯底端120低10
    ld = bot._find_nearest_ladder(280, 130, target_y=50)  # 上行：目标层50
    check("上行:下端够得着+顶端≈目标层→选X最近的梯2(x=300)", ld is not None and ld["x"] == 300)


def test_ladder_up_top_not_match():
    """上行：梯3顶端200≠目标层50，被排除；只能选梯1/2/4中X最近的"""
    bot = make_mock_bot(LADDERS, player_map_pos=(190, 130))
    ld = bot._find_nearest_ladder(190, 130, target_y=50)
    # 梯3被排除，剩下梯1(x=100)、梯2(x=300)、梯4(x=500)，人在x=190，最近是梯1(差90)还是梯2(差110)→梯1
    check("上行:顶端不匹配的梯3被排除→选梯1(x=100)", ld is not None and ld["x"] == 100)


def test_ladder_up_bottom_not_reachable():
    """上行：人物比梯底端低30（>15直跳高度），够不着，返回None"""
    bot = make_mock_bot(LADDERS, player_map_pos=(280, 155))  # 比底端120低35
    ld = bot._find_nearest_ladder(280, 155, target_y=50)
    check("上行:下端够不着(低35>15)→返回None", ld is None)


def test_ladder_down():
    """下行：人物在梯1顶端上方15内（够得着），目标层Y=120（底端≈目标层），选X最近"""
    bot = make_mock_bot(LADDERS, player_map_pos=(280, 40))  # 人在(280,40)，比顶端50高10
    ld = bot._find_nearest_ladder(280, 40, target_y=120)  # 下行：目标层120
    check("下行:顶端够得着+底端≈目标层→选X最近的梯2(x=300)", ld is not None and ld["x"] == 300)


def test_ladder_down_bottom_not_match():
    """下行：梯3底端280≠目标层120，被排除"""
    bot = make_mock_bot(LADDERS, player_map_pos=(190, 40))
    ld = bot._find_nearest_ladder(190, 40, target_y=120)
    check("下行:底端不匹配的梯3被排除→选梯1(x=100)", ld is not None and ld["x"] == 100)


def test_ladder_down_ignore_bottom_match():
    """新规则(用户2026-09-09)：下行不要求梯子底端与目标层Y对齐——一把底端999≠目标120、但人够得着且离人最近的梯应被选中
    (旧逻辑按底端±1匹配会把它排除、改选梯2；新逻辑只看够得着+离人X最近)"""
    ladders = LADDERS + [{"x": 320, "y_top": 50, "y_bottom": 999}]  # 底端不对齐但纵向覆盖人(py=40)
    bot = make_mock_bot(ladders, player_map_pos=(315, 40))
    ld = bot._find_nearest_ladder(315, 40, target_y=120)  # 下行
    # 梯5(x=320,差5)比梯2(x=300,差15)更近,虽底端999≠120仍应选它
    check("下行:不看底端对齐,够得着且最近的梯(x=320)被选中", ld is not None and ld["x"] == 320)


def test_ladder_down_no_reachable_fallback():
    """新规则兜底：没有一把梯子当前够得着(人py=20高于所有梯ytop-15)时,放宽到离人X最近,保证选得出不返回None死等"""
    bot = make_mock_bot(LADDERS, player_map_pos=(310, 20))
    ld = bot._find_nearest_ladder(310, 20, target_y=120)  # 下行,全部not reachable
    # 全部够不着→放宽取离x=310最近=梯2(x=300,差10)
    check("下行:无够得着梯→放宽取离人最近梯2(x=300)不死等", ld is not None and ld["x"] == 300)


# ==========================================================================
# 二、combat_logic cross_candidates 返回
# ==========================================================================
def test_cross_candidates_returned():
    """cross状态时返回cross_candidates列表（供_try_platform_transition做屏幕→小地图转换）"""
    monsters = [
        (900, 100, 940, 140, 0.9),  # 远怪（X差600>far_range=500，跨层候选）
    ]
    # 人物在(300,300)，far_range=500，怪X=920差620>500→框外→cross
    d = cl.select_combat_target(
        px=300, py=300, monsters=monsters, selected_platforms=[],
        skill_range=150, far_range=500,
        target_cx=None, target_cy=None, target_alive=False,
        is_on_platform=lambda cx, cy: False,  # 怪不在同平台
        get_monster_platform=lambda cx, cy: None,
        probe_side=1, probe_switched=False, cur_cross=None,
        attack_y_up=60, attack_y_down=30, allow_cross=True,
    )
    check("cross状态返回", d['state'] == 'cross')
    check("cross_candidates非空", len(d.get('cross_candidates', [])) > 0)
    check("cross_candidates格式[(dist,cx,cy)]", d['cross_candidates'][0][1] == 920)


def test_cross_disabled_no_candidates():
    """allow_cross=False时框外怪不进cross，返回idle且cross_candidates为空"""
    monsters = [(900, 100, 940, 140, 0.9)]
    d = cl.select_combat_target(
        px=300, py=300, monsters=monsters, selected_platforms=[],
        skill_range=150, far_range=500,
        target_cx=None, target_cy=None, target_alive=False,
        is_on_platform=lambda cx, cy: False,
        get_monster_platform=lambda cx, cy: None,
        probe_side=1, probe_switched=False, cur_cross=None,
        attack_y_up=60, attack_y_down=30, allow_cross=False,
    )
    check("allow_cross=False→idle", d['state'] == 'idle')
    check("cross_candidates为空", len(d.get('cross_candidates', [])) == 0)


# ==========================================================================
# 三、_combat_at_locked_edge 边界滞回（mock测试）
# ==========================================================================
def make_edge_mock(player_x, x_range=(0, 200)):
    class MockBot:
        pass
    bot = MockBot()
    bot._player_map_pos = (player_x, 100)
    bot._locked_platform_x_range = lambda: x_range
    bot._get_current_platform = lambda: None
    import maple_route_ui as mui
    bot._combat_at_locked_edge = types.MethodType(mui.MinimapRouteRecorder._combat_at_locked_edge, bot)
    return bot


def test_edge_stop_before_boundary():
    """向右走：人物在x=199（离右边界200差1，在4~10随机余量内），返回True（停）"""
    random.seed(42)
    bot = make_edge_mock(player_x=199)
    result = bot._combat_at_locked_edge("right")
    check("向右:离边界1px→停(余量范围内)", result is True)


def test_edge_hard_guard():
    """硬保底：人物已超出右边界(x=205)，向右走绝对返回True"""
    bot = make_edge_mock(player_x=205)
    check("硬保底:超出边界向右→绝对停", bot._combat_at_locked_edge("right") is True)
    check("硬保底:超出边界向左→可以走(往回)", bot._combat_at_locked_edge("left") is False)


def test_edge_hysteresis():
    """滞回：触发停后，回到边界内8单位才恢复（不在边上来回抖）"""
    random.seed(123)
    bot = make_edge_mock(player_x=196)  # 触发停
    bot._combat_at_locked_edge("right")  # 初始化+触发
    # 人物回到x=190（比触发线靠里，但不到恢复线margin+8）
    bot._player_map_pos = (190, 100)
    still_stopped = bot._combat_at_locked_edge("right")
    check("滞回:回到边界内但不到恢复线→仍停", still_stopped is True)
    # 人物回到x=180（超过恢复线margin+8）
    bot._player_map_pos = (180, 100)
    recovered = bot._combat_at_locked_edge("right")
    check("滞回:回到恢复线内→允许走", recovered is False)


# ==========================================================================
# 运行所有测试
# ==========================================================================
if __name__ == "__main__":
    print("=== 选梯逻辑 ===")
    test_ladder_up_reach()
    test_ladder_up_top_not_match()
    test_ladder_up_bottom_not_reachable()
    test_ladder_down()
    test_ladder_down_bottom_not_match()
    test_ladder_down_ignore_bottom_match()
    test_ladder_down_no_reachable_fallback()

    print("\n=== cross_candidates返回 ===")
    test_cross_candidates_returned()
    test_cross_disabled_no_candidates()

    print("\n=== 边界滞回 ===")
    test_edge_stop_before_boundary()
    test_edge_hard_guard()
    test_edge_hysteresis()

    print("\n==== 结果: PASS=%d  FAIL=%d ====" % (PASS, FAIL))
    sys.exit(1 if FAIL > 0 else 0)
