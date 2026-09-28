# -*- coding: utf-8 -*-
# 黑框状态影子化单测(真实lock_screen_from_dot+假self,测完留.trash底)
import importlib.util, warnings
warnings.filterwarnings("ignore")
spec = importlib.util.spec_from_file_location("mru", "maple_route_ui.py")
mru = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mru)
R = mru.MinimapRouteRecorder
mru._debug_log = lambda m: None
KP = {}
mru.key_pressed = lambda vk: KP.get(vk, False)

VK = dict(up=0x26, down=0x28, left=0x25, right=0x27)
DEAD = mru.DOT_SHADOW_DEAD_PX  # 2

class FakeSelf:
    _calc_blue_box_pos = R._calc_blue_box_pos
    lock_screen_from_dot = R.lock_screen_from_dot
    def __init__(self):
        self.map_area_rect = {'left': 14, 'top': 123, 'width': 200, 'height': 150}
        self._player_map_pos = (100.0, 60.0)
        self._target_window_size = (1280, 800)
        self._blue_box = {'width': 20, 'height': 15}
        self._blue_box_deadzone_pos = None
        self._camera_state = 'following'
        self._dot_shadow_pos = (100.0, 60.0)
        self._dot_dir_vec = (0.0, 0.0)
        self._combat_move_dir = None
        self.frame_count = 0
        self._speed_prev = None
        # 8补偿值设成可区分的数(基线:offset_x=10→sx=640, offset_y=7→sy=373)
        self.FOLLOW_LEFT_X = 200; self.FOLLOW_RIGHT_X = 100; self.FOLLOW_Y = 10
        self.DEAD_LEFT_X = 400; self.DEAD_RIGHT_X = 300; self.DEAD_Y = 20
        self.IDLE_X = 50; self.IDLE_Y = 30

# case1 影子静止+镜头说跟随 → 压过检测用站立值(惯性滚动滞后bug回归)
fs = FakeSelf()
fs._camera_state = 'following'
fs._dot_dir_vec = (0.0, 0.0)
sx, sy = R.lock_screen_from_dot(fs)
assert sx == 640 + 50 and sy == 373 + 30, (sx, sy)
print("case1 静=站立值(压过跟随) OK")

# case2 影子向右+跟随区 → 跟随右X
fs = FakeSelf()
fs._dot_dir_vec = (5.0, 0.0)
sx, sy = R.lock_screen_from_dot(fs)
assert sx == 640 + 100 and sy == 373 + 10, (sx, sy)
print("case2 跟随+影右=跟随右X OK")

# case3 影子向左+死区 → 死区左X
fs = FakeSelf()
fs._camera_state = 'deadzone'
fs._dot_dir_vec = (-5.0, 0.0)
sx, sy = R.lock_screen_from_dot(fs)
assert sx == 640 - 400 and sy == 373 + 20, (sx, sy)
print("case3 死区+影左=死区左X OK")

# case4 影子向右+死区 → 死区右X
fs = FakeSelf()
fs._camera_state = 'deadzone'
fs._dot_dir_vec = (5.0, 0.0)
sx, sy = R.lock_screen_from_dot(fs)
assert sx == 640 + 300, sx
print("case4 死区+影右=死区右X OK")

# case5 按住右键但影子静止(卡住) → 站立值(意图≠事实回归:旧代码这里会错套跟随右X)
fs = FakeSelf()
KP.clear(); KP[VK['right']] = True
fs._dot_dir_vec = (0.0, 0.0)
sx, sy = R.lock_screen_from_dot(fs)
assert sx == 640 + 50 and sy == 373 + 30, (sx, sy)
print("case5 按键但影子静=站立值 OK")

# case6 没按键但影子向左(被推开) → 跟随左X(旧代码这里会错套站立X)
fs = FakeSelf()
KP.clear()
fs._dot_dir_vec = (-5.0, 0.0)
sx, sy = R.lock_screen_from_dot(fs)
assert sx == 640 - 200, sx
print("case6 无键但影子左=跟随左X OK")

# case7 影子无效(光点丢) → 回退按键判定
fs = FakeSelf()
fs._dot_shadow_pos = None
KP.clear(); KP[VK['right']] = True
sx, sy = R.lock_screen_from_dot(fs)
assert sx == 640 + 100, sx
print("case7 影子无效回退按键 OK")

# case8 垂直移动(爬梯,dy>0,dx=0) → X不加左右补偿,只加区Y
fs = FakeSelf()
fs._dot_dir_vec = (0.0, 5.0)
sx, sy = R.lock_screen_from_dot(fs)
assert sx == 640 and sy == 373 + 10, (sx, sy)
print("case8 垂直移动只加区Y OK")

print("=== ALL 8 PASS ===")
