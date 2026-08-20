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
import subprocess
import queue
import random

def _debug_log(msg):
    """写调试日志到文件，exe无控制台时用"""
    try:
        with open(os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else ".", "debug.log"), "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass

# 无缓冲输出，方便实时看日志（windowed模式下stdout为None，跳过）
if sys.stdout is not None:
    sys.stdout.reconfigure(line_buffering=True)

def resource_path(relative_path):
    """获取资源文件路径，兼容PyInstaller打包"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def app_dir():
    """获取程序所在目录（用于可写数据），兼容PyInstaller"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

os.chdir(app_dir())

DISPLAY_SCALE = 1
WINDOW_TITLE = "冒险岛怀旧服"
WINDOW_KEYWORDS = ["冒险岛"]  # 自动绑定只匹配冒险岛，其他窗口用准星手动绑定
_enum_result = []

@ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
def _enum_windows_cb(hwnd, lparam):
    try:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0 and length < 500:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                for kw in WINDOW_KEYWORDS:
                    if kw in title:
                        _enum_result.append((hwnd, title))
                        break
    except Exception:
        pass
    return True

def _find_game_window():
    """枚举所有顶层窗口，找标题包含关键词的游戏窗口"""
    global _enum_result
    _enum_result = []
    try:
        user32.EnumWindows(_enum_windows_cb, 0)
    except Exception as e:
        print("[窗口枚举] 异常:", e)
        return None
    if _enum_result:
        for hwnd, title in _enum_result:
            if "冒险岛" in title:
                return hwnd
        return _enum_result[0][0]
    return None
# 内部小地图渲染尺寸（渲染后缩放到UI区域）
FIXED_W = 340
MAP_H = 250
BTN_BAR_H = 77
BTN_ROW_H = BTN_BAR_H // 2
BTN_COLS = 4
BTN_W = FIXED_W // BTN_COLS
FIXED_H = MAP_H + BTN_BAR_H
DROPDOWN_ITEM_H = 24

# === UI 整体尺寸 ===
UI_W = 330
UI_H = 566

# === 小地图合成区域（在UI背景图中的位置，等比缩放）===
UI_MAP_SCALE = 300 / FIXED_W  # 0.882
UI_MAP_W = 300
UI_MAP_H = 215
UI_MAP_X = 15
UI_MAP_Y = 71

# === 底部按钮区域 ===
UI_BTN_COL_W = 75
UI_BTN_GAP = 0
UI_BTN_START_X = 15
UI_BTN_ROW1_Y = 296
UI_BTN_ROW2_Y = 329
UI_BTN_H = 33

# === 运行/停止按钮 ===
UI_RUN_X = 15
UI_RUN_Y = 375
UI_RUN_W = 140
UI_RUN_H = 43
UI_STOP_X = 175
UI_STOP_Y = 375
UI_STOP_W = 140
UI_STOP_H = 43

# === 子标签页（人物特征/特征清除/怪物数据）===
UI_SUBTAB_Y = 430
UI_SUBTAB_H = 36
UI_SUBTAB_W = 92

# === 日志区域 ===
UI_LOG_X = 123
UI_LOG_Y = 474
UI_LOG_W = 195
UI_LOG_H = 80

# === 窗口绑定按钮 ===
UI_WINBIND_X = 15
UI_WINBIND_Y = 474
UI_WINBIND_W = 100
UI_WINBIND_H = 33

# === 已绑窗口下拉按钮 ===
UI_BOUND_X = 15
UI_BOUND_Y = 513
UI_BOUND_W = 100
UI_BOUND_H = 23
YELLOW_H_LOW = 25
YELLOW_H_HIGH = 35
YELLOW_S_LOW = 120
YELLOW_V_LOW = 180

VK_F5 = 0x74
VK_F6 = 0x75
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78
VK_F10 = 0x79
VK_F12 = 0x7B

# 游戏控制按键（冒险岛默认，可根据实际设置调整）
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_UP = 0x26
VK_DOWN = 0x28
VK_JUMP = 0x20   # Space
VK_ATTACK = 0x11  # Ctrl

DATA_DIR = os.path.join(app_dir(), "data")
os.makedirs(DATA_DIR, exist_ok=True)
REGION_FILE = os.path.join(DATA_DIR, "minimap_region.json")
ROUTE_CONFIG_FILE = os.path.join(DATA_DIR, "route_config.json")

# === 人物特征模板 ===
CHAR_TEMPLATE_DIR = os.path.join(DATA_DIR, "char_templates")
os.makedirs(CHAR_TEMPLATE_DIR, exist_ok=True)
CHAR_TEMPLATE_META = os.path.join(CHAR_TEMPLATE_DIR, "meta.json")
CHAR_MAX_TEMPLATES = 10
CHAR_MATCH_THRESHOLD = 0.75

# === 打怪/药品 输入框配置 ===
INPUT_CONFIG_FILE = os.path.join(DATA_DIR, "fight_potion_config.json")
INPUT_FONT = cv2.FONT_HERSHEY_SIMPLEX
INPUT_FONT_SCALE = 0.5
INPUT_FONT_THICKNESS = 1
INPUT_TEXT_COLOR = (40, 40, 40)  # BGR 深色文字
INPUT_FOCUS_COLOR = (0, 170, 255)  # BGR 橙色聚焦边框

# 打怪页字段定义 (x, y, w, h, type, id) — 坐标由白色方框自动检测，缩放到330x566
# type: "key"=按键录入, "num"=数字录入
FIGHT_FIELDS = [
    # 主攻
    (73, 102, 31, 19, "key", "atk1_key"),
    (151, 101, 72, 21, "num", "atk1_interval"),
    (270, 101, 47, 21, "num", "atk1_distance"),
    # 群攻
    (73, 132, 31, 19, "key", "aoe_key"),
    (151, 130, 73, 22, "num", "aoe_interval"),
    (270, 129, 47, 22, "num", "aoe_distance"),
    # 跳跃 + 技能随机时间
    (73, 169, 31, 19, "key", "jump_key"),
    (232, 163, 84, 20, "num", "skill_random"),
    # 瞬移
    (73, 199, 31, 19, "key", "teleport_key"),
    # BUFF 1-6
    (73, 283, 26, 21, "key", "buff1_key"),
    (140, 283, 84, 21, "num", "buff1_cd"),
    (258, 284, 60, 21, "num", "buff1_delay"),
    (73, 319, 26, 21, "key", "buff2_key"),
    (140, 319, 84, 21, "num", "buff2_cd"),
    (258, 319, 60, 21, "num", "buff2_delay"),
    (73, 351, 26, 21, "key", "buff3_key"),
    (140, 351, 84, 21, "num", "buff3_cd"),
    (258, 350, 60, 21, "num", "buff3_delay"),
    (73, 383, 26, 21, "key", "buff4_key"),
    (140, 383, 84, 21, "num", "buff4_cd"),
    (258, 383, 60, 21, "num", "buff4_delay"),
    (73, 414, 26, 21, "key", "buff5_key"),
    (140, 414, 84, 21, "num", "buff5_cd"),
    (258, 414, 60, 21, "num", "buff5_delay"),
    (73, 445, 26, 21, "key", "buff6_key"),
    (140, 445, 84, 21, "num", "buff6_cd"),
    (258, 445, 60, 21, "num", "buff6_delay"),
    # BUFF技能随机时间
    (163, 480, 130, 20, "num", "buff_random"),
]

# 药品页字段定义 (x, y, w, h, type, id)
POTION_FIELDS = [
    # Hp / Mp / 宠物食
    (103, 120, 36, 32, "key", "hp_key"),
    (230, 122, 84, 28, "num", "hp_value"),
    (103, 157, 36, 32, "key", "mp_key"),
    (230, 159, 84, 28, "num", "mp_value"),
    (103, 200, 36, 32, "key", "pet_key"),
    (196, 200, 117, 28, "num", "pet_cd"),
    # 1-5按键（冷却框加宽）
    (94, 249, 36, 32, "key", "pot1_key"),
    (174, 252, 143, 28, "num", "pot1_cd"),
    (94, 292, 36, 32, "key", "pot2_key"),
    (174, 294, 143, 27, "num", "pot2_cd"),
    (94, 335, 36, 30, "key", "pot3_key"),
    (174, 336, 143, 28, "num", "pot3_cd"),
    (94, 377, 36, 30, "key", "pot4_key"),
    (174, 378, 143, 28, "num", "pot4_cd"),
    (94, 420, 36, 30, "key", "pot5_key"),
    (174, 421, 143, 28, "num", "pot5_cd"),
    # 药品技能随机时间
    (145, 478, 160, 24, "num", "potion_random"),
]

# 按钮颜色 (BGR)
BTN_GREEN = (0, 165, 0)
BTN_BLUE = (210, 130, 0)
BTN_BLACK = (48, 48, 48)
BTN_ORANGE = (0, 135, 225)
BTN_WHITE = (255, 255, 255)

# 完整虚拟键码→键名映射（用于GetAsyncKeyState按键捕获）
VK_TO_NAME = {
    0x08: "backspace", 0x09: "tab", 0x0C: "clear", 0x0D: "enter",
    0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0x13: "pause",
    0x14: "capslock", 0x1B: "esc", 0x20: "space",
    0x21: "pgup", 0x22: "pgdn", 0x23: "end", 0x24: "home",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x2C: "printscreen", 0x2D: "insert", 0x2E: "delete",
    0x30: "0", 0x31: "1", 0x32: "2", 0x33: "3", 0x34: "4",
    0x35: "5", 0x36: "6", 0x37: "7", 0x38: "8", 0x39: "9",
    0x41: "a", 0x42: "b", 0x43: "c", 0x44: "d", 0x45: "e",
    0x46: "f", 0x47: "g", 0x48: "h", 0x49: "i", 0x4A: "j",
    0x4B: "k", 0x4C: "l", 0x4D: "m", 0x4E: "n", 0x4F: "o",
    0x50: "p", 0x51: "q", 0x52: "r", 0x53: "s", 0x54: "t",
    0x55: "u", 0x56: "v", 0x57: "w", 0x58: "x", 0x59: "y", 0x5A: "z",
    0x5B: "lwin", 0x5C: "rwin",
    0x60: "num0", 0x61: "num1", 0x62: "num2", 0x63: "num3",
    0x64: "num4", 0x65: "num5", 0x66: "num6", 0x67: "num7",
    0x68: "num8", 0x69: "num9",
    0x6A: "num*", 0x6B: "num+", 0x6C: "numsep", 0x6D: "num-",
    0x6E: "num.", 0x6F: "num/",
    0x70: "f1", 0x71: "f2", 0x72: "f3", 0x73: "f4", 0x74: "f5",
    0x75: "f6", 0x76: "f7", 0x77: "f8", 0x78: "f9", 0x79: "f10",
    0x7A: "f11", 0x7B: "f12",
    0x90: "numlock", 0x91: "scrolllock",
    0xA0: "lshift", 0xA1: "rshift", 0xA2: "lctrl", 0xA3: "rctrl",
    0xA4: "lalt", 0xA5: "ralt",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".",
    0xBF: "/", 0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}
