"""
Minimap Route Recorder - 鼠标操作版
Auto lock game window + blue border detection (projection) + ROI dot tracking
三套方案（route_1/2/3），每套独立存储平台+梯子；方式：手动/随机
操作：纯鼠标点击，第一排 平台/梯子/清平台/清梯子/保存/手动/刷新
      第二排 方案1/方案2/方案3/清方案/方式切换
"""
import ctypes
import struct
import mss
import numpy as np
import cv2
import os
import json
import time
import sys
import queue
import random
from pynput import mouse

# 无缓冲输出，方便实时看日志
sys.stdout.reconfigure(line_buffering=True)

os.chdir(os.path.dirname(os.path.abspath(__file__)))

DISPLAY_SCALE = 1
WINDOW_TITLE = "冒险岛怀旧服"
FIXED_W = 340
MAP_H = 250
BTN_BAR_H = 77  # 整图按钮栏高度（2行4列带间距）
BTN_ROW_H = BTN_BAR_H // 2  # 38
BTN_COLS = 4
BTN_W = FIXED_W // BTN_COLS  # 85
FIXED_H = MAP_H + BTN_BAR_H  # 327
DROPDOWN_ITEM_H = 24
YELLOW_H_LOW = 25
YELLOW_H_HIGH = 35
YELLOW_S_LOW = 120
YELLOW_V_LOW = 180

VK_F5 = 0x74
VK_F6 = 0x75
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78

# 游戏控制按键（冒险岛默认，可根据实际设置调整）
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_UP = 0x26
VK_DOWN = 0x28
VK_JUMP = 0x20   # Space
VK_ATTACK = 0x11  # Ctrl

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
REGION_FILE = os.path.join(DATA_DIR, "minimap_region.json")
ROUTE_CONFIG_FILE = os.path.join(DATA_DIR, "route_config.json")

# 按钮颜色 (BGR)
BTN_GREEN = (0, 165, 0)
BTN_BLUE = (210, 130, 0)
BTN_BLACK = (48, 48, 48)
BTN_ORANGE = (0, 135, 225)
BTN_WHITE = (255, 255, 255)

# 按钮布局：(文字, 背景色, 是否有下拉)
BTN_ROW1 = [
    ("平台", BTN_GREEN, False),
    ("梯子", BTN_BLUE, False),
    ("保存", BTN_BLACK, True),
    ("方案", BTN_ORANGE, True),
]
BTN_ROW2 = [
    ("清除", BTN_GREEN, False),   # 清平台
    ("清除", BTN_BLUE, False),    # 清梯子
    ("模式", BTN_BLACK, True),
    ("清除", BTN_ORANGE, True),   # 清方案
]


def route_files(route_id):
    """返回指定方案的平台文件和梯子文件路径"""
    return (
        os.path.join(DATA_DIR, "route_%d_platforms.json" % route_id),
        os.path.join(DATA_DIR, "route_%d_ladders.json" % route_id)
    )

COLOR_PLATFORM = (0, 255, 0)
COLOR_LADDER = (255, 100, 0)
COLOR_RECORDING = (0, 0, 255)
COLOR_PLAYER = (0, 255, 255)

user32 = ctypes.windll.user32


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = ctypes.c_bool


