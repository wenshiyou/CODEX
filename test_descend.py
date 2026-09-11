# -*- coding: utf-8 -*-
"""下行 descend 状态机离线流转测试(用户2026-09-10最终定稿:不找口子原地跳,动作先做完整、事后一次判Y;只留两种下跳方式)。
方式一 first_jump:压↓100→第一跳→松↓→随机侧100→第二跳(左右跳)→check_drop观察窗:基准用enter时站定值,300ms起逐帧比人物Y增大(主窗口屏幕≥25或小地图世界≥8),一旦增大即fall落地;到900ms观察窗满仍没增大才转方式二。
方式二 to_ladder(小地图梯X对齐光点±2)→lad_scr(主窗口二合一白框碎步三拍;无特征直接)→lad_grab(按↓500看Y变大)
  →lad_slide(再按↓1秒)→lad_leap(随机侧100+跳)→lad_fall_wait(固定1秒回主线)。
不碰硬件:按键/找梯/背景点全部stub,逐帧喂(px,py,now_ms),校验阶段流转与按键。"""
import numpy as np
import maple_route_ui as M

VK_DOWN = M.VK_DOWN
VK_LEFT = M.VK_LEFT
VK_RIGHT = M.VK_RIGHT
PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  [FAIL]", name)


def make_obj(ladder=None, boxes=(0, 0)):
    b = object.__new__(M.MinimapRouteRecorder)
    b._random_move_keys = set()
    b._climb_state = 'descend'
    b._desc_phase = None
    b._raw_frame = np.zeros((749, 1276, 3), dtype=np.uint8)
    b._player_screen_pos = (0, 0)
    b._climb_still_since = 0
    b._climb_top_hold = False
    b._climb_action_time = 0
    b._desc_land_y = 0
    b._desc_land_t = 0
    b._desc_j2 = False
    b._desc_leap_dir = 1
    b._climb_fail_pause_until = 0
    b.pressed = set()
    b.down_log = []
    b.jumps = 0
    b.reset_n = 0
    b.relock_n = 0
    b.fail_n = 0
    b.trace = []

    b._get_fight_config = lambda: {"jump_key": "X"}
    b._release_move_conflicts = lambda: None

    def _kd(vk):
        b._random_move_keys.add(vk)   # 贴近真实:_key_down会同步维护_random_move_keys(松键判"in"用它)
        b.pressed.add(vk); b.down_log.append(('d', vk))

    def _ku(vk):
        b._random_move_keys.discard(vk)
        b.pressed.discard(vk); b.down_log.append(('u', vk))
    b._key_down = _kd
    b._key_up = _ku
    b._press_game_key = lambda k, duration=80: setattr(b, 'jumps', b.jumps + 1)
    b._rlog = lambda *a, **k: None
    b._find_nearest_ladder = lambda px, py, ty: ladder
    b._pick_climb_boxes = lambda p, h, w: [(0, 0), (1, 1), (2, 2)]
    b._climb_boxes_still = lambda frame, centers: boxes
    # 方式二段2主窗口对位依赖(默认无梯子特征/YOLO→lad_scr直接lad_grab兜底,离线不依赖白框)
    b._ladder_templates = []
    b._ladder_snap_x = None
    b._ladder_precise_mode = False
    b._ladder_use_yolo = lambda: False
    b._match_ladder_screen_x = lambda *a, **k: None
    b._rlog_throttle = lambda *a, **k: None

    def _reset():
        b._climb_state = 'none'; b._desc_phase = None; b.reset_n += 1
        b.pressed.discard(VK_DOWN); b.pressed.discard(VK_LEFT); b.pressed.discard(VK_RIGHT)
    b._reset_climb = _reset
    b._reset_lock_after_arrival = lambda *a: setattr(b, 'relock_n', b.relock_n + 1)

    def _fail():
        b.fail_n += 1; b._climb_state = 'none'; b._desc_phase = None
    b._decide_climb_fail_action = _fail
    return b


def step(b, px, py, t):
    ph0 = b._desc_phase
    b._descend_step(px, py, t)
    if b._desc_phase != ph0:
        b.trace.append(b._desc_phase)