# 轮询捕获时检测的键码列表（按优先级排序，修饰键放后面避免误触）
VK_POLL_LIST = (
    [0x70+i for i in range(4)] +  # F1-F4 (F5-F12留作热键不捕获)
    [0x30+i for i in range(10)] +  # 0-9
    [0x41+i for i in range(26)] +  # A-Z
    [0x60+i for i in range(10)] +  # num0-9
    [0x20, 0x0D, 0x09] +  # space enter tab (backspace/esc单独处理不捕获)
    [0x21, 0x22, 0x23, 0x24, 0x2D, 0x2E] +  # pgup pgdn end home insert delete
    # 方向键/ScrollLock/Pause/PrintScreen 不捕获，避免冲突
    [0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE] +  # 符号
    [0x6A, 0x6B, 0x6D, 0x6E, 0x6F] +  # 小键盘运算
    [0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5]  # 左右修饰键
)

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
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.GetParent.argtypes = [ctypes.c_void_p]
user32.GetParent.restype = ctypes.c_void_p


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


class GlobalMouseListener:
    """低级鼠标钩子（主线程版），全局捕获鼠标事件，游戏前台也能捕获"""
    WH_MOUSE_LL = 14
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP = 0x0202
    WM_MOUSEMOVE = 0x0200

    def __init__(self):
        self.events = queue.Queue()
        self._hook = None
        self._hook_proc_ref = None

    def _hook_proc(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam in (self.WM_LBUTTONDOWN, self.WM_LBUTTONUP, self.WM_MOUSEMOVE):
            ms = ctypes.cast(lParam, ctypes.POINTER(POINT))[0]
            self.events.put((wParam, ms.x, ms.y))
        return user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

    def install(self):
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p)
        self._hook_proc_ref = HOOKPROC(self._hook_proc)
        kernel32 = ctypes.windll.kernel32
        self._hook = user32.SetWindowsHookExW(
            self.WH_MOUSE_LL, self._hook_proc_ref,
            kernel32.GetModuleHandleW(None), 0
        )
        return bool(self._hook)

    def pump(self):
        msg = ctypes.c_void_p()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            if msg.value == 0x0012:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def get_events(self):
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                break
        return events

    def uninstall(self):
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None