def key_pressed(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class GlobalHotkeyListener:
    """低级键盘钩子全局热键（主线程版），绕过 UIPI，游戏前台也能捕获"""
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104

    def __init__(self, vk_list):
        self.vk_list = set(vk_list)
        self.events = queue.Queue()
        self._hook = None
        self._hook_proc_ref = None

    def _hook_proc(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
            vk = ctypes.cast(lParam, ctypes.POINTER(ctypes.c_ulong))[0] & 0xFF
            if vk in self.vk_list:
                self.events.put(vk)
        return user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

    def install(self):
        """在主线程安装钩子，返回是否成功"""
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p)
        self._hook_proc_ref = HOOKPROC(self._hook_proc)
        kernel32 = ctypes.windll.kernel32
        self._hook = user32.SetWindowsHookExW(
            self.WH_KEYBOARD_LL, self._hook_proc_ref,
            kernel32.GetModuleHandleW(None), 0
        )
        return bool(self._hook)

    def pump(self):
        """每帧调用，处理钩子消息（必须在安装钩子的线程调用）"""
        msg = ctypes.c_void_p()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
            if msg.value == 0x0012:  # WM_QUIT
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def uninstall(self):
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def get_events(self):
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                break
        return events


class MinimapRouteRecorder:
    def __init__(self):
        self.sct = mss.mss()
        self.hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if not self.hwnd:
            raise RuntimeError("Game window not found: " + WINDOW_TITLE)
        self._update_window_rect()
        self._detect_minimap()

        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []

        # 方案系统：当前方案(1-3) + 运行方式(手动/随机)
        self.current_route = 1
        self.route_mode = "手动"
        self._dropdown = None  # 当前展开的下拉菜单: None/"save"/"route"/"mode"/"clear_route"
        self._load_route_config()
        pf_file, ld_file = route_files(self.current_route)
        self.platforms = self._load(pf_file, "platforms")
        self.ladders = self._load(ld_file, "ladders")

        # 加载按钮栏整图
        self._btn_bar_img = None
        btn_path = os.path.join(os.path.dirname(__file__), "data", "templates", "btn_bar.png")
        if os.path.exists(btn_path):
            self._btn_bar_img = cv2.imread(btn_path)

        # 手动框选模式状态
        self._selecting = False
        self._select_frame = None
        self._select_rect = None
        self._select_dragging = False

        # 随机模式运行状态
        self._random_running = False
        self._random_route_id = None
        self._random_platform_idx = 0
        self._random_state = "idle"  # idle/moving/attacking/returning
        self._random_attack_start = 0
        self._random_move_keys = set()  # 当前按住的移动键

        # 自动刷新状态：默认开启，手动框选后关闭，点刷新重新开启
        self._auto_refresh = True

        self.last_player_pos = None
        self.frame_count = 0

        # 热键状态（保留以备鼠标回调复用_handle_hotkey）
        self._key_state = {vk: False for vk in [VK_F5, VK_F6, VK_F7, VK_F8, VK_F9]}

        print("Map area:", self.map_area_rect["width"], "x", self.map_area_rect["height"])
        print("方案 %d 已加载: %d 平台, %d 梯子 (模式: %s)" % (
            self.current_route, len(self.platforms), len(self.ladders), self.route_mode))
        print("UI: 左上角=刷新/手动/方案X  第一排=平台/梯子/保存▼/方案▼")
        print("    第二排=清除(绿=平台)/清除(蓝=梯子)/模式▼/清除(橙=方案)\n")

    def _update_window_rect(self):
        rect = ctypes.create_string_buffer(16)
        user32.GetWindowRect(self.hwnd, rect)
        l, t, r, b = struct.unpack("llll", rect.raw)
        self.window_rect = {"left": l, "top": t, "width": r - l, "height": b - t}

    def _load_region(self):
        """从文件加载已保存的小地图区域，成功返回 True"""
        if not os.path.exists(REGION_FILE):
            return False
        try:
            with open(REGION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "map" in data and "minimap" in data:
                self.map_area_rect = data["map"]
                self.minimap_rect = data["minimap"]
                print("Loaded saved region:", self.map_area_rect["width"], "x", self.map_area_rect["height"])
                return True
        except Exception:
            pass
        return False

    def _detect_minimap(self, debug=True):
        """三特征点定位：左=小地图文字左，右=大地图文字右，下=底部蓝色线（颜色检测）
        debug=False 时为每帧轻量模式，不写调试图"""
        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]

        # 懒加载模板
        if not hasattr(self, '_tpl_minimap'):
            base = os.path.join(os.path.dirname(__file__), "data", "templates")
            self._tpl_minimap = cv2.imread(os.path.join(base, "minimap_title.png"))
            self._tpl_bigmap = cv2.imread(os.path.join(base, "bigmap_title.png"))
            print("Templates loaded: mini%dx%d big%dx%d" % (
                self._tpl_minimap.shape[1], self._tpl_minimap.shape[0],
                self._tpl_bigmap.shape[1], self._tpl_bigmap.shape[0]))

        tpl_m, tpl_b = self._tpl_minimap, self._tpl_bigmap
        mh, mw = tpl_m.shape[:2]
        bh, bw = tpl_b.shape[:2]

        # 1. 找"小地图"文字
        roi_m = frame[0:120, 0:300]
        res_m = cv2.matchTemplate(roi_m, tpl_m, cv2.TM_CCOEFF_NORMED)
        _, val_m, _, loc_m = cv2.minMaxLoc(res_m)
        mini_x, mini_y = loc_m
        if debug:
            print("小地图: val=%.3f at (%d,%d)" % (val_m, mini_x, mini_y))
        if val_m < 0.55:
            if debug:
                print("小地图匹配度过低，回退扫描线法")
                self._detect_minimap_scanline()
            return

        # 2. 找"大地图"文字（小地图右侧同行）
        roi_b_x1 = mini_x + mw
        roi_b_x2 = min(fw, mini_x + 200)
        roi_b = frame[max(0, mini_y - 5):mini_y + mh + 10, roi_b_x1:roi_b_x2]
        res_b = cv2.matchTemplate(roi_b, tpl_b, cv2.TM_CCOEFF_NORMED)
        _, val_b, _, loc_b = cv2.minMaxLoc(res_b)
        big_x = roi_b_x1 + loc_b[0]
        big_y = max(0, mini_y - 5) + loc_b[1]
        if debug:
            print("大地图: val=%.3f at (%d,%d)" % (val_b, big_x, big_y))

        # 3. 边界：左=小地图左，右=大地图右，上=小地图下
        left = mini_x
        right = big_x + bw
        top = mini_y + mh
        if debug:
            print("边界: L=%d R=%d T=%d W=%d" % (left, right, top, right - left))

        # 4. top向下350px内，从下往上找底部蓝色线（颜色检测）
        blue_y1 = top
        blue_y2 = min(fh, top + 350)
        roi_blue = frame[blue_y1:blue_y2, left:right]
        hsv_blue = cv2.cvtColor(roi_blue, cv2.COLOR_BGR2HSV)
        blue_mask = cv2.inRange(hsv_blue, np.array([90, 40, 80]), np.array([125, 220, 240]))
        row_blue = np.sum(blue_mask > 0, axis=1)
        roi_w = right - left
        bottom = None
        for y in range(len(row_blue) - 1, -1, -1):
            if row_blue[y] > roi_w * 0.30:
                bottom = blue_y1 + y
                break
        if bottom is None:
            if debug:
                print("蓝色线未找到，跳过本帧")
            return
        if debug:
            print("底部蓝色线: y=%d (blue_px=%d)" % (bottom, row_blue[bottom - blue_y1]))

        # 5. 计算区域
        new_minimap = {
            "left": left, "top": mini_y,
            "width": right - left, "height": bottom - mini_y
        }
        TITLE_PAD = 45
        new_map = {
            "left": left,
            "top": top + TITLE_PAD,
            "width": right - left,
            "height": bottom - top - TITLE_PAD
        }

        # 轻量模式：区域变化小于3px则不更新（防抖），不写文件不写图
        if not debug:
            old = self.map_area_rect
            if (abs(old["left"] - new_map["left"]) <= 3 and
                abs(old["top"] - new_map["top"]) <= 3 and
                abs(old["width"] - new_map["width"]) <= 3 and
                abs(old["height"] - new_map["height"]) <= 3):
                return
            print("[自动刷新] 小地图区域变化: %dx%d -> %dx%d" % (
                old["width"], old["height"], new_map["width"], new_map["height"]))

        self.minimap_rect = new_minimap
        self.map_area_rect = new_map
        self._save_region()
        self.last_player_pos = None

        if debug:
            # 调试图
            dbg = frame.copy()
            cv2.rectangle(dbg, (mini_x, mini_y), (mini_x + mw, mini_y + mh), (0, 0, 255), 1)
            cv2.rectangle(dbg, (big_x, big_y), (big_x + bw, big_y + bh), (0, 165, 255), 1)
            cv2.line(dbg, (left, bottom), (right, bottom), (255, 0, 255), 2)
            cv2.rectangle(dbg, (self.minimap_rect["left"], self.minimap_rect["top"]),
                          (self.minimap_rect["left"] + self.minimap_rect["width"],
                           self.minimap_rect["top"] + self.minimap_rect["height"]), (255, 0, 0), 1)
            mr = self.map_area_rect
            cv2.rectangle(dbg, (mr["left"], mr["top"]),
                          (mr["left"] + mr["width"], mr["top"] + mr["height"]), (0, 255, 0), 2)
            cv2.imwrite("debug_detect.png", dbg)
            print("Map area: %dx%d" % (self.map_area_rect["width"], self.map_area_rect["height"]))

    def _detect_minimap_scanline(self):
        """【兜底】扫描线法：直接巡最外面的细边框（含圆角），标题栏包含在内"""
        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]

        # 搜索区域：窗口左上角小范围（小地图固定在左上角，避免扫到游戏背景）
        roi_top = 8
        roi_bottom = min(fh, 260)
        roi_right = min(fw, 220)
        roi = frame[roi_top:roi_bottom, 0:roi_right].copy()
        roi_h, roi_w = roi.shape[:2]

        # 灰度 + 亮度阈值找灰白色细边框
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        def scan_h(start, end, step, threshold=130, ratio=0.55):
            for y in range(start, end, step):
                if y < 0 or y >= roi_h:
                    break
                if np.sum(gray[y, :] > threshold) > roi_w * ratio:
                    return y
            return None

        def scan_v(start, end, step, y1, y2, threshold=130, ratio=0.45):
            for x in range(start, end, step):
                if x < 0 or x >= roi_w:
                    break
                if np.sum(gray[y1:y2, x] > threshold) > (y2 - y1) * ratio:
                    return x
            return None

        # 顶部：从上往下第一条亮线
        top_y = scan_h(0, roi_h // 2, 1, 130, 0.55)

        # 左右边框先找（用顶部以下的范围）
        if top_y is not None:
            mid_y1 = top_y + 20
            mid_y2 = min(roi_h - 5, top_y + 180)
            left_x = scan_v(0, roi_w // 2, 1, mid_y1, mid_y2, 130, 0.45)
            right_x = scan_v(roi_w - 1, roi_w // 2, -1, mid_y1, mid_y2, 130, 0.45)
        else:
            left_x = scan_v(0, roi_w // 2, 1, 20, roi_h - 5, 130, 0.45)
            right_x = scan_v(roi_w - 1, roi_w // 2, -1, 20, roi_h - 5, 130, 0.45)

        # 底部：在合理范围内找（小地图高宽比约1:1，高度≈宽度±30）
        if top_y is not None and left_x is not None and right_x is not None:
            est_h = right_x - left_x  # 估计高度≈宽度
            bottom_search_top = top_y + max(120, est_h - 30)
            bottom_search_bottom = top_y + min(roi_h - top_y - 5, est_h + 40)
            bottom_y = scan_h(bottom_search_bottom, bottom_search_top, -1, 120, 0.45)
        else:
            bottom_y = scan_h(roi_h - 1, 60, -1, 130, 0.50)

        # 兜底
        if top_y is None: top_y = 5
        if bottom_y is None: bottom_y = roi_h - 5
        if left_x is None: left_x = 3
        if right_x is None: right_x = roi_w - 5

        print("Scan border: top=%d bottom=%d left=%d right=%d" % (top_y, bottom_y, left_x, right_x))

        # 小地图外框 = 扫描线粗定位（含标题栏）
        self.minimap_rect = {
            "left": left_x,
            "top": roi_top + top_y,
            "width": right_x - left_x,
            "height": bottom_y - top_y
        }

        # ===== 第二步：颜色检测精修，裁掉多余边框 =====
        # 截取粗定位区域，用颜色分析找真实内容边界
        coarse = frame[roi_top + top_y:roi_top + bottom_y, left_x:right_x].copy()
        ch, cw = coarse.shape[:2]
        hsv_c = cv2.cvtColor(coarse, cv2.COLOR_BGR2HSV)
        # 内容像素：非亮边框（亮度<160 或 饱和度>50），即深色背景+彩色平台+光点
        content_mask = ((hsv_c[:, :, 2] < 160) | (hsv_c[:, :, 1] > 50)).astype(np.uint8) * 255
        content_mask = cv2.morphologyEx(content_mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

        def find_content_edge(mask, axis, start, end, step, ratio=0.15):
            """沿 axis=0(行) 或 axis=1(列) 扫描，找第一个内容占比>ratio的位置"""
            h_m, w_m = mask.shape
            if axis == 0:
                for i in range(start, end, step):
                    if np.sum(mask[i, :] > 0) > w_m * ratio:
                        return i
            else:
                for i in range(start, end, step):
                    if np.sum(mask[:, i] > 0) > h_m * ratio:
                        return i
            return None

        # 精修四边（从粗边框向内找内容边界）
        refine_top = find_content_edge(content_mask, 0, 0, ch // 2, 1, 0.15)
        refine_bottom = find_content_edge(content_mask, 0, ch - 1, ch // 3, -1, 0.15)
        refine_left = find_content_edge(content_mask, 1, 0, cw // 2, 1, 0.10)
        refine_right = find_content_edge(content_mask, 1, cw - 1, cw // 2, -1, 0.10)

        # 精修失败则用粗定位 + 固定内边距
        if refine_left is None: refine_left = 8
        if refine_top is None: refine_top = 2
        if refine_right is None: refine_right = cw - 2
        if refine_bottom is None: refine_bottom = ch - 2

        print("Refine: L=%d T=%d R=%d B=%d (coarse %dx%d)" % (
            refine_left, refine_top, refine_right, refine_bottom, cw, ch))

        # 地图区域 = 精修后的内容区（窗口内坐标）
        self.map_area_rect = {
            "left": left_x + refine_left,
            "top": roi_top + top_y + refine_top,
            "width": refine_right - refine_left,
            "height": refine_bottom - refine_top
        }

        self._save_region()
        dbg = frame.copy()
        cv2.rectangle(dbg, (self.minimap_rect["left"], self.minimap_rect["top"]),
                      (self.minimap_rect["left"] + self.minimap_rect["width"],
                       self.minimap_rect["top"] + self.minimap_rect["height"]), (255, 0, 0), 1)
        mr = self.map_area_rect
        cv2.rectangle(dbg, (mr["left"], mr["top"]),
                      (mr["left"] + mr["width"], mr["top"] + mr["height"]), (0, 255, 0), 1)
        cv2.imwrite("debug_detect.png", dbg)
        print("Map area:", self.map_area_rect["width"], "x", self.map_area_rect["height"])

    def _save_region(self):
        with open(REGION_FILE, "w", encoding="utf-8") as f:
            json.dump({"minimap": self.minimap_rect, "map": self.map_area_rect}, f, indent=2)

    def _load_route_config(self):
        """加载方案配置（当前方案 + 运行方式）"""
        if os.path.exists(ROUTE_CONFIG_FILE):
            try:
                with open(ROUTE_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.current_route = data.get("current_route", 1)
                self.route_mode = data.get("route_mode", "手动")
            except Exception:
                pass

    def _save_route_config(self):
        """保存方案配置"""
        with open(ROUTE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"current_route": self.current_route, "route_mode": self.route_mode}, f, indent=2)

    def _load(self, path, key):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f).get(key, [])
            except Exception:
                return []
        return []

    def _route_has_file(self, route_id):
        """方案是否已录：只要平台文件存在就算已录"""
        pf_file, _ = route_files(route_id)
        return os.path.exists(pf_file)

    def _save_to_route(self, route_id):
        """保存当前录制的平台+梯子到指定方案文件（覆盖）"""
        pf_file, ld_file = route_files(route_id)
        with open(pf_file, "w", encoding="utf-8") as f:
            json.dump({"platforms": self.platforms, "count": len(self.platforms)}, f, indent=2)
        with open(ld_file, "w", encoding="utf-8") as f:
            json.dump({"ladders": self.ladders, "count": len(self.ladders)}, f, indent=2)
        self.current_route = route_id
        self._save_route_config()
        print("[保存] 方案%d: %d 平台, %d 梯子（已覆盖）" % (
            route_id, len(self.platforms), len(self.ladders)))

    def _save(self):
        """保存到当前方案（兼容切换时调用）"""
        self._save_to_route(self.current_route)

    def _switch_route(self, route_id):
        """切换方案：不自动保存，直接加载目标方案数据"""
        if route_id == self.current_route:
            return
        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []
        self.current_route = route_id
        pf_file, ld_file = route_files(route_id)
        self.platforms = self._load(pf_file, "platforms")
        self.ladders = self._load(ld_file, "ladders")
        self._save_route_config()
        print("[切换] 方案 %d: %d 平台, %d 梯子" % (
            route_id, len(self.platforms), len(self.ladders)))

    def _clear_route_file(self, route_id):
        """清除指定方案：删除文件，若为当前方案则清空内存"""
        pf_file, ld_file = route_files(route_id)
        for f in (pf_file, ld_file):
            if os.path.exists(f):
                os.remove(f)
        if route_id == self.current_route:
            self.platforms = []
            self.ladders = []
            self.platform_points = []
            self.ladder_points = []
            self.recording_platform = False
            self.recording_ladder = False
        print("[清除] 方案%d 已删除" % route_id)

    def _clear_route(self):
        """清除当前方案（保留兼容）"""
        self._clear_route_file(self.current_route)

    def _pop_platform(self):
        """删除最后一个平台段"""
        if self.platforms:
            removed = self.platforms.pop()
            print("[清平台] 删除最后一个平台 id=%s (剩余 %d)" % (removed.get("id"), len(self.platforms)))
        else:
            print("[清平台] 没有可删除的平台")

    def _pop_ladder(self):
        """删除最后一个梯子段"""
        if self.ladders:
            removed = self.ladders.pop()
            print("[清梯子] 删除最后一个梯子 id=%s (剩余 %d)" % (removed.get("id"), len(self.ladders)))
        else:
            print("[清梯子] 没有可删除的梯子")

    def _toggle_mode(self):
        """切换运行方式：手动 <-> 随机"""
        self.route_mode = "随机" if self.route_mode == "手动" else "手动"
        self._save_route_config()
        if self.route_mode == "随机":
            self._start_random()
        else:
            self._stop_random()
        print("[方式] 切换为: %s" % self.route_mode)

    def _dropdown_items(self):
        """返回当前下拉菜单的菜单项列表"""
        if self._dropdown == "save":
            return ["保存为方案一", "保存为方案二", "保存为方案三"]
        elif self._dropdown == "route":
            items = []
            for i in range(1, 4):
                status = "已录" if self._route_has_file(i) else "未录"
                items.append("方案%s【%s】" % ("一二三"[i - 1], status))
            return items
        elif self._dropdown == "mode":
            return ["手动", "随机"]
        elif self._dropdown == "clear_route":
            return ["清除方案一", "清除方案二", "清除方案三"]
        return []

    def _handle_dropdown_item(self, menu, item_idx):
        """处理下拉菜单项点击"""
        if menu == "save":
            self._save_to_route(item_idx + 1)
        elif menu == "route":
            self._switch_route(item_idx + 1)
        elif menu == "mode":
            self.route_mode = "手动" if item_idx == 0 else "随机"
            self._save_route_config()
            if self.route_mode == "随机":
                self._start_random()
            else:
                self._stop_random()
            print("[模式] 切换为: %s" % self.route_mode)
        elif menu == "clear_route":
            self._clear_route_file(item_idx + 1)

    # ===== 随机模式运行逻辑 =====

    def _key_down(self, vk):
        user32.keybd_event(vk, 0, 0, 0)
        self._random_move_keys.add(vk)

    def _key_up(self, vk):
        user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
        self._random_move_keys.discard(vk)

    def _release_all_keys(self):
        for vk in list(self._random_move_keys):
            user32.keybd_event(vk, 0, 2, 0)
        self._random_move_keys.clear()

    def _start_random(self):
        """启动随机模式：停止录制，清空按键，开始状态机"""
        if self._random_running:
            return
        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []
        self._release_all_keys()
        self._random_running = True
        self._random_state = "idle"
        self._random_platform_idx = 0
        print("[随机] 模式已启动，将自动选方案打平台")

    def _stop_random(self):
        """停止随机模式：松开所有按键"""
        if not self._random_running:
            return
        self._release_all_keys()
        self._random_running = False
        self._random_state = "idle"
        print("[随机] 模式已停止")

    def _random_pick_route(self):
        """随机选一个有数据的方案，排除当前方案（避免连续重复）"""
        available = [i for i in range(1, 4) if self._route_has_file(i)]
        if not available:
            return None
        if len(available) > 1 and self._random_route_id in available:
            available = [i for i in available if i != self._random_route_id]
        return random.choice(available)

    def _move_to(self, player_pos, target_x, target_y):
        """移动角色到目标位置（小地图坐标），返回是否到达
        TODO: 需根据游戏实际手感调整阈值、跳跃和爬梯逻辑"""
        if player_pos is None:
            return False
        px, py = player_pos
        dx = target_x - px
        dy = target_y - py

        # 水平移动
        if abs(dx) > 4:
            if dx > 0:
                if VK_LEFT in self._random_move_keys:
                    self._key_up(VK_LEFT)
                if VK_RIGHT not in self._random_move_keys:
                    self._key_down(VK_RIGHT)
            else:
                if VK_RIGHT in self._random_move_keys:
                    self._key_up(VK_RIGHT)
                if VK_LEFT not in self._random_move_keys:
                    self._key_down(VK_LEFT)
        else:
            if VK_LEFT in self._random_move_keys:
                self._key_up(VK_LEFT)
            if VK_RIGHT in self._random_move_keys:
                self._key_up(VK_RIGHT)

        # 垂直差异大时需要爬梯/跳跃（简化处理，需结合梯子数据完善）
        if abs(dx) <= 4 and abs(dy) <= 4:
            return True
        return False

    def _random_step(self, player_pos):
        """随机模式每帧状态机"""
        if not self._random_running:
            return

        if self._random_state == "idle":
            route_id = self._random_pick_route()
            if route_id is None:
                print("[随机] 没有可用方案，自动停止")
                self._stop_random()
                return
            self._switch_route(route_id)
            self._random_route_id = route_id
            self._random_platform_idx = 0
            self._random_state = "moving"
            print("[随机] 选择方案%d（%d平台），开始逐个打" % (route_id, len(self.platforms)))

        elif self._random_state == "moving":
            if self._random_platform_idx >= len(self.platforms):
                # 全部平台打完，回起点
                self._random_state = "returning"
                return
            pf = self.platforms[self._random_platform_idx]
            target_x = (pf["x_min"] + pf["x_max"]) / 2
            target_y = pf["y_base"]
            arrived = self._move_to(player_pos, target_x, target_y)
            if arrived:
                self._release_all_keys()
                self._random_state = "attacking"
                self._random_attack_start = time.time()
                self._key_down(VK_ATTACK)
                print("[随机] 到达平台%d，开始攻击" % self._random_platform_idx)

        elif self._random_state == "attacking":
            # 持续攻击一段时间后前往下一个平台
            if time.time() - self._random_attack_start > 3.0:
                self._key_up(VK_ATTACK)
                self._random_platform_idx += 1
                self._random_state = "moving"
                print("[随机] 平台%d打完，前往下一个" % (self._random_platform_idx - 1))

        elif self._random_state == "returning":
            # 回到起点（第一个平台位置），然后重新随机选方案
            if self.platforms:
                pf = self.platforms[0]
                target_x = (pf["x_min"] + pf["x_max"]) / 2
                target_y = pf["y_base"]
                arrived = self._move_to(player_pos, target_x, target_y)
                if arrived:
                    self._release_all_keys()
                    self._random_state = "idle"
                    print("[随机] 已回起点，重新随机选方案")

    def _capture_window(self):
        r = self.window_rect
        return np.array(self.sct.grab(r))[:, :, :3]

    def _capture_map(self):
        r = self.map_area_rect
        reg = {
            "left": self.window_rect["left"] + r["left"],
            "top": self.window_rect["top"] + r["top"],
            "width": r["width"],
            "height": r["height"]
        }
        return np.array(self.sct.grab(reg))[:, :, :3]

    def find_player_dot(self, map_area):
        hsv = cv2.cvtColor(map_area, cv2.COLOR_BGR2HSV)
        lower = np.array([YELLOW_H_LOW, YELLOW_S_LOW, YELLOW_V_LOW])
        upper = np.array([YELLOW_H_HIGH, 255, 255])
        h, w = map_area.shape[:2]

        if self.last_player_pos:
            cx, cy = self.last_player_pos
            # 坐标超出当前图像范围（自动刷新后区域变小），清空走全图搜索
            if cx < 0 or cy < 0 or cx >= w or cy >= h:
                self.last_player_pos = None
            else:
                x1 = max(0, cx - 12)
                y1 = max(0, cy - 12)
                x2 = min(w, cx + 13)
                y2 = min(h, cy + 13)
                roi_hsv = hsv[y1:y2, x1:x2]
                mask = cv2.inRange(roi_hsv, lower, upper)
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
                cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 30]
                if valid:
                    largest = max(valid, key=cv2.contourArea)
                    M = cv2.moments(largest)
                    if M["m00"] > 0:
                        px = int(M["m10"] / M["m00"]) + x1
                        py = int(M["m01"] / M["m00"]) + y1
                        self.last_player_pos = (px, py)
                        return (px, py)

        mask = cv2.inRange(hsv, lower, upper)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 30]
        if valid:
            largest = max(valid, key=cv2.contourArea)
            M = cv2.moments(largest)
            if M["m00"] > 0:
                px = int(M["m10"] / M["m00"])
                py = int(M["m01"] / M["m00"])
                self.last_player_pos = (px, py)
                return (px, py)
        self.last_player_pos = None
        return None

    def extract_platform(self, points):
        if len(points) < 2:
            return []
        ys = sorted(set(int(p[1] // 3) * 3 for p in points))
        clusters = []
        cur = [ys[0]]
        for y in ys[1:]:
            if y - cur[-1] <= 6:
                cur.append(y)
            else:
                clusters.append(cur)
                cur = [y]
        clusters.append(cur)
        platforms = []
        for cl in clusters:
            cp = [p for p in points if int(p[1] // 3) * 3 in cl]
            if len(cp) < 2:
                continue
            xs = [p[0] for p in cp]
            y_base = sum(p[1] for p in cp) / len(cp)
            platforms.append({
                "id": len(self.platforms) + len(platforms),
                "x_min": float(min(xs)),
                "x_max": float(max(xs)),
                "y_base": float(y_base)
            })
        return platforms

    def extract_ladder(self, points):
        if len(points) < 2:
            return []
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return [{
            "id": len(self.ladders),
            "x": float(sorted(xs)[len(xs) // 2]),
            "y_top": float(min(ys)),
            "y_bottom": float(max(ys))
        }]

    def _check_hotkeys(self):
        """GetAsyncKeyState 轮询，按下瞬间触发一次"""
        for vk in [VK_F5, VK_F6, VK_F7, VK_F8, VK_F9]:
            pressed = bool(user32.GetAsyncKeyState(vk) & 0x8000)
            if pressed and not self._key_state[vk]:
                self._handle_hotkey(vk)
            self._key_state[vk] = pressed

    def _handle_hotkey(self, vk):
        if vk == VK_F5:
            if self.recording_ladder:
                print("Stop ladder first (F6)")
            elif self.recording_platform:
                np_ = self.extract_platform(self.platform_points)
                if np_:
                    self.platforms.extend(np_)
                    print("Extracted", len(np_), "platforms,", len(self.platform_points), "points")
                else:
                    print("No platform extracted,", len(self.platform_points), "points")
                self.platform_points = []
                self.recording_platform = False
            else:
                self.recording_platform = True
                self.platform_points = []
                print("Platform recording started...")
        elif vk == VK_F6:
            if self.recording_platform:
                print("Stop platform first (F5)")
            elif self.recording_ladder:
                nl = self.extract_ladder(self.ladder_points)
                if nl:
                    self.ladders.extend(nl)
                    print("Extracted", len(nl), "ladders,", len(self.ladder_points), "points")
                else:
                    print("No ladder extracted,", len(self.ladder_points), "points")
                self.ladder_points = []
                self.recording_ladder = False
            else:
                self.recording_ladder = True
                self.ladder_points = []
                print("Ladder recording started...")
        elif vk == VK_F7:
            self.platform_points = []
            self.ladder_points = []
            self.platforms = []
            self.ladders = []
            print("Cleared all (points + saved platforms/ladders)")
        elif vk == VK_F8:
            self._save()
        elif vk == VK_F9:
            print("Manual select triggered (F9)")
            self.manual_select_region()

    def _on_mouse(self, event, x, y, flags, param):
        """鼠标点击回调：左上角文字 + 两排按钮 + 下拉菜单"""
        # 手动框选模式：pynput全局监听鼠标，这里只处理按钮点击
        if self._selecting:
            if y < 22:
                # 左上角文字按钮区域，只响应左键按下
                if event == cv2.EVENT_LBUTTONDOWN and x < 48:
                    # 点刷新：退出框选模式，恢复正常显示和自动刷新
                    self._stop_select_listener()
                    self._selecting = False
                    self._select_rect = None
                    self._select_dragging = False
                    if hasattr(self, '_win_name'):
                        cv2.setWindowProperty(self._win_name, cv2.WND_PROP_TOPMOST, 0)
                # 放行到下面正常处理刷新/手动按钮（下方有LBUTTONDOWN检查）
            elif y >= MAP_H:
                # 点到按钮区，退出框选模式，继续处理按钮点击
                if event == cv2.EVENT_LBUTTONDOWN:
                    self._stop_select_listener()
                    self._selecting = False
                    self._select_rect = None
                    self._select_dragging = False
                    if hasattr(self, '_win_name'):
                        cv2.setWindowProperty(self._win_name, cv2.WND_PROP_TOPMOST, 0)
                    if getattr(self, '_was_random_running', False) and self.route_mode == "随机":
                        self._start_random()
            else:
                # 地图区域：拖拽在游戏窗口上通过pynput监听处理，这里不处理
                return

        if event != cv2.EVENT_LBUTTONDOWN:
            return

        BTN_W = FIXED_W // 4
        ITEM_H = 24

        # 1. 如果有下拉菜单展开，优先处理菜单点击
        if self._dropdown is not None:
            btn_idx_map = {"save": 2, "route": 3, "mode": 2, "clear_route": 3}
            btn_idx = btn_idx_map[self._dropdown]
            mx1 = btn_idx * BTN_W
            mx2 = (btn_idx + 1) * BTN_W
            items = self._dropdown_items()
            n = len(items)
            menu_y1 = MAP_H - n * ITEM_H
            menu_y2 = MAP_H
            if mx1 <= x < mx2 and menu_y1 <= y < menu_y2:
                item_idx = (y - menu_y1) // ITEM_H
                if 0 <= item_idx < n:
                    self._handle_dropdown_item(self._dropdown, item_idx)
                self._dropdown = None
                return
            # 点了触发按钮本身 → 关闭下拉，不继续处理按钮点击
            if mx1 <= x < mx2 and y >= MAP_H:
                self._dropdown = None
                return
            # 点了菜单外其他地方 → 收起，继续处理本次点击
            self._dropdown = None

        # 2. 左上角文字按钮（地图区域内，y<22）
        if y < 22:
            if x < 48:
                print("[鼠标] 刷新-重新检测（自动刷新已开启）")
                self._auto_refresh = True
                self._detect_minimap()
                self.frame_count = 0
                self.last_player_pos = None
                return
            elif 50 <= x < 98:
                print("[鼠标] 手动框选")
                self.manual_select_region()
                return
        if y < MAP_H:
            return

        # 3. 第一排按钮（平台/梯子/保存▼/方案▼）
        if MAP_H <= y < MAP_H + BTN_ROW_H:
            idx = x // BTN_W
            if idx == 0:
                print("[鼠标] 平台")
                self._handle_hotkey(VK_F5)
            elif idx == 1:
                print("[鼠标] 梯子")
                self._handle_hotkey(VK_F6)
            elif idx == 2:
                self._dropdown = "save" if self._dropdown != "save" else None
            elif idx == 3:
                self._dropdown = "route" if self._dropdown != "route" else None
            return

        # 4. 第二排按钮（清除绿/清除蓝/模式▼/清除橙▼）
        if MAP_H + BTN_ROW_H <= y < MAP_H + BTN_BAR_H:
            idx = x // BTN_W
            if idx == 0:
                self._pop_platform()
            elif idx == 1:
                self._pop_ladder()
            elif idx == 2:
                self._dropdown = "mode" if self._dropdown != "mode" else None
            elif idx == 3:
                self._dropdown = "clear_route" if self._dropdown != "clear_route" else None
            return

    def draw(self, map_area, player_pos):
        display = map_area.copy()
        h, w = display.shape[:2]
        for p in self.platforms:
            x1 = int(max(0, min(p["x_min"], w - 1)))
            x2 = int(max(0, min(p["x_max"], w - 1)))
            y = int(max(0, min(p["y_base"], h - 1)))
            cv2.line(display, (x1, y), (x2, y), COLOR_PLATFORM, 1)
        for l in self.ladders:
            x = int(max(0, min(l["x"], w - 1)))
            y1 = int(max(0, min(l["y_top"], h - 1)))
            y2 = int(max(0, min(l["y_bottom"], h - 1)))
            cv2.line(display, (x, y1), (x, y2), COLOR_LADDER, 1)
        if self.recording_platform and len(self.platform_points) > 1:
            cv2.polylines(display, [np.array(self.platform_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        if self.recording_ladder and len(self.ladder_points) > 1:
            cv2.polylines(display, [np.array(self.ladder_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        if player_pos:
            cv2.circle(display, player_pos, 2, COLOR_PLAYER, -1)
            cv2.circle(display, player_pos, 4, (0, 0, 255), 1)
        map_display = cv2.resize(display, (FIXED_W, MAP_H), interpolation=cv2.INTER_NEAREST)

        # 随机模式运行状态（底部）
        if self._random_running:
            state_text = {"idle": "选方案中", "moving": "移动中", "attacking": "攻击中", "returning": "返回起点"}.get(self._random_state, self._random_state)
            progress = "%d/%d" % (min(self._random_platform_idx + 1, len(self.platforms)), len(self.platforms)) if self.platforms else "0/0"
            status = "随机: %s 平台%s" % (state_text, progress)
            cv2.rectangle(map_display, (0, MAP_H - 20), (FIXED_W, MAP_H), (25, 25, 25), -1)
            cv2.putText(map_display, status, (6, MAP_H - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1)

        BTN_W = FIXED_W // 4

        # === 左上角文字按钮：刷新 / 手动 / 方案X（录制）或 随机 ===
        cv2.rectangle(map_display, (0, 0), (195, 22), (25, 25, 25), -1)
        refresh_color = (0, 255, 0) if self._auto_refresh else (0, 165, 255)
        cv2.putText(map_display, "刷新", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, refresh_color, 1)
        cv2.putText(map_display, "手动", (52, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
        if self.route_mode == "随机":
            cv2.putText(map_display, "随机", (100, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
        else:
            route_text = "方案" + "一二三"[self.current_route - 1]
            cv2.putText(map_display, route_text, (100, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)

        # === 按钮栏整图 ===
        if self._btn_bar_img is not None:
            btn_bar = self._btn_bar_img.copy()
        else:
            btn_bar = np.zeros((BTN_BAR_H, FIXED_W, 3), dtype=np.uint8)
            btn_bar[:] = (40, 40, 40)

        # 录制中：左上角闪烁红点
        # 下拉展开：按钮底部 2px 高亮线
        def overlay_recording(canvas, row, col):
            x1 = col * BTN_W
            y1 = row * BTN_ROW_H
            # 左上角闪烁红点（每15帧切换）
            if (self.frame_count // 15) % 2 == 0:
                cv2.circle(canvas, (x1 + 8, y1 + 8), 4, (0, 0, 255), -1)
                cv2.circle(canvas, (x1 + 8, y1 + 8), 5, (0, 0, 255), 1)

        def underline_dropdown(canvas, row, col):
            x1 = col * BTN_W
            y2 = (row + 1) * BTN_ROW_H
            x2 = (col + 1) * BTN_W
            cv2.line(canvas, (x1 + 4, y2 - 2), (x2 - 5, y2 - 2), (0, 165, 255), 2)

        if self.recording_platform:
            overlay_recording(btn_bar, 0, 0)
        elif self.recording_ladder:
            overlay_recording(btn_bar, 0, 1)
        if self._dropdown == "save":
            underline_dropdown(btn_bar, 0, 2)
        if self._dropdown == "route":
            underline_dropdown(btn_bar, 0, 3)
        if self._dropdown == "mode":
            underline_dropdown(btn_bar, 1, 2)
        if self._dropdown == "clear_route":
            underline_dropdown(btn_bar, 1, 3)

        full = np.vstack([map_display, btn_bar])

        # === 下拉菜单（覆盖在地图底部，从 MAP_H 向上展开）===
        if self._dropdown is not None:
            items = self._dropdown_items()
            n = len(items)
            ITEM_H = 24
            btn_idx_map = {"save": 2, "route": 3, "mode": 2, "clear_route": 3}
            btn_idx = btn_idx_map[self._dropdown]
            mx1 = btn_idx * BTN_W
            mx2 = (btn_idx + 1) * BTN_W
            menu_h = n * ITEM_H
            menu_y1 = MAP_H - menu_h

            # 菜单背景
            cv2.rectangle(full, (mx1, menu_y1), (mx2 - 1, MAP_H - 1), (58, 58, 58), -1)
            cv2.rectangle(full, (mx1, menu_y1), (mx2 - 1, MAP_H - 1), (110, 110, 110), 1)

            for i, text in enumerate(items):
                iy = menu_y1 + i * ITEM_H
                # 分隔线
                if i > 0:
                    cv2.line(full, (mx1 + 3, iy), (mx2 - 4, iy), (85, 85, 85), 1)
                # 当前选中项高亮
                is_current = False
                if self._dropdown == "route" and (i + 1) == self.current_route:
                    is_current = True
                elif self._dropdown == "mode" and text == self.route_mode:
                    is_current = True
                if is_current:
                    cv2.rectangle(full, (mx1 + 1, iy + 1), (mx2 - 2, iy + ITEM_H - 1), (0, 70, 0), -1)
                # 文字
                color = (0, 255, 0) if is_current else (240, 240, 240)
                cv2.putText(full, text, (mx1 + 6, iy + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1)

        return full

    def manual_select_region(self):
        """手动框选：pynput全局鼠标监听，在游戏窗口上拖拽框选，松开确认，Esc取消"""
        self._was_random_running = self._random_running
        if self._random_running:
            self._stop_random()
        self._update_window_rect()
        self._selecting = True
        self._select_rect = None
        self._select_dragging = False
        self._select_wait_release = True

        def _in_game(x, y):
            wr = self.window_rect
            return wr["left"] <= x < wr["left"] + wr["width"] and wr["top"] <= y < wr["top"] + wr["height"]

        def _to_game(x, y):
            wr = self.window_rect
            return x - wr["left"], y - wr["top"]

        def on_click(x, y, button, pressed):
            print("[pynput] click x=%d y=%d btn=%s pressed=%s wait_release=%s" % (x, y, button, pressed, self._select_wait_release))
            if button != mouse.Button.left:
                return
            if self._select_wait_release:
                if not pressed:
                    self._select_wait_release = False
                    print("[pynput] released, ready to drag")
                return
            if pressed:
                if _in_game(x, y):
                    gx, gy = _to_game(x, y)
                    self._select_dragging = True
                    self._select_rect = (gx, gy, gx, gy)
                    print("[pynput] drag start at game (%d,%d)" % (gx, gy))
                else:
                    print("[pynput] click outside game window")
            else:
                if self._select_dragging:
                    self._select_dragging = False
                    print("[pynput] drag end, confirming")
                    self._confirm_select()

        def on_move(x, y):
            if self._select_dragging and not self._select_wait_release:
                gx, gy = _to_game(x, y)
                rx1, ry1, _, _ = self._select_rect
                self._select_rect = (rx1, ry1, gx, gy)

        self._select_listener = mouse.Listener(on_click=on_click, on_move=on_move)
        self._select_listener.start()
        print("[pynput] mouse listener started")

        if hasattr(self, '_win_name'):
            cv2.setWindowProperty(self._win_name, cv2.WND_PROP_TOPMOST, 1)
        print("\n=== 手动框选 ===")
        print("先松开鼠标，再在游戏窗口上拖拽框选小地图，松开自动确认，按 Esc 取消")

    def _stop_select_listener(self):
        if hasattr(self, '_select_listener') and self._select_listener:
            self._select_listener.stop()
            self._select_listener = None

    def _confirm_select(self):
        """确认框选（松开鼠标自动调用），坐标为游戏窗口坐标"""
        self._stop_select_listener()
        if not self._select_rect:
            return
        x1, y1, x2, y2 = self._select_rect
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        w = x2 - x1
        h = y2 - y1
        if w < 20 or h < 20:
            print("选择区域太小，请重新拉取")
            self._select_rect = None
            return
        # 坐标已经是游戏窗口坐标，直接使用
        self.minimap_rect = {"left": x1, "top": y1, "width": w, "height": h}
        pad_l, pad_t, pad_r, pad_b = 8, 2, 2, 2
        self.map_area_rect = {
            "left": x1 + pad_l, "top": y1 + pad_t,
            "width": w - pad_l - pad_r, "height": h - pad_t - pad_b
        }
        self._save_region()
        self.frame_count = 0
        self.last_player_pos = None
        # 手动框选后关闭自动刷新，避免被覆盖
        self._auto_refresh = False
        # 应用后退出框选模式，立即显示新小地图
        self._selecting = False
        self._select_rect = None
        if hasattr(self, '_win_name'):
            cv2.setWindowProperty(self._win_name, cv2.WND_PROP_TOPMOST, 0)
        if getattr(self, '_was_random_running', False) and self.route_mode == "随机":
            self._start_random()
        print("已应用: (%d,%d) %dx%d（自动刷新已关闭，点刷新可重新开启）" % (x1, y1, w, h))

    def run(self):
        win = "Minimap Route"
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(win, self._on_mouse)
        self._win_name = win
        self._win_size = (FIXED_W, FIXED_H)
        while True:
            # 手动框选模式：pynput全局鼠标监听，脚本窗口置顶同步显示
            if self._selecting:
                self._update_window_rect()
                frame = self._capture_window()
                fh, fw = frame.shape[:2]
                display = cv2.resize(frame, (FIXED_W, MAP_H), interpolation=cv2.INTER_AREA)
                sx = FIXED_W / fw
                sy = MAP_H / fh

                # 左上角完整UI
                cv2.rectangle(display, (0, 0), (195, 22), (25, 25, 25), -1)
                refresh_color = (0, 255, 0) if self._auto_refresh else (0, 165, 255)
                cv2.putText(display, "刷新", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, refresh_color, 1)
                cv2.putText(display, "手动", (52, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
                if self.route_mode == "随机":
                    cv2.putText(display, "随机", (100, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
                else:
                    route_text = "方案" + "一二三"[self.current_route - 1]
                    cv2.putText(display, route_text, (100, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)

                # 拖拽框（游戏窗口坐标映射到显示坐标）
                if self._select_rect:
                    gx1, gy1, gx2, gy2 = self._select_rect
                    dx1, dy1 = int(gx1 * sx), int(gy1 * sy)
                    dx2, dy2 = int(gx2 * sx), int(gy2 * sy)
                    dx1, dx2 = min(dx1, dx2), max(dx1, dx2)
                    dy1, dy2 = min(dy1, dy2), max(dy1, dy2)
                    cv2.rectangle(display, (dx1, dy1), (dx2, dy2), (0, 255, 0), 2)

                cv2.putText(display, "Release mouse first, then drag on GAME window",
                            (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
                cv2.imshow(win, display)
                key = cv2.waitKey(20) & 0xFF
                if key == 27:  # Esc 取消
                    self._stop_select_listener()
                    self._selecting = False
                    self._select_rect = None
                    self._select_dragging = False
                    if hasattr(self, '_win_name'):
                        cv2.setWindowProperty(self._win_name, cv2.WND_PROP_TOPMOST, 0)
                    if getattr(self, '_was_random_running', False) and self.route_mode == "随机":
                        self._start_random()
                    print("取消框选")
                continue

            try:
                map_area = self._capture_map()
            except Exception:
                time.sleep(0.05)
                continue

            # 窗口被关掉后自动重建
            try:
                cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE)
            except Exception:
                cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
                cv2.setMouseCallback(win, self._on_mouse)

            # 调试：保存实际截取的地图区域（只存一次）
            if self.frame_count == 0:
                cv2.imwrite("debug_map_area.png", map_area)
                print("Captured map_area:", map_area.shape[1], "x", map_area.shape[0])

            self.frame_count += 1
            # 每30帧自动重新检测小地图区域（仅自动刷新模式下，手动模式不覆盖）
            if self._auto_refresh and self.frame_count % 30 == 0:
                self._detect_minimap(debug=False)
            if self.frame_count % 2 == 0 or self.last_player_pos is None:
                player_pos = self.find_player_dot(map_area)
            else:
                player_pos = self.last_player_pos

            if self.recording_platform and player_pos:
                self.platform_points.append(player_pos)
            if self.recording_ladder and player_pos:
                self.ladder_points.append(player_pos)

            # 随机模式运行
            self._random_step(player_pos)

            cv2.imshow(win, self.draw(map_area, player_pos))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                self._stop_random()
                break
            elif key == ord('r'):
                print("Redetecting...")
                self._detect_minimap()
            elif key == ord('n'):
                self.manual_select_region()
        cv2.destroyAllWindows()
        print("Final:", len(self.platforms), "platforms,", len(self.ladders), "ladders")


if __name__ == "__main__":
    MinimapRouteRecorder().run()