# 场景1【方式一·世界Y佐证跳下】两跳进check_drop→350ms后小地图世界Y比跳前增大≥8→fall→落地回主线
def case1():
    b = make_obj(boxes=(1, 1))
    b._enter_descend(target_x=100, target_y=200, px=0, py=100, now_ms=1000)
    check("c1 起始直接first_jump", b._desc_phase == 'first_jump')
    fj = b._desc_phase_t
    step(b, 99, 100, fj + 99)            # 未满100不跳
    check("c1 100ms前不跳", b.jumps == 0 and VK_DOWN in b.pressed)
    step(b, 99, 100, fj + 100)           # 满100第一跳+松↓+按随机侧键
    check("c1 满100第一跳", b.jumps == 1)
    check("c1 第一跳后松↓", VK_DOWN not in b.pressed)
    step(b, 99, 100, fj + 150)           # 侧键才50ms,不第二跳
    check("c1 侧键未满100不第二跳", b.jumps == 1)
    step(b, 99, 100, fj + 200)           # 侧键满100第二跳+松左右+进check_drop(记基准世界Y=100)
    check("c1 侧键满100第二跳", b.jumps == 2)
    check("c1 第二跳后进check_drop", b._desc_phase == 'check_drop')
    check("c1 第二跳后松左右", VK_LEFT not in b.pressed and VK_RIGHT not in b.pressed)
    step(b, 99, 100, fj + 400)           # 判定窗未满350(从第二跳起),仍check_drop
    check("c1 判定窗未满仍check_drop", b._desc_phase == 'check_drop')
    step(b, 99, 115, fj + 550)           # 满350,世界Y 100→115 Δ15≥8=穿到下一层→fall
    check("c1 世界YΔ15≥8转fall", b._desc_phase == 'fall')
    ht = fj + 550
    step(b, 99, 115, ht + 100)
    step(b, 99, 115, ht + 300)           # 背景静止/Y稳定任一满足=落地
    check("c1 落地state=none", b._climb_state == 'none')
    check("c1 落地松↓", VK_DOWN not in b.pressed)
    check("c1 落地触发重锁", b.relock_n == 1)


# 场景2【方式一跳不下去→方式二】check_drop后Y没增大→to_ladder小地图±2→lad_scr(无特征直接)lad_grab抓住→slide→leap侧跳→固定1秒回主线
def case2():
    b = make_obj(ladder={"x": 30, "y_top": 50, "y_bottom": 200})
    b._enter_descend(0, 200, 0, 100, 2000)
    step(b, 0, 100, 2000)
    check("c2 进first_jump", b._desc_phase == 'first_jump')
    fj = b._desc_phase_t
    step(b, 0, 100, fj + 100)           # 第一跳
    step(b, 0, 100, fj + 200)           # 第二跳→check_drop
    check("c2 方式一两跳按完", b.jumps == 2 and b._desc_phase == 'check_drop')
    step(b, 0, 100, fj + 500)           # el=300刚到最早判定,Y没增大且未到900上限→仍check_drop继续观察
    check("c2 观察窗内Y没增大仍check_drop", b._desc_phase == 'check_drop')
    step(b, 0, 100, fj + 1100)          # el=900满观察窗Y始终没变(Δ0)=真跳不下去→方式二to_ladder,梯X=30
    check("c2 满观察窗没增大转to_ladder且梯X=30", b._desc_phase == 'to_ladder' and b._climb_ladder_x == 30)
    t = fj + 1100
    step(b, 24, 100, t + 100)           # |30-24|=6>5,小地图继续走(to_ladder),不切
    check("c2 |差|6>5仍to_ladder", b._desc_phase == 'to_ladder')
    step(b, 25, 100, t + 200)           # |30-25|=5≤5→切段2 lad_scr(同拍开30Hz高帧)
    check("c2 |差|5切lad_scr且开高帧", b._desc_phase == 'lad_scr' and b._ladder_precise_mode)
    step(b, 25, 100, t + 300)           # 无梯子特征/YOLO→lad_scr直接lad_grab按↓
    check("c2 lad_scr进lad_grab且按↓", b._desc_phase == 'lad_grab' and VK_DOWN in b.pressed)
    lg = t + 300
    step(b, 25, 100, lg + 100)          # 未满500仍观察
    check("c2 500ms前仍lad_grab", b._desc_phase == 'lad_grab')
    step(b, 25, 110, lg + 500)          # Y变大=抓住梯子→lad_slide
    check("c2 Y变大转lad_slide", b._desc_phase == 'lad_slide')
    ls = lg + 500
    step(b, 25, 110, ls + 999)
    check("c2 下滑未满1秒仍lad_slide", b._desc_phase == 'lad_slide')
    step(b, 25, 110, ls + 1000)         # 满1秒→松↓随机侧键进lad_leap
    check("c2 满1秒转lad_leap且松↓", b._desc_phase == 'lad_leap' and VK_DOWN not in b.pressed)
    lp = ls + 1000
    step(b, 25, 110, lp + 99)
    check("c2 侧键未满100仍lad_leap", b._desc_phase == 'lad_leap')
    step(b, 25, 110, lp + 100)          # 侧键满100+跳+松左右→lad_fall_wait
    check("c2 侧跳转lad_fall_wait(方式二第3次跳)", b._desc_phase == 'lad_fall_wait' and b.jumps == 3)
    lw = lp + 100
    step(b, 25, 110, lw + 999)
    check("c2 未满1秒仍等待", b._desc_phase == 'lad_fall_wait' and b._climb_state == 'descend')
    step(b, 25, 110, lw + 1000)         # 固定满1秒→清锁回主线
    check("c2 满1秒回主线state=none", b._climb_state == 'none')
    check("c2 回主线触发重锁", b.relock_n == 1)