class MinimapRouteRecorder:
    def __init__(self):
        self.sct = mss.mss()
        try:
            self.hwnd = _find_game_window()
            if self.hwnd:
                self._update_window_rect()
                self._detect_minimap()
                self._save_target_window_size()
                print("[窗口绑定] 自动绑定成功")
            else:
                print("[警告] 未找到游戏窗口，请用准星拖拽绑定")
                self.hwnd = None
                self.window_rect = None
                self.map_area_rect = None
        except Exception as e:
            print("[窗口绑定] 自动绑定异常:", e)
            self.hwnd = None
            self.window_rect = None
            self.map_area_rect = None

        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []

        # 方案系统：当前方案(1-3) + 运行方式(手动/随机)
        self.current_route = 1
        self.route_mode = "手动"
        self._dropdown = None  # 当前展开的下拉菜单: None/"save"/"route"/"mode"/"clear_route"
        # 可拖拽准星（窗口绑定用）
        self._crosshair_size = 18
        self._crosshair_home = (88, 490)  # 窗口绑定按钮圆形区域居中（右移3px对齐）
        self._crosshair_pos = self._crosshair_home
        self._drag_crosshair = False
        # 已绑窗口列表
        self._bound_windows = []  # [{hwnd, title}]
        self._bound_dropdown = False
        # 窗口大小固定：绑定时记录目标大小，运行中监控拉回
        self._target_window_size = None  # (width, height) 或 None
        # 人物特征模板（最多10套）
        self._char_templates = []  # [{id, img(numpy), width, height, created_at}]
        self._load_char_templates()
        # 打怪/药品输入框状态
        self._field_values = {}  # {field_id: value_string}
        self._focused_field = None  # 当前聚焦的字段id
        self._load_input_config()
        # HP/MP自动吃药状态
        self._hp_bar = None  # (x, y, w) 扫描线
        self._mp_bar = None
        self._last_hp_pot = 0  # 上次吃红时间戳
        self._last_mp_pot = 0
        self._hp_pot_delay = 1  # 吃红后延时(ms)，1-20毫秒随机
        self._mp_pot_delay = 1
        self._last_pot_check = 0
        self._auto_potion_enabled = True
        self._max_hp = 0  # 检测到的HP上限，0=未知
        self._max_mp = 0
        self._digit_templates = {}  # 0-9数字模板
        self._last_max_check = 0
        # YOLO怪物检测
        self._yolo_net = None
        self._monsters = []  # [(x1,y1,x2,y2,score), ...]
        self._last_yolo_check = 0
        self._yolo_conf = 0.4
        self._yolo_nms = 0.45
        # YOLO怪物检测
        self._yolo_net = None
        self._monsters = []  # [(x1,y1,x2,y2,score), ...]
        self._last_yolo_check = 0
        self._yolo_conf = 0.4
        self._yolo_nms = 0.45
        # BUFF/药品冷却状态（启动后生效）
        self._buff_last = {}  # buffN_key -> 上次释放时间戳
        self._potion_last = {}  # potionN_key -> 上次释放时间戳
        self._prev_key_states = set()  # 按键捕获轮询用
        # 按键捕获状态（GetAsyncKeyState轮询）
        self._prev_key_states = set()  # 上一轮已按下的键码集合
        self._last_periodic_pot = {}  # {pot_key: last_use_ms} 周期性吃药记录
        self._load_route_config()
        pf_file, ld_file = route_files(self.current_route)
        self.platforms = self._load(pf_file, "platforms")
        self.ladders = self._load(ld_file, "ladders")

        # 加载按钮栏整图
        self._btn_bar_img = None
        btn_path = resource_path(os.path.join("data", "templates", "btn_bar.png"))
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
        self._key_state = {vk: False for vk in [VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10, VK_F12]}
        self._running = False  # 脚本运行状态，F10启动 F12停止
        self._last_input_change = 0  # 输入框最后修改时间，用于3秒自动失焦

        # 加载UI背景图（五个标签页）
        self._ui_bgs = {}
        for tab, fname in [("route", "ui_route.png"), ("fight", "ui_tab_fight.png"),
                           ("potion", "ui_tab_potion.png"), ("chat", "ui_tab_chat.png"),
                           ("lie", "ui_tab_lie.png")]:
            p = resource_path(fname)
            img = cv2.imread(p)
            if img is not None:
                self._ui_bgs[tab] = cv2.resize(img, (UI_W, UI_H))
            else:
                self._ui_bgs[tab] = np.ones((UI_H, UI_W, 3), dtype=np.uint8) * 200
        self._ui_bg = self._ui_bgs["route"]
        self._current_tab = "route"

        # 顶部标签页点击区域
        self._tab_areas = {
            "route": (5, 34, 75, 36),
            "fight": (82, 34, 60, 36),
            "potion": (145, 34, 60, 36),
            "chat": (207, 34, 58, 36),
            "lie": (266, 34, 58, 36),
        }

        # 日志
        self._logs = []

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

    def _save_target_window_size(self):
        """记录当前窗口大小为目标大小（绑定成功后调用）"""
        if self.hwnd and self.window_rect:
            self._target_window_size = (self.window_rect["width"], self.window_rect["height"])
            print("[窗口固定] 目标大小已记录: %dx%d" % self._target_window_size)

    def _ensure_window_size(self):
        """检测窗口大小是否变动，变动则拉回目标大小"""
        if self.hwnd is None or self._target_window_size is None:
            return
        self._update_window_rect()
        cur_w = self.window_rect["width"]
        cur_h = self.window_rect["height"]
        tgt_w, tgt_h = self._target_window_size
        if abs(cur_w - tgt_w) > 2 or abs(cur_h - tgt_h) > 2:
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            user32.SetWindowPos(self.hwnd, 0, 0, 0, tgt_w, tgt_h,
                                SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)
            self._update_window_rect()
            print("[窗口固定] 检测到大小变动 %dx%d -> 已拉回 %dx%d" % (cur_w, cur_h, tgt_w, tgt_h))

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
        if self.hwnd is None:
            return
        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]

        # 懒加载模板
        if not hasattr(self, '_tpl_minimap'):
            base = resource_path(os.path.join("data", "templates"))
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
        if self.hwnd is None or not self.window_rect or self.window_rect.get("width", 0) <= 0:
            return np.zeros((MAP_H, FIXED_W, 3), dtype=np.uint8)
        r = self.window_rect
        return np.array(self.sct.grab(r))[:, :, :3]

    def _capture_map(self):
        if self.hwnd is None or not self.window_rect or self.window_rect.get("width", 0) <= 0:
            return np.zeros((MAP_H, FIXED_W, 3), dtype=np.uint8)
        r = self.map_area_rect
        reg = {
            "left": self.window_rect["left"] + r["left"],
            "top": self.window_rect["top"] + r["top"],
            "width": r["width"],
            "height": r["height"]
        }
        if reg["width"] <= 0 or reg["height"] <= 0:
            return np.zeros((MAP_H, FIXED_W, 3), dtype=np.uint8)
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
        for vk in [VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10, VK_F12]:
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
        elif vk == VK_F10:
            if self.hwnd is None:
                print("[启动] 未绑定游戏窗口，请先绑定")
                self._add_log("未绑定窗口，无法启动")
            else:
                self._running = True
                print("[启动] 脚本已启动 (F10)")
                self._add_log("脚本已启动 F10")
        elif vk == VK_F12:
            if self._running:
                self._running = False
                print("[停止] 脚本已停止 (F12)")
                self._add_log("脚本已停止 F12")

    def _on_mouse(self, event, x, y, flags, param):
        """鼠标点击回调：标签页切换 + 路线页按钮"""
        # 1. 顶部标签页切换
        if event == cv2.EVENT_LBUTTONDOWN:
            for tab, (tx, ty, tw, th) in self._tab_areas.items():
                if tx <= x < tx + tw and ty <= y < ty + th:
                    if tab != self._current_tab:
                        self._current_tab = tab
                        self._ui_bg = self._ui_bgs[tab]
                        self._dropdown = None
                        if self._focused_field is not None:
                            self._save_input_config()
                            self._focused_field = None
                        print("[标签页] 切换到:", tab)
                    return

        if self._current_tab in ("fight", "potion"):
            if event == cv2.EVENT_LBUTTONDOWN:
                self._handle_input_mouse(x, y)
            return

        if self._current_tab != "route":
            return

        # 2. 手动框选模式（小地图合成区域内拖拽）
        if self._selecting:
            mx = int((x - UI_MAP_X) / UI_MAP_SCALE)
            my = int((y - UI_MAP_Y) / UI_MAP_SCALE)
            if my < 22:
                if event == cv2.EVENT_LBUTTONDOWN and mx < 48:
                    self._selecting = False
                    self._select_rect = None
                    self._select_dragging = False
            elif my >= MAP_H:
                if event == cv2.EVENT_LBUTTONDOWN:
                    self._selecting = False
                    self._select_rect = None
                    self._select_dragging = False
                    if getattr(self, '_was_random_running', False) and self.route_mode == "随机":
                        self._start_random()
            else:
                if event == cv2.EVENT_LBUTTONDOWN:
                    self._select_dragging = True
                    self._select_rect = (mx, my, mx, my)
                elif event == cv2.EVENT_MOUSEMOVE and self._select_dragging:
                    x1, y1, _, _ = self._select_rect
                    self._select_rect = (x1, y1, mx, my)
                elif event == cv2.EVENT_LBUTTONUP:
                    self._select_dragging = False
                    x1, y1, _, _ = self._select_rect
                    self._select_rect = (x1, y1, mx, my)
                    self._confirm_select()
                return

        if event not in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_RBUTTONDOWN):
            return

        # 右键：已绑窗口下拉列表项解绑（向上弹出，最多10项）
        if event == cv2.EVENT_RBUTTONDOWN:
            if self._bound_dropdown and self._bound_windows:
                item_h = 20
                show_count = min(len(self._bound_windows), 10)
                menu_y2 = UI_BOUND_Y  # 菜单底部在按钮顶部
                menu_y1 = menu_y2 - show_count * item_h
                if UI_BOUND_X <= x < UI_BOUND_X + UI_BOUND_W and menu_y1 <= y < menu_y2:
                    idx = (y - menu_y1) // item_h
                    if 0 <= idx < show_count:
                        w = self._bound_windows.pop(idx)
                        self._add_log("已解绑: %s" % w["title"][:20])
                        print("[已绑窗口] 解绑:", w["title"])
                        # 如果解绑的是当前活动窗口，自动切换到列表中的下一个
                        if self.hwnd == w["hwnd"]:
                            if self._bound_windows:
                                next_w = self._bound_windows[0]
                                self.hwnd = next_w["hwnd"]
                                self._update_window_rect()
                                self._detect_minimap()
                                self._add_log("切换到: %s" % next_w["title"][:20])
                            else:
                                self.hwnd = None
                                self._auto_refresh = False
                                self._stop_random()
                        if not self._bound_windows:
                            self._bound_dropdown = False
                    return
            return

        # 已绑窗口下拉菜单：左键点击其他地方则关闭
        if self._bound_dropdown and event == cv2.EVENT_LBUTTONDOWN:
            in_button = UI_BOUND_X <= x < UI_BOUND_X + UI_BOUND_W and UI_BOUND_Y <= y < UI_BOUND_Y + UI_BOUND_H
            in_menu = False
            if self._bound_windows:
                item_h = 20
                show_count = min(len(self._bound_windows), 10)
                menu_y2 = UI_BOUND_Y
                menu_y1 = menu_y2 - show_count * item_h
                in_menu = UI_BOUND_X <= x < UI_BOUND_X + UI_BOUND_W and menu_y1 <= y < menu_y2
            if not in_button and not in_menu:
                self._bound_dropdown = False

        # 3. 下拉菜单优先（向下弹出，在小地图检测之前）
        if self._dropdown is not None:
            btn_col_map = {"save": 2, "route": 3, "mode": 2, "clear_route": 3}
            col = btn_col_map[self._dropdown]
            col_x1 = UI_BTN_START_X + col * (UI_BTN_COL_W + UI_BTN_GAP)
            col_x2 = col_x1 + UI_BTN_COL_W
            items = self._dropdown_items()
            n = len(items)
            menu_h = n * DROPDOWN_ITEM_H
            menu_y1 = UI_BTN_ROW1_Y + UI_BTN_H  # 向下弹出
            if col_x1 <= x < col_x2 and menu_y1 <= y < menu_y1 + menu_h:
                item_idx = (y - menu_y1) // DROPDOWN_ITEM_H
                if 0 <= item_idx < n:
                    self._handle_dropdown_item(self._dropdown, item_idx)
                self._dropdown = None
                return
            if col_x1 <= x < col_x2 and UI_BTN_ROW1_Y <= y < UI_BTN_ROW1_Y + UI_BTN_H:
                self._dropdown = None
                return
            self._dropdown = None

        # 4. 小地图区域内点击（刷新/手动）
        if UI_MAP_X <= x < UI_MAP_X + UI_MAP_W and UI_MAP_Y <= y < UI_MAP_Y + UI_MAP_H:
            mx = int((x - UI_MAP_X) / UI_MAP_SCALE)
            my = int((y - UI_MAP_Y) / UI_MAP_SCALE)
            if my < 22:
                if mx < 48:
                    print("[鼠标] 刷新")
                    self._auto_refresh = True
                    self._detect_minimap()
                    self.frame_count = 0
                    self.last_player_pos = None
                    return
                elif 50 <= mx < 98:
                    print("[鼠标] 手动框选")
                    self.manual_select_region()
                    return
            return

        # 5. 第一排按钮（平台/梯子/保存▼/方案▼）
        if UI_BTN_ROW1_Y <= y < UI_BTN_ROW1_Y + UI_BTN_H:
            col = (x - UI_BTN_START_X) // (UI_BTN_COL_W + UI_BTN_GAP)
            if col == 0:
                print("[鼠标] 平台")
                self._handle_hotkey(VK_F5)
            elif col == 1:
                print("[鼠标] 梯子")
                self._handle_hotkey(VK_F6)
            elif col == 2:
                self._dropdown = "save" if self._dropdown != "save" else None
            elif col == 3:
                self._dropdown = "route" if self._dropdown != "route" else None
            return

        # 6. 第二排按钮（清除平台/清除梯子/模式▼/清除方案▼）
        if UI_BTN_ROW2_Y <= y < UI_BTN_ROW2_Y + UI_BTN_H:
            col = (x - UI_BTN_START_X) // (UI_BTN_COL_W + UI_BTN_GAP)
            if col == 0:
                self._pop_platform()
            elif col == 1:
                self._pop_ladder()
            elif col == 2:
                self._dropdown = "mode" if self._dropdown != "mode" else None
            elif col == 3:
                self._dropdown = "clear_route" if self._dropdown != "clear_route" else None
            return

        # 7. 运行/停止
        if UI_RUN_Y <= y < UI_RUN_Y + UI_RUN_H:
            if UI_RUN_X <= x < UI_RUN_X + UI_RUN_W:
                print("[鼠标] 运行")
                if self.route_mode == "随机":
                    self._start_random()
                return
            if UI_STOP_X <= x < UI_STOP_X + UI_STOP_W:
                print("[鼠标] 停止")
                self._stop_random()
                return

        # 8. 子标签页（人物特征/特征清除/怪物数据）
        if UI_SUBTAB_Y <= y < UI_SUBTAB_Y + UI_SUBTAB_H:
            if 15 <= x < 107:
                print("[鼠标] 人物特征")
                self._capture_character_feature()
            elif 115 <= x < 207:
                print("[鼠标] 特征清除")
                self._clear_character_features()
            elif 215 <= x < 307:
                print("[鼠标] 怪物数据")
                self._add_log("YOLO模型未就绪")
            return

        # 9. 可拖拽准星（按住拖到游戏窗口释放即绑定前台窗口）
        chx, chy = self._crosshair_pos
        half = self._crosshair_size // 2
        if chx - half <= x < chx + half and chy - half <= y < chy + half:
            print("[鼠标] 准星拖拽开始 - 拖到游戏窗口释放")
            self._drag_crosshair = True
            self._add_log("拖到游戏窗口释放")
            return

        # 10. 已绑窗口下拉按钮
        if UI_BOUND_X <= x < UI_BOUND_X + UI_BOUND_W and UI_BOUND_Y <= y < UI_BOUND_Y + UI_BOUND_H:
            self._bound_dropdown = not self._bound_dropdown
            print("[鼠标] 已绑窗口下拉:", "展开" if self._bound_dropdown else "收起")
            return


    def draw(self, map_area, player_pos):
        frame = self._ui_bg.copy()

        if self._current_tab in ("fight", "potion"):
            self._draw_input_fields(frame)
            return frame

        if self._current_tab != "route":
            return frame

        # === 渲染小地图内容 ===
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

        # 随机模式运行状态
        if self._random_running:
            state_text = {"idle": "选方案中", "moving": "移动中", "attacking": "攻击中", "returning": "返回起点"}.get(self._random_state, self._random_state)
            progress = "%d/%d" % (min(self._random_platform_idx + 1, len(self.platforms)), len(self.platforms)) if self.platforms else "0/0"
            status = "随机: %s 平台%s" % (state_text, progress)
            cv2.rectangle(map_display, (0, MAP_H - 20), (FIXED_W, MAP_H), (25, 25, 25), -1)
            cv2.putText(map_display, status, (6, MAP_H - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1)

        # 左上角文字按钮
        cv2.rectangle(map_display, (0, 0), (195, 22), (25, 25, 25), -1)
        refresh_color = (0, 255, 0) if self._auto_refresh else (0, 165, 255)
        cv2.putText(map_display, "刷新", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, refresh_color, 1)
        cv2.putText(map_display, "手动", (52, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
        if self.route_mode == "随机":
            cv2.putText(map_display, "随机", (100, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
        else:
            route_text = "方案" + "一二三"[self.current_route - 1]
            cv2.putText(map_display, route_text, (100, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)

        # 手动框选拖拽矩形
        if self._selecting and self._select_rect and self._select_dragging:
            x1, y1, x2, y2 = self._select_rect
            cv2.rectangle(map_display, (x1, y1), (x2, y2), (0, 255, 255), 1)

        # === 缩放到UI尺寸并合成到背景 ===
        map_scaled = cv2.resize(map_display, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H, UI_MAP_X:UI_MAP_X+UI_MAP_W] = map_scaled

        # === 录制状态红色闪烁指示器（在对应按钮左上角）===
        import time as _t
        if int(_t.time() * 3) % 2 == 0:
            if self.recording_platform:
                cv2.circle(frame, (UI_BTN_START_X + 8, UI_BTN_ROW1_Y + 8), 5, (0, 0, 255), -1)
                cv2.circle(frame, (UI_BTN_START_X + 8, UI_BTN_ROW1_Y + 8), 5, (0, 0, 180), 1)
            if self.recording_ladder:
                cv2.circle(frame, (UI_BTN_START_X + UI_BTN_COL_W + 8, UI_BTN_ROW1_Y + 8), 5, (0, 0, 255), -1)
                cv2.circle(frame, (UI_BTN_START_X + UI_BTN_COL_W + 8, UI_BTN_ROW1_Y + 8), 5, (0, 0, 180), 1)

        # === 下拉菜单 ===
        if self._dropdown is not None:
            items = self._dropdown_items()
            n = len(items)
            btn_col_map = {"save": 2, "route": 3, "mode": 2, "clear_route": 3}
            col = btn_col_map[self._dropdown]
            col_x1 = UI_BTN_START_X + col * (UI_BTN_COL_W + UI_BTN_GAP)
            col_x2 = col_x1 + UI_BTN_COL_W
            menu_h = n * DROPDOWN_ITEM_H
            menu_y1 = UI_BTN_ROW1_Y + UI_BTN_H  # 向下弹出
            menu_y2 = menu_y1 + menu_h
            cv2.rectangle(frame, (col_x1, menu_y1), (col_x2 - 1, menu_y2 - 1), (58, 58, 58), -1)
            cv2.rectangle(frame, (col_x1, menu_y1), (col_x2 - 1, menu_y2 - 1), (110, 110, 110), 1)
            for i, text in enumerate(items):
                iy = menu_y1 + i * DROPDOWN_ITEM_H
                if i > 0:
                    cv2.line(frame, (col_x1 + 3, iy), (col_x2 - 4, iy), (85, 85, 85), 1)
                is_current = False
                if self._dropdown == "route" and (i + 1) == self.current_route:
                    is_current = True
                elif self._dropdown == "mode" and text == self.route_mode:
                    is_current = True
                if is_current:
                    cv2.rectangle(frame, (col_x1 + 1, iy + 1), (col_x2 - 2, iy + DROPDOWN_ITEM_H - 1), (0, 70, 0), -1)
                color = (0, 255, 0) if is_current else (240, 240, 240)
                cv2.putText(frame, text, (col_x1 + 6, iy + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1)

        # === 日志区域 ===
        if self._logs:
            log_y = UI_LOG_Y + 14
            for log in self._logs[-4:]:
                cv2.putText(frame, log, (UI_LOG_X + 4, log_y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (60, 60, 60), 1)
                log_y += 14

        # === 已绑窗口下拉列表（向上弹出，最多10项）===
        if self._bound_dropdown and self._bound_windows:
            item_h = 20
            show_count = min(len(self._bound_windows), 10)
            menu_y2 = UI_BOUND_Y  # 菜单底部在按钮顶部
            menu_y1 = menu_y2 - show_count * item_h
            # 背景
            cv2.rectangle(frame, (UI_BOUND_X, menu_y1), (UI_BOUND_X + UI_BOUND_W - 1, menu_y2 - 1), (58, 58, 58), -1)
            cv2.rectangle(frame, (UI_BOUND_X, menu_y1), (UI_BOUND_X + UI_BOUND_W - 1, menu_y2 - 1), (110, 110, 110), 1)
            for i, w in enumerate(self._bound_windows[:10]):
                iy = menu_y1 + i * item_h
                if i > 0:
                    cv2.line(frame, (UI_BOUND_X + 3, iy), (UI_BOUND_X + UI_BOUND_W - 4, iy), (85, 85, 85), 1)
                is_current = (w["hwnd"] == self.hwnd)
                if is_current:
                    cv2.rectangle(frame, (UI_BOUND_X + 1, iy + 1), (UI_BOUND_X + UI_BOUND_W - 2, iy + item_h - 1), (0, 70, 0), -1)
                color = (0, 255, 0) if is_current else (240, 240, 240)
                title = w["title"][:12] if len(w["title"]) > 12 else w["title"]
                cv2.putText(frame, title, (UI_BOUND_X + 4, iy + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.32, color, 1)
            # 提示右键解绑
            cv2.putText(frame, "RMB unbind", (UI_BOUND_X, menu_y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)
            if len(self._bound_windows) > 10:
                cv2.putText(frame, "...+%d more" % (len(self._bound_windows) - 10), (UI_BOUND_X, menu_y1 - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (180, 180, 180), 1)

        # === 可拖拽准星（窗口绑定）===
        chx, chy = self._crosshair_pos
        r = self._crosshair_size // 2
        # 外圈
        cv2.circle(frame, (chx, chy), r, (0, 0, 255), 2)
        cv2.circle(frame, (chx, chy), max(1, r // 3), (0, 0, 255), -1)
        # 十字线
        cv2.line(frame, (chx - r - 4, chy), (chx - r + 1, chy), (0, 0, 255), 2)
        cv2.line(frame, (chx + r - 1, chy), (chx + r + 4, chy), (0, 0, 255), 2)
        cv2.line(frame, (chx, chy - r - 4), (chx, chy - r + 1), (0, 0, 255), 2)
        cv2.line(frame, (chx, chy + r - 1), (chx, chy + r + 4), (0, 0, 255), 2)

        # === 准星拖拽模式提示 ===
        if self._drag_crosshair:
            cv2.putText(frame, "DRAG TO GAME WINDOW", (UI_W // 2 - 100, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        return frame


    def manual_select_region(self):
        """手动框选：OpenCV独立窗口1:1显示游戏截图，拖拽框选，坐标即游戏窗口坐标"""
        self._was_random_running = self._random_running
        if self._random_running:
            self._stop_random()

        print("\n=== 手动框选 ===")
        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]

        sel_win = "Select Minimap"
        cv2.namedWindow(sel_win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(sel_win, fw, fh)
        cv2.moveWindow(sel_win, 0, 0)

        self._select_rect = None
        self._select_dragging = False
        self._select_confirmed = False

        def on_sel_mouse(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                self._select_dragging = True
                self._select_rect = (x, y, x, y)
            elif event == cv2.EVENT_MOUSEMOVE and self._select_dragging:
                x1, y1, _, _ = self._select_rect
                self._select_rect = (x1, y1, x, y)
            elif event == cv2.EVENT_LBUTTONUP:
                self._select_dragging = False
                x1, y1, _, _ = self._select_rect
                self._select_rect = (x1, y1, x, y)
                self._select_confirmed = True

        cv2.setMouseCallback(sel_win, on_sel_mouse)
        print("在弹出的窗口上拖拽框选小地图，松开自动确认，按 Esc 取消")

        while True:
            display = frame.copy()
            if self._select_rect:
                x1, y1, x2, y2 = self._select_rect
                x1, x2 = min(x1, x2), max(x1, x2)
                y1, y2 = min(y1, y2), max(y1, y2)
                cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(display, "Drag to select minimap, release=apply, Esc=exit",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.imshow(sel_win, display)
            key = cv2.waitKey(20) & 0xFF
            if key == 27:
                print("取消框选")
                break
            if self._select_confirmed:
                x1, y1, x2, y2 = self._select_rect
                x1, x2 = min(x1, x2), max(x1, x2)
                y1, y2 = min(y1, y2), max(y1, y2)
                w = x2 - x1
                h = y2 - y1
                if w >= 20 and h >= 20:
                    self.minimap_rect = {"left": x1, "top": y1, "width": w, "height": h}
                    pad_l, pad_t, pad_r, pad_b = 8, 2, 2, 2
                    self.map_area_rect = {
                        "left": x1 + pad_l, "top": y1 + pad_t,
                        "width": w - pad_l - pad_r, "height": h - pad_t - pad_b
                    }
                    self._save_region()
                    self.frame_count = 0
                    self.last_player_pos = None
                    self._auto_refresh = False
                    print("已应用: (%d,%d) %dx%d（自动刷新已关闭，点刷新可重新开启）" % (x1, y1, w, h))
                else:
                    print("选择区域太小")
                break
            if cv2.getWindowProperty(sel_win, cv2.WND_PROP_VISIBLE) < 1:
                break

        cv2.destroyWindow(sel_win)
        if getattr(self, '_was_random_running', False) and self.route_mode == "随机":
            self._start_random()

    def _stop_select_listener(self):
        pass

    def _confirm_select(self):
        """确认框选（松开鼠标自动调用），将显示坐标映射到游戏窗口坐标"""
        if not self._select_rect:
            return
        x1, y1, x2, y2 = self._select_rect
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        w = x2 - x1
        h = y2 - y1
        if w < 10 or h < 10:
            print("选择区域太小，请重新拉取")
            self._select_rect = None
            return
        # 显示坐标(FIXED_W x MAP_H)映射到游戏窗口坐标
        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]
        sx = fw / FIXED_W
        sy = fh / MAP_H
        gx = int(x1 * sx)
        gy = int(y1 * sy)
        gw = int(w * sx)
        gh = int(h * sy)
        self.minimap_rect = {"left": gx, "top": gy, "width": gw, "height": gh}
        pad_l, pad_t, pad_r, pad_b = 8, 2, 2, 2
        self.map_area_rect = {
            "left": gx + pad_l, "top": gy + pad_t,
            "width": gw - pad_l - pad_r, "height": gh - pad_t - pad_b
        }
        self._save_region()
        self.frame_count = 0
        self.last_player_pos = None
        self._auto_refresh = False
        self._selecting = False
        self._select_rect = None
        self._select_dragging = False
        if hasattr(self, '_win_name'):
            cv2.setWindowProperty(self._win_name, cv2.WND_PROP_TOPMOST, 0)
        if getattr(self, '_was_random_running', False) and self.route_mode == "随机":
            self._start_random()
        print("已应用: (%d,%d) %dx%d（自动刷新已关闭，点刷新可重新开启）" % (gx, gy, gw, gh))

    def _add_log(self, msg):
        self._logs.append(msg)
        if len(self._logs) > 20:
            self._logs = self._logs[-20:]

    def _load_char_templates(self):
        """从磁盘加载已保存的人物特征模板"""
        self._char_templates = []
        if not os.path.exists(CHAR_TEMPLATE_META):
            return
        try:
            with open(CHAR_TEMPLATE_META, "r", encoding="utf-8") as f:
                meta_list = json.load(f)
            for meta in meta_list:
                tid = meta.get("id", 0)
                img_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % tid)
                if os.path.exists(img_path):
                    img = cv2.imread(img_path)
                    if img is not None:
                        h, w = img.shape[:2]
                        self._char_templates.append({
                            "id": tid,
                            "img": img,
                            "width": w,
                            "height": h,
                            "created_at": meta.get("created_at", "")
                        })
            print("[人物特征] 已加载 %d 套模板" % len(self._char_templates))
        except Exception as e:
            print("[人物特征] 加载模板失败:", e)

    def _save_char_meta(self):
        """保存人物特征模板元数据到磁盘"""
        meta_list = []
        for t in self._char_templates:
            meta_list.append({
                "id": t["id"],
                "width": t["width"],
                "height": t["height"],
                "created_at": t["created_at"]
            })
        try:
            with open(CHAR_TEMPLATE_META, "w", encoding="utf-8") as f:
                json.dump(meta_list, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[人物特征] 保存元数据失败:", e)

    def _capture_character_feature(self):
        """人物特征截图：在游戏窗口框选人物身体，保存为特征模板（最多10套）
        使用 cv2.selectROI 内置框选，坐标可靠，无最小尺寸限制（越小越精确）"""
        if self.hwnd is None:
            self._add_log("请先绑定游戏窗口")
            print("[人物特征] 未绑定窗口")
            return

        # 超过上限则替换最早的一套
        if len(self._char_templates) >= CHAR_MAX_TEMPLATES:
            oldest = self._char_templates.pop(0)
            old_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % oldest["id"])
            if os.path.exists(old_path):
                os.remove(old_path)
            self._add_log("模板已满，替换最早一套")

        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]
        if fh <= 0 or fw <= 0:
            self._add_log("截图失败")
            return

        print("[人物特征] 弹出框选窗口，拖拽框选人物身体，回车确认，ESC取消")
        # cv2.selectROI 返回 (x, y, w, h)，取消返回全0
        roi = cv2.selectROI("Select Character", frame, showCrosshair=False, fromCenter=False)
        cv2.destroyWindow("Select Character")

        x, y, w, h = roi
        if w <= 0 or h <= 0:
            print("[人物特征] 取消框选")
            return

        captured = frame[y:y + h, x:x + w].copy()

        # 分配新ID（取最大ID+1）
        existing_ids = [t["id"] for t in self._char_templates]
        new_id = (max(existing_ids) + 1) if existing_ids else 0
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")

        # 保存到磁盘
        img_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % new_id)
        cv2.imwrite(img_path, captured)

        ch, cw = captured.shape[:2]
        self._char_templates.append({
            "id": new_id,
            "img": captured,
            "width": cw,
            "height": ch,
            "created_at": created_at
        })
        self._save_char_meta()

        msg = "人物特征#%d已保存 (%dx%d) 共%d套" % (new_id, cw, ch, len(self._char_templates))
        self._add_log(msg)
        print("[人物特征]", msg)

    def _clear_character_features(self):
        """清除所有人物特征模板"""
        count = len(self._char_templates)
        if count == 0:
            self._add_log("没有可清除的特征")
            return
        for t in self._char_templates:
            img_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % t["id"])
            if os.path.exists(img_path):
                os.remove(img_path)
        self._char_templates = []
        if os.path.exists(CHAR_TEMPLATE_META):
            os.remove(CHAR_TEMPLATE_META)
        self._add_log("已清除 %d 套人物特征" % count)
        print("[特征清除] 已清除 %d 套" % count)

    def _match_character(self, frame):
        """在游戏画面中用模板匹配查找人物位置
        Args:
            frame: 游戏窗口截图 (BGR numpy)
        Returns:
            (center_x, center_y, confidence) 或 None
            坐标为游戏窗口内的像素坐标
        """
        if not self._char_templates or frame is None:
            return None
        fh, fw = frame.shape[:2]
        best_score = 0
        best_loc = None
        best_tpl = None
        for tpl in self._char_templates:
            timg = tpl["img"]
            th, tw = timg.shape[:2]
            if th > fh or tw > fw:
                continue
            result = cv2.matchTemplate(frame, timg, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_score:
                best_score = max_val
                best_loc = max_loc
                best_tpl = tpl
        if best_score >= CHAR_MATCH_THRESHOLD and best_loc is not None:
            cx = best_loc[0] + best_tpl["width"] // 2
            cy = best_loc[1] + best_tpl["height"] // 2
            return (cx, cy, best_score)
        return None

    def _calc_character_monster_distance(self, char_pos, monster_bbox):
        """计算人物与怪物之间的像素距离
        Args:
            char_pos: (x, y) 人物中心点坐标（游戏窗口像素）
            monster_bbox: (x1, y1, x2, y2) 怪物检测框（游戏窗口像素）
        Returns:
            float: 欧氏距离（像素），或 None 如果输入无效
        """
        if char_pos is None or monster_bbox is None:
            return None
        cx, cy = char_pos[0], char_pos[1]
        mx1, my1, mx2, my2 = monster_bbox
        mcx = (mx1 + mx2) // 2
        mcy = (my1 + my2) // 2
        return float(np.sqrt((cx - mcx) ** 2 + (cy - mcy) ** 2))

    def _find_nearest_monster(self, char_pos, monster_bboxes):
        """从怪物检测列表中找到离人物最近的怪物
        Args:
            char_pos: (x, y) 人物中心点
            monster_bboxes: [(x1,y1,x2,y2,conf,cls), ...] YOLO检测结果
        Returns:
            (index, distance) 或 (None, None)
        """
        if char_pos is None or not monster_bboxes:
            return None, None
        best_idx = None
        best_dist = float("inf")
        for i, bbox in enumerate(monster_bboxes):
            dist = self._calc_character_monster_distance(char_pos, bbox[:4])
            if dist is not None and dist < best_dist:
                best_dist = dist
                best_idx = i
        return best_idx, best_dist

    # ===== 打怪/药品 输入框系统 =====

    def _load_input_config(self):
        """加载打怪/药品配置到 _field_values（只加载用户已录入的值，不设默认显示）"""
        self._field_values = {}
        _debug_log("配置文件路径: %s 存在=%s" % (INPUT_CONFIG_FILE, os.path.exists(INPUT_CONFIG_FILE)))
        if os.path.exists(INPUT_CONFIG_FILE):
            try:
                with open(INPUT_CONFIG_FILE, "r", encoding="utf-8") as fp:
                    saved = json.load(fp)
                for k, v in saved.items():
                    if v:
                        self._field_values[k] = str(v)
                _debug_log("加载配置: %s" % dict(self._field_values))
                print("[输入框] 已加载配置，共 %d 项" % len(self._field_values))
            except Exception as e:
                _debug_log("加载配置失败: %s" % e)
                print("[输入框] 加载配置失败:", e)

    def _save_input_config(self):
        """保存 _field_values 到磁盘（只保存已知字段且非空的值）"""
        known_ids = set(f[5] for f in FIGHT_FIELDS + POTION_FIELDS)
        to_save = {k: v for k, v in self._field_values.items() if k in known_ids and v}
        try:
            with open(INPUT_CONFIG_FILE, "w", encoding="utf-8") as fp:
                json.dump(to_save, fp, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[输入框] 保存配置失败:", e)

    def _get_fields_for_tab(self, tab):
        """返回指定标签页的字段列表"""
        if tab == "fight":
            return FIGHT_FIELDS
        elif tab == "potion":
            return POTION_FIELDS
        return []

    def _find_field_at(self, x, y, tab):
        """查找 (x,y) 位置的字段，返回字段元组或 None"""
        for f in self._get_fields_for_tab(tab):
            fx, fy, fw, fh, ftype, fid = f
            if fx <= x < fx + fw and fy <= y < fy + fh:
                return f
        return None

    def _handle_input_mouse(self, x, y):
        """打怪/药品页的鼠标点击处理：聚焦输入框或取消聚焦"""
        field = self._find_field_at(x, y, self._current_tab)
        if field:
            _, _, _, _, ftype, fid = field
            self._focused_field = fid
            self._last_input_change = time.time() * 1000
            self._num_field_replace = (ftype == "num")  # 数字框聚焦后首次输入覆盖旧值
            print("[输入框] 聚焦:", fid, "类型:", ftype)
        else:
            # 点击其他地方，保存并取消聚焦
            if self._focused_field is not None:
                self._save_input_config()
                self._focused_field = None

    def _key_code_to_name(self, key):
        """将 cv2.waitKey 返回的键码转为键名字符串"""
        if key == 32:
            return "space"
        elif key == 13:
            return "enter"
        elif key == 9:
            return "tab"
        elif key == 8:
            return "backspace"
        elif 0 <= key < 256:
            ch = chr(key)
            if ch.isalnum():
                return ch.lower()
            # 符号键直接用字符
            if ch in "`-=[]\\;',./":
                return ch
        return None

    def _handle_input_key(self, key):
        """聚焦输入框时的键盘处理，返回 True 表示已消费该按键"""
        if self._focused_field is None:
            return False

        fid = self._focused_field
        # 找字段类型
        ftype = "num"
        for f in FIGHT_FIELDS + POTION_FIELDS:
            if f[5] == fid:
                ftype = f[4]
                break

        if ftype == "key":
            # ESC清空键值，回车取消
            if key == 27:
                self._field_values[fid] = ""
                self._save_input_config()
                self._focused_field = None
                return True
            if key == 13:
                self._focused_field = None
                return True
            # 按键录入：捕获第一个有效键后自动失焦
            name = self._key_code_to_name(key)
            if name:
                self._field_values[fid] = name
                print("[输入框] 按键录入:", fid, "=", name)
                self._focused_field = None
                self._save_input_config()
            return True

        elif ftype == "num":
            # 数字录入
            if 48 <= key <= 57:  # 0-9
                cur = self._field_values.get(fid, "")
                if getattr(self, '_num_field_replace', False):
                    new_val = chr(key)  # 聚焦后首次输入覆盖旧值
                    self._num_field_replace = False
                else:
                    new_val = cur + chr(key)
                # HP/MP阈值百分比上限100
                if fid in ("hp_value", "mp_value") and int(new_val) > 100:
                    return True
                if len(new_val) <= 10:
                    self._field_values[fid] = new_val
                    self._last_input_change = time.time() * 1000
            elif key == 8:  # 退格
                cur = self._field_values.get(fid, "")
                if cur:
                    self._field_values[fid] = cur[:-1]
                    self._last_input_change = time.time() * 1000
                self._num_field_replace = False  # 退格后取消覆盖状态
            elif key in (13, 27):  # 回车或ESC确认
                # 回车时再做一次上限校验
                if key == 13 and fid in ("hp_value", "mp_value"):
                    val = self._field_values.get(fid, "")
                    if val:
                        max_val = self._max_hp if fid == "hp_value" else self._max_mp
                        if max_val > 0 and int(val) > max_val:
                            print("[校验] %s阈值 %s 超出上限 %d，已清空" % (fid, val, max_val))
                            self._field_values[fid] = ""
                self._focused_field = None
                self._save_input_config()
            return True

        return False

    def _draw_input_fields(self, frame):
        """在 frame 上绘制输入框聚焦边框和用户已录入的值（不画任何默认/占位文字）"""
        fields = self._get_fields_for_tab(self._current_tab)
        for f in fields:
            fx, fy, fw, fh, ftype, fid = f
            val = self._field_values.get(fid, "")
            is_focused = (self._focused_field == fid)

            # 聚焦时画橙色边框
            if is_focused:
                cv2.rectangle(frame, (fx, fy), (fx + fw - 1, fy + fh - 1),
                              INPUT_FOCUS_COLOR, 2)

            # 只在用户已录入时画值
            if val:
                (tw, th), _ = cv2.getTextSize(val, INPUT_FONT, INPUT_FONT_SCALE, INPUT_FONT_THICKNESS)
                tx = fx + (fw - tw) // 2
                ty = fy + (fh + th) // 2 - 2
                cv2.putText(frame, val, (tx, ty), INPUT_FONT, INPUT_FONT_SCALE,
                            INPUT_TEXT_COLOR, INPUT_FONT_THICKNESS, cv2.LINE_AA)
            elif fid in ("hp_value", "mp_value"):
                # 空框显示占位文字
                ph = "百分比设置"
                (tw, th), _ = cv2.getTextSize(ph, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
                tx = fx + (fw - tw) // 2
                ty = fy + (fh + th) // 2 - 1
                cv2.putText(frame, ph, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                            (150, 150, 150), 1, cv2.LINE_AA)

    def _get_fight_config(self):
        """获取打怪配置（供战斗逻辑调用）
        skill_random: 技能随机时间(+-ms)，影响主攻/群攻触发
        buff_random: BUFF技能随机时间(+-ms)，影响BUFF触发"""
        return {
            "atk1_key": self._field_values.get("atk1_key", ""),
            "atk1_interval": int(self._field_values.get("atk1_interval", "300") or "300"),
            "atk1_distance": int(self._field_values.get("atk1_distance", "150") or "150"),
            "aoe_key": self._field_values.get("aoe_key", ""),
            "aoe_interval": int(self._field_values.get("aoe_interval", "1000") or "1000"),
            "aoe_distance": int(self._field_values.get("aoe_distance", "200") or "200"),
            "jump_key": self._field_values.get("jump_key", "alt"),
            "teleport_key": self._field_values.get("teleport_key", ""),
            "skill_random": int(self._field_values.get("skill_random", "50") or "50"),
            "buff_random": int(self._field_values.get("buff_random", "100") or "100"),
            "buffs": [
                {
                    "key": self._field_values.get("buff%d_key" % i, ""),
                    "cd": int(self._field_values.get("buff%d_cd" % i, "60000") or "60000"),
                    "delay": int(self._field_values.get("buff%d_delay" % i, "500") or "500"),
                }
                for i in range(1, 7)
            ],
        }

    def _get_potion_config(self):
        """获取药品配置（供药品逻辑调用）"""
        return {
            "hp_key": self._field_values.get("hp_key", ""),
            "hp_value": int(self._field_values.get("hp_value", "0") or "0"),
            "mp_key": self._field_values.get("mp_key", ""),
            "mp_value": int(self._field_values.get("mp_value", "0") or "0"),
            "pet_key": self._field_values.get("pet_key", ""),
            "pet_cd": int(self._field_values.get("pet_cd", "60000") or "60000"),
            "pots": [
                {
                    "key": self._field_values.get("pot%d_key" % i, ""),
                    "cd": int(self._field_values.get("pot%d_cd" % i, "1000") or "1000"),
                }
                for i in range(1, 6)
            ],
            "potion_random": int(self._field_values.get("potion_random", "50") or "50"),
        }

    # ===== HP/MP自动吃药 =====

    def _is_key_field(self, fid):
        """判断字段是否为按键录入类型"""
        for f in FIGHT_FIELDS + POTION_FIELDS:
            if f[5] == fid:
                return f[4] == "key"
        return False

    def _poll_key_capture(self):
        """用GetAsyncKeyState轮询捕获按键（支持F1-F12/Ctrl/Shift/Home/End等所有键）
        只捕获新按下的键（不捕获按住不放的）"""
        if self._focused_field is None or not self._is_key_field(self._focused_field):
            return
        current_pressed = set()
        for vk in VK_POLL_LIST:
            if user32.GetAsyncKeyState(vk) & 0x8000:
                current_pressed.add(vk)
        # 找出新按下的键（本次按下但上次没按下）
        new_keys = current_pressed - self._prev_key_states
        self._prev_key_states = current_pressed
        if new_keys:
            # 取第一个新按下的键
            vk = min(new_keys)
            name = VK_TO_NAME.get(vk, "vk_%d" % vk)
            self._field_values[self._focused_field] = name
            print("[按键录入] %s = %s (vk=0x%02X)" % (self._focused_field, name, vk))
            self._focused_field = None
            self._save_input_config()
            self._prev_key_states = set()
            self._last_input_change = time.time() * 1000

    def _key_to_vk(self, key_name):
        """键名转虚拟键码"""
        if not key_name:
            return None
        kn = key_name.lower()
        if len(kn) == 1 and kn.isalnum():
            return ord(kn.upper())
        mapping = {
            "space": 0x20, "ctrl": 0x11, "alt": 0x12, "shift": 0x10,
            "enter": 0x0D, "tab": 0x09, "backspace": 0x08, "esc": 0x1B,
            "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
            "pgup": 0x21, "pgdn": 0x22,
            "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
            "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63,
            "num4": 0x64, "num5": 0x65, "num6": 0x66, "num7": 0x67,
            "num8": 0x68, "num9": 0x69,
            "num*": 0x6A, "num+": 0x6B, "num-": 0x6D, "num.": 0x6E, "num/": 0x6F,
            "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
            "printscreen": 0x2C,
        }
        if kn in mapping:
            return mapping[kn]
        if kn.startswith("f") and kn[1:].isdigit():
            n = int(kn[1:])
            if 1 <= n <= 12:
                return 0x6F + n
        if kn in "`-=[]\\;',./":
            return ord(kn)
        return None

    def _press_game_key(self, key_name):
        """keybd_event发键 + AttachThreadInput强制前台"""
        vk = self._key_to_vk(key_name)
        if vk is None:
            _debug_log("按键未知: %s" % key_name)
            return
        if not self.hwnd:
            _debug_log("无窗口句柄")
            return
        kernel32 = ctypes.windll.kernel32
        scan = user32.MapVirtualKeyW(vk, 0)
        EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0xA3, 0xA5}
        ext = 0x0001 if vk in EXTENDED_VKS else 0
        old_fg = user32.GetForegroundWindow()
        _debug_log("发键 %s vk=0x%02X scan=0x%02X ext=%d" % (key_name, vk, scan, ext))
        if old_fg != self.hwnd:
            fg_thread = user32.GetWindowThreadProcessId(old_fg, None)
            cur_thread = kernel32.GetCurrentThreadId()
            user32.AttachThreadInput(cur_thread, fg_thread, True)
            user32.BringWindowToTop(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
            user32.AttachThreadInput(cur_thread, fg_thread, False)
        time.sleep(0.05)
        user32.keybd_event(vk, scan, ext, 0)
        time.sleep(0.08)
        user32.keybd_event(vk, scan, ext | 0x0002, 0)
        _debug_log("keybd_event已发送")
        time.sleep(0.03)
        if old_fg and old_fg != self.hwnd:
            fg_thread = user32.GetWindowThreadProcessId(old_fg, None)
            cur_thread = kernel32.GetCurrentThreadId()
            user32.AttachThreadInput(cur_thread, fg_thread, True)
            user32.SetForegroundWindow(old_fg)
            user32.AttachThreadInput(cur_thread, fg_thread, False)

    def _detect_hp_mp_bars(self, frame):
        """检测HP/MP血条：只搜底部25px，HSV颜色，HP在左MP在右"""
        if frame is None:
            return None, None
        h, w = frame.shape[:2]
        y_start = max(0, h - 25)
        roi = frame[y_start:, :]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # HP红色
        hp_mask1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([12, 255, 255]))
        hp_mask2 = cv2.inRange(hsv, np.array([168, 80, 80]), np.array([180, 255, 255]))
        hp_mask = (hp_mask1 | hp_mask2) > 0
        # MP青蓝色
        mp_mask = cv2.inRange(hsv, np.array([85, 60, 80]), np.array([135, 255, 255])) > 0
        hp_bar = self._find_longest_hbar(hp_mask, y_start)
        mp_bar = None
        if hp_bar:
            hx, hy, hw = hp_bar
            mp_bar = self._find_longest_hbar(mp_mask, y_start,
                                             x_min=hx + hw - 15, x_max=hx + hw + 160,
                                             y_center=hy, y_tol=6, max_w=120)
        if mp_bar is None:
            mp_bar = self._find_longest_hbar(mp_mask, y_start, max_w=120)
        # 测量条的总宽度（填充+空白），替换填充宽度
        if hp_bar:
            total = self._measure_bar_total_width(frame, hp_bar[0], hp_bar[1], "hp")
            if total:
                hp_bar = (hp_bar[0], hp_bar[1], total)
            else:
                _debug_log("HP总宽测量失败, 使用填充宽=%d" % hp_bar[2])
        if mp_bar:
            total = self._measure_bar_total_width(frame, mp_bar[0], mp_bar[1], "mp")
            if total:
                mp_bar = (mp_bar[0], mp_bar[1], total)
            else:
                _debug_log("MP总宽测量失败, 使用填充宽=%d" % mp_bar[2])
        # 稳定性缓存：偏差太大就用上次的位置，避免跳变误触发
        if not hasattr(self, '_hp_bar_stable'):
            self._hp_bar_stable = None
        if not hasattr(self, '_mp_bar_stable'):
            self._mp_bar_stable = None
        # HP校验：宽60-160，x在200-900，和缓存x差<50
        if hp_bar and 60 <= hp_bar[2] <= 160 and 200 <= hp_bar[0] <= 900:
            if self._hp_bar_stable is None or abs(hp_bar[0] - self._hp_bar_stable[0]) < 50:
                self._hp_bar_stable = hp_bar
        if self._hp_bar_stable:
            hp_bar = self._hp_bar_stable
        # MP校验：宽50-140，在HP右边0-200px
        if mp_bar and 50 <= mp_bar[2] <= 140:
            if hp_bar:
                if 0 <= mp_bar[0] - hp_bar[0] <= 200:
                    if self._mp_bar_stable is None or abs(mp_bar[0] - self._mp_bar_stable[0]) < 50:
                        self._mp_bar_stable = mp_bar
            else:
                if self._mp_bar_stable is None or abs(mp_bar[0] - self._mp_bar_stable[0]) < 50:
                    self._mp_bar_stable = mp_bar
        if self._mp_bar_stable:
            mp_bar = self._mp_bar_stable
        _debug_log("血条检测: hp=%s mp=%s" % (hp_bar, mp_bar))
        return hp_bar, mp_bar

    def _measure_bar_total_width(self, frame, x, y, color_type):
        """从条的左边界向右扫描，找到条的右边缘（非条内颜色），返回总宽度
        MP条内=B>180(亮蓝+暗蓝), HP条内=R>100(亮红+暗红)"""
        if frame is None or y >= frame.shape[0] or x >= frame.shape[1]:
            return None
        scan_y = y + 3
        if scan_y >= frame.shape[0]:
            scan_y = y
        out_count = 0
        for i in range(200):
            cx = x + i
            if cx >= frame.shape[1]:
                break
            b, g, r = frame[scan_y, cx]
            if color_type == "hp":
                in_bar = int(r) > 100
            else:
                in_bar = int(b) > 180
            if in_bar:
                out_count = 0
            else:
                out_count += 1
                if out_count >= 5:
                    return i - 4
        return None

    def _find_longest_hbar(self, mask, y_offset, x_min=0, x_max=99999, y_center=None, y_tol=8, max_w=200):
        """跨所有行找最长水平连续段，可限制x范围和y中心，返回(x,y,w)或None"""
        if mask is None or mask.size == 0 or mask.sum() < 15:
            return None
        best = None
        best_len = 0
        for row in range(mask.shape[0]):
            abs_y = y_offset + row
            if y_center is not None and abs(abs_y - y_center) > y_tol:
                continue
            cols = np.where(mask[row])[0]
            cols = cols[(cols >= x_min) & (cols <= x_max)]
            if len(cols) < 15:
                continue
            gaps = np.diff(cols)
            splits = np.where(gaps > 3)[0]
            start = 0
            for sp in splits:
                seg_len = int(cols[sp]) - int(cols[start]) + 1
                if seg_len > best_len and 20 <= seg_len <= max_w:
                    best_len = seg_len
                    best = (int(cols[start]), abs_y, seg_len)
                start = sp + 1
            seg_len = int(cols[-1]) - int(cols[start]) + 1
            if seg_len > best_len and 20 <= seg_len <= max_w:
                best_len = seg_len
                best = (int(cols[start]), abs_y, seg_len)
        return best

    def _is_bar_blank_at(self, frame, bar, pct, color_type):
        """检查血条在pct%位置的竖框内是否找不到填充色。找不到则吃药。
        color_type='hp': 填充=红(R明显大于G,B), 'mp': 填充=蓝(B>200)
        检测框: 左边缘对齐pct%位置，向右取样，3px宽 x 9px高竖框"""
        if bar is None or frame is None:
            return False
        x, y, bw = bar
        check_x = x + int(bw * pct / 100.0)  # 左边缘
        if check_x >= frame.shape[1] or check_x < 0:
            return False
        filled = 0
        total = 0
        for dx in range(0, 3):  # 向右取样3px
            for dy in range(0, 9):  # 9px高
                xx = check_x + dx
                yy = y + dy
                if 0 <= xx < frame.shape[1] and 0 <= yy < frame.shape[0]:
                    b, g, r = frame[yy, xx]
                    total += 1
                    if color_type == "hp":
                        # 直接判断红色：R明显大于G和B才算红（排除灰色/白色背景）
                        ri, gi, bi = int(r), int(g), int(b)
                        if ri > 100 and ri > gi + 25 and ri > bi + 25:
                            filled += 1
                    else:
                        if int(b) > 200:
                            filled += 1
        result = total > 0 and filled < total // 2
        _debug_log("blank检测 %s: x=%d y=%d bw=%d check_x=%d pct=%d filled=%d/%d -> %s" % (
            color_type, x, y, bw, check_x, pct, filled, total, result))
        return result

    def _init_digit_templates(self):
        """生成0-9数字模板（用cv2绘图，不依赖外部OCR）"""
        if self._digit_templates:
            return
        for d in range(10):
            img = np.zeros((26, 16), dtype=np.uint8)
            cv2.putText(img, str(d), (1, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 2, cv2.LINE_AA)
            self._digit_templates[d] = img

    def _recognize_digits(self, crop):
        """从裁剪区域识别数字，返回数字字符串（含/）"""
        if crop is None or crop.size == 0:
            return ""
        self._init_digit_templates()
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # 白字阈值（游戏数字是亮白色）
        _, thresh = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # 按x坐标排序
        boxes = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if 3 <= w <= 22 and 7 <= h <= 24:
                boxes.append((x, y, w, h))
        boxes.sort(key=lambda b: b[0])
        result = ""
        for (x, y, w, h) in boxes:
            digit_img = thresh[y:y+h, x:x+w]
            digit_resized = cv2.resize(digit_img, (16, 26))
            best_d = -1
            best_score = -1
            for d, tmpl in self._digit_templates.items():
                res = cv2.matchTemplate(digit_resized, tmpl, cv2.TM_CCOEFF_NORMED)
                score = float(res[0][0])
                if score > best_score:
                    best_score = score
                    best_d = d
            if best_score > 0.35:
                result += str(best_d)
            elif w <= 4 and h >= 12:
                # 细竖线可能是 / 或 |
                result += "/"
        return result

    def _detect_hp_mp_max(self, frame):
        """用数字模板匹配读取HP/MP的 current/max，更新上限"""
        if frame is None or self.hwnd is None:
            return
        now = time.time() * 1000
        if now - self._last_max_check < 3000:
            return
        self._last_max_check = now
        import re
        for bar, attr in [(self._hp_bar, "_max_hp"), (self._mp_bar, "_max_mp")]:
            if bar is None:
                continue
            x, y, w = bar
            # 裁剪血条上方的文字区域（数字在条上方）
            y1 = max(0, y - 24)
            y2 = y
            x1 = max(0, x - 10)
            x2 = min(frame.shape[1], x + w + 10)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            try:
                text = self._recognize_digits(crop)
                m = re.search(r'(\d+)/(\d+)', text)
                if m:
                    max_val = int(m.group(2))
                    if 50 <= max_val <= 999999:
                        old_max = getattr(self, attr, 0)
                        if old_max != max_val:
                            setattr(self, attr, max_val)
                            print("[上限检测] %s=%d (识别:%s)" % (attr, max_val, text))
                            # 阈值为空时默认设成上限的一半
                            fid = "hp_value" if attr == "_max_hp" else "mp_value"
                            if not self._field_values.get(fid, ""):
                                half = max_val // 2
                                self._field_values[fid] = str(half)
                                self._save_input_config()
                                print("[上限检测] %s 默认阈值=%d" % (fid, half))
            except Exception as e:
                print("[上限检测] 出错:", e)


    def _init_yolo(self):
        """加载YOLO onnx模型（cv2.dnn，不依赖onnxruntime）"""
        if self._yolo_net is not None:
            return True
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best.onnx")
        if not os.path.exists(model_path):
            model_path = "best.onnx"
        if not os.path.exists(model_path):
            print("[YOLO] 未找到 best.onnx")
            return False
        try:
            self._yolo_net = cv2.dnn.readNetFromONNX(model_path)
            self._yolo_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            print("[YOLO] 模型加载成功:", model_path)
            return True
        except Exception as e:
            print("[YOLO] 加载失败:", e)
            return False

    def _detect_monsters(self, frame):
        """YOLO检测怪物，返回 [(x1,y1,x2,y2,score), ...]"""
        if frame is None or not self._init_yolo():
            return []
        h, w = frame.shape[:2]
        INPUT_SIZE = 640
        scale = min(INPUT_SIZE / w, INPUT_SIZE / h)
        new_w, new_h = int(w * scale), int(h * scale)
        pad_x = (INPUT_SIZE - new_w) // 2
        pad_y = (INPUT_SIZE - new_h) // 2
        resized = cv2.resize(frame, (new_w, new_h))
        padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
        padded[pad_y:pad_y+new_h, pad_x:pad_x+new_w] = resized
        blob = cv2.dnn.blobFromImage(padded, 1/255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=True, crop=False)
        self._yolo_net.setInput(blob)
        out = self._yolo_net.forward()[0]  # (300, 6) = [x1,y1,x2,y2,score,cls]
        detections = []
        for row in out:
            x1, y1, x2, y2, score, cls = row
            if score < self._yolo_conf:
                continue
            x1 = int((x1 - pad_x) / scale)
            y1 = int((y1 - pad_y) / scale)
            x2 = int((x2 - pad_x) / scale)
            y2 = int((y2 - pad_y) / scale)
            if x2 > x1 and y2 > y1:
                detections.append((x1, y1, x2, y2, float(score)))
        # NMS去重
        if detections:
            boxes = [[d[0], d[1], d[2]-d[0], d[3]-d[1]] for d in detections]
            scores = [d[4] for d in detections]
            indices = cv2.dnn.NMSBoxes(boxes, scores, self._yolo_conf, self._yolo_nms)
            detections = [detections[i] for i in indices] if len(indices) > 0 else []
        return detections

    def _get_player_screen_pos(self, frame):
        """获取人物在游戏画面中的坐标（用特征模板匹配，失败返回画面中心底部）"""
        h, w = frame.shape[:2]
        # 优先用人物特征模板匹配
        best_loc = None
        best_score = 0
        tpl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "char_templates")
        if os.path.exists(tpl_dir):
            for fname in os.listdir(tpl_dir):
                if fname.endswith('.png'):
                    tpl = cv2.imread(os.path.join(tpl_dir, fname))
                    if tpl is None or tpl.shape[0] > h or tpl.shape[1] > w:
                        continue
                    res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    if max_val > best_score and max_val > 0.6:
                        best_score = max_val
                        best_loc = (max_loc[0] + tpl.shape[1]//2, max_loc[1] + tpl.shape[0]//2)
        if best_loc:
            return best_loc
        # 兜底：画面中心偏下
        return (w // 2, int(h * 0.65))

    def _draw_monster_overlay(self, frame, player_pos):
        """在游戏画面上画怪物框和人物连线"""
        if not self._monsters:
            return frame
        disp = frame.copy()
        px, py = player_pos
        cv2.circle(disp, (px, py), 6, (0, 255, 255), -1)
        cv2.putText(disp, "PLAYER", (px+8, py-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        for i, (x1, y1, x2, y2, score) in enumerate(self._monsters):
            cx, cy = (x1+x2)//2, (y1+y2)//2
            cv2.rectangle(disp, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(disp, "M%d %.0f%%" % (i, score*100), (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            # 连线
            cv2.line(disp, (px, py), (cx, cy), (0, 165, 255), 1)
            dist = int(np.sqrt((cx-px)**2 + (cy-py)**2))
            mid_x, mid_y = (px+cx)//2, (py+cy)//2
            cv2.putText(disp, str(dist), (mid_x, mid_y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 165, 255), 1)
        return disp


    def _init_yolo(self):
        """加载YOLO onnx模型（cv2.dnn，不依赖onnxruntime）"""
        if self._yolo_net is not None:
            return True
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best.onnx")
        if not os.path.exists(model_path):
            model_path = "best.onnx"
        if not os.path.exists(model_path):
            print("[YOLO] 未找到 best.onnx")
            return False
        try:
            self._yolo_net = cv2.dnn.readNetFromONNX(model_path)
            self._yolo_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            print("[YOLO] 模型加载成功:", model_path)
            return True
        except Exception as e:
            print("[YOLO] 加载失败:", e)
            return False

    def _detect_monsters(self, frame):
        """YOLO检测怪物，返回 [(x1,y1,x2,y2,score), ...]"""
        if frame is None or not self._init_yolo():
            return []
        h, w = frame.shape[:2]
        INPUT_SIZE = 640
        scale = min(INPUT_SIZE / w, INPUT_SIZE / h)
        new_w, new_h = int(w * scale), int(h * scale)
        pad_x = (INPUT_SIZE - new_w) // 2
        pad_y = (INPUT_SIZE - new_h) // 2
        resized = cv2.resize(frame, (new_w, new_h))
        padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
        padded[pad_y:pad_y+new_h, pad_x:pad_x+new_w] = resized
        blob = cv2.dnn.blobFromImage(padded, 1/255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=True, crop=False)
        self._yolo_net.setInput(blob)
        out = self._yolo_net.forward()[0]  # (300, 6) = [x1,y1,x2,y2,score,cls]
        detections = []
        for row in out:
            x1, y1, x2, y2, score, cls = row
            if score < self._yolo_conf:
                continue
            x1 = int((x1 - pad_x) / scale)
            y1 = int((y1 - pad_y) / scale)
            x2 = int((x2 - pad_x) / scale)
            y2 = int((y2 - pad_y) / scale)
            if x2 > x1 and y2 > y1:
                detections.append((x1, y1, x2, y2, float(score)))
        # NMS去重
        if detections:
            boxes = [[d[0], d[1], d[2]-d[0], d[3]-d[1]] for d in detections]
            scores = [d[4] for d in detections]
            indices = cv2.dnn.NMSBoxes(boxes, scores, self._yolo_conf, self._yolo_nms)
            detections = [detections[i] for i in indices] if len(indices) > 0 else []
        return detections

    def _get_player_screen_pos(self, frame):
        """获取人物在游戏画面中的坐标（用特征模板匹配，失败返回画面中心底部）"""
        h, w = frame.shape[:2]
        # 优先用人物特征模板匹配
        best_loc = None
        best_score = 0
        tpl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "char_templates")
        if os.path.exists(tpl_dir):
            for fname in os.listdir(tpl_dir):
                if fname.endswith('.png'):
                    tpl = cv2.imread(os.path.join(tpl_dir, fname))
                    if tpl is None or tpl.shape[0] > h or tpl.shape[1] > w:
                        continue
                    res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    if max_val > best_score and max_val > 0.6:
                        best_score = max_val
                        best_loc = (max_loc[0] + tpl.shape[1]//2, max_loc[1] + tpl.shape[0]//2)
        if best_loc:
            return best_loc
        # 兜底：画面中心偏下
        return (w // 2, int(h * 0.65))

    def _draw_monster_overlay(self, frame, player_pos):
        """在游戏画面上画怪物框和人物连线"""
        if not self._monsters:
            return frame
        disp = frame.copy()
        px, py = player_pos
        cv2.circle(disp, (px, py), 6, (0, 255, 255), -1)
        cv2.putText(disp, "PLAYER", (px+8, py-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        for i, (x1, y1, x2, y2, score) in enumerate(self._monsters):
            cx, cy = (x1+x2)//2, (y1+y2)//2
            cv2.rectangle(disp, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(disp, "M%d %.0f%%" % (i, score*100), (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            # 连线
            cv2.line(disp, (px, py), (cx, cy), (0, 165, 255), 1)
            dist = int(np.sqrt((cx-px)**2 + (cy-py)**2))
            mid_x, mid_y = (px+cx)//2, (py+cy)//2
            cv2.putText(disp, str(dist), (mid_x, mid_y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 165, 255), 1)
        return disp

    def _check_auto_potion(self):
        """自动吃药检测：HP/MP低于设定百分比时按键，带冷却和随机误差"""
        if self.hwnd is None:
            return
        now = time.time() * 1000
        # 每400ms检测一次，避免太频繁
        if now - self._last_pot_check < 500:
            return
        self._last_pot_check = now

        cfg = self._get_potion_config()

        frame = self._capture_window()
        if frame is None:
            return

        # 自动检测血条（每帧都检测，适应窗口移动）
        hp_bar, mp_bar = self._detect_hp_mp_bars(frame)
        if hp_bar:
            self._hp_bar = hp_bar
        if mp_bar:
            self._mp_bar = mp_bar

        # 检测HP/MP上限（每3秒一次，用于输入校验，不影响吃药逻辑）
        self._detect_hp_mp_max(frame)

        # HP检测 — 阈值%位置为空白(底色)则吃药
        hp_thresh = min(int(self._field_values.get("hp_value", "30") or "30"), 100)
        hp_blank = self._is_bar_blank_at(frame, self._hp_bar, hp_thresh, "hp")
        _debug_log("HP检测: blank=%s thresh=%d key=%s bar=%s" % (hp_blank, hp_thresh, cfg.get("hp_key"), self._hp_bar))
        if hp_blank and cfg.get("hp_key"):
            if now - self._last_hp_pot > self._hp_pot_delay:
                self._press_game_key(cfg["hp_key"])
                self._last_hp_pot = now
                self._hp_pot_delay = random.randint(800, 1000)
                print("[自动吃药] HP低于%d%%, 按 %s" % (hp_thresh, cfg["hp_key"]))

        # MP检测 — 阈值%位置为空白(底色)则吃药
        mp_thresh = min(int(self._field_values.get("mp_value", "30") or "30"), 100)
        mp_blank = self._is_bar_blank_at(frame, self._mp_bar, mp_thresh, "mp")
        _debug_log("MP检测: blank=%s thresh=%d key=%s bar=%s" % (mp_blank, mp_thresh, cfg.get("mp_key"), self._mp_bar))
        if mp_blank and cfg.get("mp_key"):
            if now - self._last_mp_pot > self._mp_pot_delay:
                self._press_game_key(cfg["mp_key"])
                self._last_mp_pot = now
                self._mp_pot_delay = random.randint(800, 1000)
                print("[自动吃药] MP低于%d%%, 按 %s" % (mp_thresh, cfg["mp_key"]))

        # 调试：实时显示检测框位置
        if frame is not None:
            dbg = frame.copy()
            if self._hp_bar:
                hx, hy, hw = self._hp_bar
                cx = hx + int(hw * hp_thresh / 100.0)
                cv2.rectangle(dbg, (cx, hy), (cx + 2, hy + 8), (0, 0, 0), 1)
                cv2.putText(dbg, f"HP{hp_thresh}%", (cx - 20, hy - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
            if self._mp_bar:
                mx, my, mw = self._mp_bar
                cx = mx + int(mw * mp_thresh / 100.0)
                cv2.rectangle(dbg, (cx, my), (cx + 2, my + 8), (0, 0, 0), 1)
                cv2.putText(dbg, f"MP{mp_thresh}%", (cx - 20, my - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)
            # 只裁剪底部血条区域显示
            h = dbg.shape[0]
            crop = dbg[max(0, h - 60):h, :]
            cv2.imshow("Potion Detection", crop)
            cv2.waitKey(1)

    def _combat_tick(self):
        """战斗逻辑：BUFF和1-5药品按冷却自动释放，仅在_running时生效
        主攻/群攻技能等YOLO模型到位后接入"""
        if not self._running or self.hwnd is None:
            return
        now = time.time() * 1000
        fight_cfg = self._get_fight_config()
        pot_cfg = self._get_potion_config()

        # BUFF 1-6：按键+冷却+后摇，受buff_random随机影响
        buff_rand = fight_cfg.get("buff_random", 50)
        for i, b in enumerate(fight_cfg.get("buffs", []), 1):
            key = b.get("key", "")
            cd = b.get("cd", 0)
            if not key or cd <= 0:
                continue
            last = self._buff_last.get("buff%d" % i, 0)
            actual_cd = cd + random.randint(-buff_rand, buff_rand)
            if now - last > actual_cd:
                self._press_game_key(key)
                self._buff_last["buff%d" % i] = now
                print("[BUFF%d] %s 释放 (冷却%dms)" % (i, key, cd))

        # 药品1-5：按键+冷却，受potion_random随机影响
        pot_rand = pot_cfg.get("potion_random", 50)
        for i, p in enumerate(pot_cfg.get("pots", []), 1):
            key = p.get("key", "")
            cd = p.get("cd", 0)
            if not key or cd <= 0:
                continue
            last = self._potion_last.get("pot%d" % i, 0)
            actual_cd = cd + random.randint(-pot_rand, pot_rand)
            if now - last > actual_cd:
                self._press_game_key(key)
                self._potion_last["pot%d" % i] = now
                print("[药品%d] %s 释放 (冷却%dms)" % (i, key, cd))

        # 宠物食：按键+冷却
        pet_key = pot_cfg.get("pet_key", "")
        pet_cd = pot_cfg.get("pet_cd", 0)
        if pet_key and pet_cd > 0:
            last = self._potion_last.get("pet", 0)
            if now - last > pet_cd:
                self._press_game_key(pet_key)
                self._potion_last["pet"] = now
                print("[宠物食] %s 释放" % pet_key)

    def _bind_window(self):
        """重新绑定游戏窗口（模糊匹配标题）"""
        hwnd = _find_game_window()
        if hwnd:
            self.hwnd = hwnd
            self._update_window_rect()
            self._detect_minimap()
            self._save_target_window_size()
            self._add_log("窗口已绑定")
            print("[窗口绑定] 已绑定")
        else:
            self._add_log("未找到游戏窗口")
            print("[窗口绑定] 未找到游戏窗口")

    def run(self):
        win = "PLAY AND HAPPY"
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(win, self._on_mouse)
        self._win_name = win
        self._win_size = (UI_W, UI_H)
        while True:
            try:
                map_area = self._capture_map()
            except Exception:
                time.sleep(0.05)
                continue

            try:
                if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                    print("Window closed, exiting...")
                    self._stop_random()
                    break
            except Exception:
                cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
                cv2.setMouseCallback(win, self._on_mouse)

            if self.frame_count == 0:
                cv2.imwrite("debug_map_area.png", map_area)
                print("Captured map_area:", map_area.shape[1], "x", map_area.shape[0])

            self.frame_count += 1
            if self._auto_refresh and self.frame_count % 30 == 0:
                self._detect_minimap(debug=False)
            # 窗口大小固定：每30帧检测一次，变动则拉回
            if self.frame_count % 30 == 0:
                self._ensure_window_size()
            if self.frame_count % 2 == 0 or self.last_player_pos is None:
                player_pos = self.find_player_dot(map_area)
            else:
                player_pos = self.last_player_pos

            if self.recording_platform and player_pos:
                self.platform_points.append(player_pos)
            if self.recording_ladder and player_pos:
                self.ladder_points.append(player_pos)

            self._random_step(player_pos)
            self._check_hotkeys()

            # === 自动吃药检测（HP/MP低于阈值） ===
            try:
                self._check_auto_potion()
            except Exception as e:
                print("[自动吃药] 异常:", e)
            try:
                self._combat_tick()
            except Exception as e:
                print("[战斗] 异常:", e)

            # === YOLO怪物检测已临时关闭 ===
            # try:
            #     now_ms = time.time() * 1000
            #     if now_ms - self._last_yolo_check > 500:
            #         self._last_yolo_check = now_ms
            #         game_frame = self._capture_window()
            #         if game_frame is not None:
            #             self._monsters = self._detect_monsters(game_frame)
            #             if self._monsters:
            #                 player_pos = self._get_player_screen_pos(game_frame)
            #                 overlay = self._draw_monster_overlay(game_frame, player_pos)
            #                 cv2.imshow("Monster Detection", overlay)
            # except Exception as e:
            #     print("[YOLO] 异常:", e)

            # === YOLO怪物检测已临时关闭(重复块) ===

            # === 准星拖拽绑定检测 ===
            if self._drag_crosshair:
                left_down = user32.GetAsyncKeyState(0x01) & 0x8000  # VK_LBUTTON
                if left_down:
                    # 跟随全局鼠标位置（不限制在UI窗口内，可拖到其他窗口）
                    cursor = POINT()
                    user32.GetCursorPos(cursor)
                    hwnd_ui = user32.FindWindowW(None, "PLAY AND HAPPY")
                    if hwnd_ui:
                        user32.ScreenToClient(hwnd_ui, ctypes.byref(cursor))
                        self._crosshair_pos = (cursor.x, cursor.y)
                else:
                    # 左键释放，绑定鼠标指向的顶层窗口
                    cursor = POINT()
                    user32.GetCursorPos(cursor)
                    hwnd = user32.WindowFromPoint(cursor)
                    # GetAncestor取真正顶层窗口(GA_ROOT=2)
                    hwnd = user32.GetAncestor(hwnd, 2)
                    _debug_log("跨线释放绑定 hwnd=%s" % hwnd)
                    _debug_log("前台绑定 hwnd=%s" % hwnd)
                    if hwnd:
                        length = user32.GetWindowTextLengthW(hwnd)
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        title = buf.value or "未知窗口"
                        _debug_log("前台绑定标题: %s" % title)
                        self.hwnd = hwnd
                        self._update_window_rect()
                        self._detect_minimap()
                        self._save_target_window_size()
                        if not any(w["hwnd"] == hwnd for w in self._bound_windows):
                            self._bound_windows.append({"hwnd": hwnd, "title": title})
                        self._add_log("已绑定: %s" % title[:20])
                        print("[窗口绑定] 前台窗口已绑定:", title)
                    else:
                        self._add_log("绑定失败")
                    self._drag_crosshair = False
                    self._crosshair_pos = self._crosshair_home

            try:
                frame = self.draw(map_area, player_pos)
                cv2.imshow(win, frame)
            except Exception as e:
                print("draw error:", e)
                cv2.imshow(win, self._ui_bg)

            key = cv2.waitKey(1) & 0xFF
            # 输入框自动失焦：3秒无变化 或 UI窗口非前台
            if self._focused_field is not None:
                now_ms = time.time() * 1000
                ui_hwnd = user32.FindWindowW(None, "PLAY AND HAPPY")
                fg_hwnd = user32.GetForegroundWindow()
                if now_ms - self._last_input_change > 3000 or (ui_hwnd and fg_hwnd != ui_hwnd):
                    self._save_input_config()
                    self._focused_field = None
            # 输入框聚焦时优先处理键盘
            if self._focused_field is not None:
                if self._is_key_field(self._focused_field):
                    # BACKSPACE清空键值，ESC取消聚焦（不参与按键捕获）
                    if user32.GetAsyncKeyState(0x08) & 0x8000:
                        self._field_values[self._focused_field] = ""
                        self._save_input_config()
                        self._focused_field = None
                        continue
                    if user32.GetAsyncKeyState(0x1B) & 0x8000:
                        self._focused_field = None
                        continue
                    self._poll_key_capture()
                elif key != 255:
                    self._handle_input_key(key)
                continue
            # 任意按键关闭所有下拉菜单
            if key != 255:
                self._dropdown = None
                self._bound_dropdown = False
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
