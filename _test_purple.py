# -*- coding: utf-8 -*-
# 紫点纯X判台单测：build_buckets 平台门控 + 主线 _screen_to_map 绿框倒数 + _get_monster_platform 纯X
import sys, types
sys.path.insert(0, r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2")
import combat_logic as CL
import maple_route_ui as M

PASS = 0
def chk(name, cond):
    global PASS
    assert cond, "FAIL: " + name
    PASS += 1
    print("[pass]", name)

def box(cx, cy):
    return (cx - 20, cy - 60, cx + 20, cy, 0.9)  # cx 居中, cy=y2

PX, PY = 600, 500
SKILL = 200

def buckets(monsters, selected, mode, cb, aup=100, adn=25, cup=True, cdn=True, slope=None):
    return CL.build_buckets(
        PX, PY, monsters, selected, SKILL, cb, aup, adn,
        group_priority=False, allow_cross=True, metric=None,
        slope_y_up=slope, combat_mode=mode, allow_cross_up=cup, allow_cross_down=cdn)

# 回调：模拟纯X判台结果（cx->台dict/None）
def cb_yes_same(cx, cy):   # 选中台1(id0)
    return {'id': 0}
def cb_by_cx(cx, cy):      # cx600=台1, cx900判不上(别台/换算None)
    return {'id': 0} if cx == 600 else None
def cb_other_platform(cx, cy):  # 判到台6(id5)，不在选中
    return {'id': 5}

# T1 平台single 同台怪(Y差0)留
cand, cross, *_ = buckets([box(600, 500)], [1], 'single', cb_yes_same)
chk("T1 single同台怪进cand", (0, 600, 500) in cand and len(cross) == 0)

# T2 平台single 别台怪(回调None)直接丢,即使X>=300也不进pursue
cand, cross, *_ = buckets([box(900, 500)], [1], 'single', cb_by_cx)
chk("T2 single别台(回调None)被丢", len(cand) == 0 and len(cross) == 0)

# T3 平台single 上层怪(Y差-200)cross全关->不锁不cross
cand, cross, *_ = buckets([box(600, 200)], [1], 'single', cb_yes_same, cup=False, cdn=False)
chk("T3 single上层怪不cross不进cand", len(cand) == 0 and len(cross) == 0)

# T4 自由random selected=[] 全留:同台进cand、上层超带进cross(回调不应被调)
called = {'n': 0}
def cb_count(cx, cy):
    called['n'] += 1
    return {'id': 0}
cand, cross, *_ = buckets([box(600, 500), box(600, 200)], [], 'random', cb_count)
chk("T4 random同台+上层cross各1", len(cand) == 1 and len(cross) == 1)
chk("T4 random不调判台回调(自由零影响)", called['n'] == 0)

# T5 multi 上层选中台怪 allow_cross_up=True -> cross
cand, cross, *_ = buckets([box(600, 200)], [1, 2], 'multi', lambda cx, cy: {'id': 1}, cup=True, cdn=False)
chk("T5 multi上层选中台怪进cross", len(cross) == 1 and cross[0][1] == 600)

# T6 平台 回调台号不在selected -> 丢
cand, cross, *_ = buckets([box(600, 500)], [1], 'single', cb_other_platform)
chk("T6 判到非选中台被丢", len(cand) == 0 and len(cross) == 0)

# ===== 主线 _screen_to_map 绿框实时倒数 =====
fake = types.SimpleNamespace()
fake._player_map_pos = (100.0, 200.0)
fake._player_screen_pos = (600, 500)
fake._cam_x_scale = 15.0
fake._cam_y_scale = 15.0
fake._cam_x_winw = 1280
fake._cam_y_winh = 800
s2m = M.MinimapRouteRecorder._screen_to_map.__get__(fake)
mp = s2m(750, 500)
chk("T7 绿框倒数换算 map_x=110,map_y=200", mp is not None and abs(mp[0] - 110.0) < 1e-6 and abs(mp[1] - 200.0) < 1e-6)
fake._cam_y_scale = None
chk("T7b 缺Y缓存->None安全侧", s2m(750, 500) is None)
fake._cam_y_scale = 15.0

# ===== 主线 _get_monster_platform 纯X判台 =====
fake._screen_to_map = s2m
fake.platforms = [{'id': 0}]
fake._platform_x_range = lambda pf: (100.0, 120.0)
fake._active_platforms = lambda: [1]
gmp = M.MinimapRouteRecorder._get_monster_platform.__get__(fake)
# cx=750 -> map_x 110 ∈ [98,122] -> 台1
chk("T8 紫点X落选中台区间->该台", gmp(750, 500) == {'id': 0})
# cx=1000 -> map_x=126.7 >122 -> None
chk("T8b 紫点X在台区间外->None", gmp(1000, 500) is None)
# 自由模式 selected=[] -> None
fake._active_platforms = lambda: []
chk("T8c 自由模式不判台->None", gmp(750, 500) is None)
fake._active_platforms = lambda: [1]
# 换算失效 -> None
fake._cam_x_scale = None
chk("T8d 换算失效->None安全侧", gmp(750, 500) is None)

print("\n==== 紫点判台单测全部通过: %d 项 ====" % PASS)