# 场景3【方式二抓不住】对齐梯后lad_grab满500ms Y始终没变=抓不住,松↓回主线(不补跳/不死磕)
def case3():
    b = make_obj(ladder={"x": 0, "y_top": 50, "y_bottom": 200}, boxes=(0, 0))
    b._enter_descend(0, 200, 0, 100, 4000)   # 人就在梯X=0
    t = 4000
    guard = 0
    while b._climb_state == 'descend' and guard < 80:
        guard += 1
        t += 100
        step(b, 0, 100, t)                  # py恒100=一直下不去
    check("c3 抓不住回主线state=none", b._climb_state == 'none')
    check("c3 调了失败重选", b.fail_n == 1)
    check("c3 回主线时松↓", VK_DOWN not in b.pressed)


# 场景4【小地图走不到梯子】方式一失败转to_ladder,人被挡住连续600ms没靠近→stall切lad_scr→无特征lad_grab
def case4():
    b = make_obj(ladder={"x": 100, "y_top": 50, "y_bottom": 200})
    b._enter_descend(100, 200, 50, 100, 5000)   # 梯在100,人卡在50
    t = 5000
    # 先走完方式一(两跳+check_drop失败)进to_ladder
    while b._desc_phase != 'to_ladder' and t < 5000 + 2000:
        t += 100
        step(b, 50, 100, t)
    check("c4 方式一失败转to_ladder", b._desc_phase == 'to_ladder')
    # px恒50=走不动,持续喂超过stall 600ms → 切lad_scr,再一帧无特征进lad_grab
    guard = 0
    while b._desc_phase in ('to_ladder', 'lad_scr') and guard < 14:
        guard += 1
        t += 100
        step(b, 50, 100, t)
    check("c4 卡住经lad_scr就近进lad_grab", b._desc_phase == 'lad_grab')


# 场景5【方式一·主窗口屏幕Y判定】世界Y没动(镜头跟随),但人物特征屏幕Y比左右跳前增大≥25→fall
def case5():
    b = make_obj(boxes=(1, 1))
    b._player_screen_pos = (0, 300)        # 站定(进descend)时屏幕Y=300=基准(新机制基准在enter站定时记)
    b._enter_descend(target_x=100, target_y=200, px=0, py=100, now_ms=7000)
    fj = b._desc_phase_t
    step(b, 0, 100, fj + 100)              # 第一跳
    step(b, 0, 100, fj + 200)              # 第二跳进check_drop(基准沿用站定300,不再在跳中覆盖)
    check("c5 第二跳进check_drop", b._desc_phase == 'check_drop')
    b._player_screen_pos = (0, 330)        # 屏幕Δ30≥25(世界py恒100,Δ0<8)
    step(b, 0, 100, fj + 550)              # el=350≥300最早判定,屏幕Δ30≥25→fall
    check("c5 屏幕Δ30≥25转fall", b._desc_phase == 'fall')


# 场景6【阈值放宽·小位移不算下穿】屏幕Δ20<25且世界Δ5<8=只是原地小跳没穿台→转方式二to_ladder
def case6():
    b = make_obj(ladder={"x": 0, "y_top": 50, "y_bottom": 200})
    b._player_screen_pos = (0, 300)        # 站定基准屏幕Y=300(新机制基准在enter站定时记)
    b._enter_descend(0, 200, 0, 100, 8000)
    fj = b._desc_phase_t
    step(b, 0, 100, fj + 100)
    step(b, 0, 100, fj + 200)              # 第二跳,基准沿用站定300/世界100
    b._player_screen_pos = (0, 320)        # 屏幕Δ20<25
    step(b, 0, 105, fj + 500)              # el=300,屏幕Δ20<25/世界Δ5<8都不够、未到900→仍check_drop
    check("c6 小位移观察窗内仍check_drop", b._desc_phase == 'check_drop')
    step(b, 0, 105, fj + 1100)             # el=900满观察窗仍没增大→to_ladder
    check("c6 满观察窗小位移不够转to_ladder", b._desc_phase == 'to_ladder')


for fn in (case1, case2, case3, case4, case5, case6):
    fn()
print("==== RESULT: PASS=%d FAIL=%d ====" % (PASS, FAIL))
raise SystemExit(1 if FAIL else 0)
