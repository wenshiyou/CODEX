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
import threading

# === 必须在创建任何窗口之前设置 DPI 感知，否则高DPI缩放下蒙板坐标错位 ===
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

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

def load_png(path):
    """加载PNG（保留alpha透明通道），兼容中文路径"""
    try:
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        return img
    except Exception:
        return None

def draw_asset(frame, asset, x, y, w, h):
    """将素材绘制到frame上，支持PNG透明通道混合"""
    if asset is None:
        return
    img = cv2.resize(asset, (w, h))
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = (img[:, :, 3:4].astype(np.float32)) / 255.0
        roi = frame[y:y+h, x:x+w].astype(np.float32)
        frame[y:y+h, x:x+w] = (img[:, :, :3].astype(np.float32) * alpha + roi * (1.0 - alpha)).astype(np.uint8)
    else:
        frame[y:y+h, x:x+w] = img

def draw_rounded_rect(img, x, y, w, h, radius, color, thickness=-1):
    """绘制圆角矩形（thickness=-1为填充）"""
    r = min(radius, w // 2, h // 2)
    # 四个角
    cv2.circle(img, (x + r, y + r), r, color, thickness)
    cv2.circle(img, (x + w - r, y + r), r, color, thickness)
    cv2.circle(img, (x + r, y + h - r), r, color, thickness)
    cv2.circle(img, (x + w - r, y + h - r), r, color, thickness)
    # 中间矩形
    cv2.rectangle(img, (x + r, y), (x + w - r, y + h), color, thickness)
    cv2.rectangle(img, (x, y + r), (x + w, y + h - r), color, thickness)

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

# === UI 整体缩放 ===
# === UI 整体尺寸（按参考图 效果图一.png 461x900）===
UI_W = 461
UI_H = 900

def _s(v):
    """fight/potion页用：原330x566设计缩放到UI尺寸"""
    return int(round(v * UI_W / 330.0))

# === 小地图内容区域 ===
UI_MAP_X = 29
UI_MAP_Y = 131
UI_MAP_W = 403
UI_MAP_H = 279
UI_MAP_SCALE = UI_MAP_W / FIXED_W

# === 按钮（参考图精确坐标）===
BTN_PLATFORM = (43, 451, 81, 43)
BTN_LADDER   = (134, 451, 80, 42)
BTN_SAVE     = (229, 451, 80, 42)
BTN_PLAN     = (324, 450, 94, 42)
BTN_PLATFORM_CLR = (43, 500, 81, 39)
BTN_LADDER_CLR   = (134, 499, 80, 39)
BTN_MODE         = (229, 499, 80, 40)
BTN_PLAN_CLR     = (326, 499, 92, 39)
BTN_RUN  = (27, 552, 195, 60)
BTN_STOP = (241, 552, 195, 60)
BTN_CHAR    = (54, 629, 152, 50)
BTN_OFFSET  = (210, 628, 215, 52)
BTN_MONSTER = (61, 694, 344, 46)

# === 偏移输入框 ===
# 数字实际绘制区域（小框）
OFFSET_X_DRAW = (228, 653, 87, 22)
OFFSET_Y_DRAW = (324, 654, 85, 22)
# 点击区域（扩大，包含"X偏移/Y偏移"标签文字）
OFFSET_X_CLICK = (228, 628, 87, 44)
OFFSET_Y_CLICK = (319, 628, 85, 45)

# === 工具栏（小地图上方）===
BTN_REFRESH = (28, 103, 57, 26)
BTN_MANUAL = (91, 104, 56, 25)
BTN_PLAN_TOOLBAR = (156, 104, 57, 25)

# === 窗口绑定 + 准星 ===
BTN_WINBIND = (25, 826, 124, 46)
CROSSHAIR_POS = (116, 849)
CROSSHAIR_SIZE = 30

# === 日志区域 ===
UI_LOG_X = 166
UI_LOG_Y = 754
UI_LOG_W = 274
UI_LOG_H = 135
UI_LOG_CONTENT_Y = 776

# === 已绑窗口下拉 ===
UI_BOUND_X = 31
UI_BOUND_Y = 777
UI_BOUND_W = 114
UI_BOUND_H = 24

# === 人物特征下拉面板 ===
CHAR_DD_X = 54
CHAR_DD_W = 180
CHAR_DD_SCROLL_W = 22
CHAR_DD_ITEM_H = 26
CHAR_DD_VISIBLE = 5
CHAR_DD_ITEMS = 10
CHAR_DD_FEAT_PER_PAGE = 4
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
CHAR_MATCH_THRESHOLD = 0.70

# === 打怪/药品 输入框配置 ===
INPUT_CONFIG_FILE = os.path.join(DATA_DIR, "fight_potion_config.json")
YOLO_CONFIG_FILE = os.path.join(DATA_DIR, "yolo_config.json")
INPUT_FONT = cv2.FONT_HERSHEY_SIMPLEX
INPUT_FONT_SCALE = 0.5 * UI_W / 330.0
INPUT_FONT_THICKNESS = 1
INPUT_TEXT_COLOR = (40, 40, 40)  # BGR 深色文字
INPUT_FOCUS_COLOR = (0, 170, 255)  # BGR 橙色聚焦边框

# 打怪页字段定义 (x, y, w, h, type, id) — 坐标由新背景(461x900)白色方框精确检测
# type: "key"=按键录入, "num"=数字录入
# 坐标由新背景(ui_tab_fight.png, 462x900)白色输入框精确检测
FIGHT_FIELDS = [
    # 主攻
    (100, 155, 54, 26, "key", "atk1_key"),
    (211, 154, 108, 30, "num", "atk1_interval"),
    (371, 154, 74, 29, "num", "atk1_distance"),
    # 群攻
    (100, 198, 54, 26, "key", "aoe_key"),
    (211, 196, 110, 29, "num", "aoe_interval"),
    (371, 195, 74, 29, "num", "aoe_distance"),
    # 跳跃 + 技能随机时间
    (100, 251, 54, 26, "key", "jump_key"),
    (306, 242, 138, 27, "num", "skill_random"),
    # 瞬移 + 瞬移距离（用于上/下层平台，不填=不启用）
    (100, 294, 54, 26, "key", "teleport_key"),
    (243, 294, 62, 26, "num", "teleport_distance"),
    # BUFF 1-6（技能/冷却/后摇）
    (95, 432, 67, 29, "key", "buff1_key"),
    (207, 432, 117, 29, "num", "buff1_cd"),
    (373, 433, 70, 29, "num", "buff1_delay"),
    (95, 482, 67, 29, "key", "buff2_key"),
    (207, 482, 117, 29, "num", "buff2_cd"),
    (373, 482, 70, 29, "num", "buff2_delay"),
    (95, 527, 67, 29, "key", "buff3_key"),
    (207, 527, 117, 29, "num", "buff3_cd"),
    (373, 526, 70, 29, "num", "buff3_delay"),
    (95, 572, 67, 29, "key", "buff4_key"),
    (207, 572, 117, 29, "num", "buff4_cd"),
    (373, 572, 70, 29, "num", "buff4_delay"),
    (95, 616, 67, 29, "key", "buff5_key"),
    (207, 616, 117, 29, "num", "buff5_cd"),
    (373, 615, 70, 29, "num", "buff5_delay"),
    (95, 659, 67, 29, "key", "buff6_key"),
    (207, 659, 117, 29, "num", "buff6_cd"),
    (373, 659, 70, 29, "num", "buff6_delay"),
    # BUFF技能随机时间
    (229, 706, 182, 28, "num", "buff_random"),
]

# 路线页字段定义 — 人物X/Y偏移（点击范围加大，覆盖偏移标签下半部分）
ROUTE_FIELDS = [
    (OFFSET_X_CLICK[0], OFFSET_X_CLICK[1], OFFSET_X_CLICK[2], OFFSET_X_CLICK[3], "num", "char_x_offset"),
    (OFFSET_Y_CLICK[0], OFFSET_Y_CLICK[1], OFFSET_Y_CLICK[2], OFFSET_Y_CLICK[3], "num", "char_y_offset"),
]

# 药品页字段定义 (x, y, w, h, type, id) — 坐标由新背景(461x900)白色方框精确检测
POTION_FIELDS = [
    # Hp / Mp / 宠物食
    (101, 174, 119, 43, "key", "hp_key"),
    (314, 177, 124, 37, "num", "hp_value"),
    (101, 226, 119, 43, "key", "mp_key"),
    (314, 229, 124, 38, "num", "mp_value"),
    (101, 286, 119, 43, "key", "pet_key"),
    (314, 287, 124, 38, "num", "pet_cd"),
    # 1-5按键（冷却框加宽）
    (102, 361, 105, 43, "key", "pot1_key"),
    (268, 364, 175, 38, "num", "pot1_cd"),
    (102, 420, 105, 44, "key", "pot2_key"),
    (268, 424, 175, 37, "num", "pot2_cd"),
    (102, 480, 105, 41, "key", "pot3_key"),
    (268, 482, 175, 37, "num", "pot3_cd"),
    (102, 539, 105, 41, "key", "pot4_key"),
    (268, 541, 175, 38, "num", "pot4_cd"),
    (102, 600, 105, 41, "key", "pot5_key"),
    (268, 601, 175, 38, "num", "pot5_cd"),
    # 药品技能随机时间
    (213, 673, 218, 31, "num", "potion_random"),
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
        self.map_area_rect = None  # 预先初始化，避免_detect_minimap未设置时属性缺失
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
        self._crosshair_size = CROSSHAIR_SIZE
        self._crosshair_home = CROSSHAIR_POS
        self._crosshair_pos = self._crosshair_home
        self._drag_crosshair = False
        # 已绑窗口列表
        self._bound_windows = []  # [{hwnd, title}]
        # 自动绑定的窗口加入已绑定列表
        if self.hwnd:
            try:
                length = user32.GetWindowTextLengthW(self.hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(self.hwnd, buf, length + 1)
                title = buf.value or "未知窗口"
                self._bound_windows.append({"hwnd": self.hwnd, "title": title})
            except Exception:
                self._bound_windows.append({"hwnd": self.hwnd, "title": "游戏窗口"})
        self._bound_dropdown = False
        self._char_dropdown = False  # 人物特征下拉面板开关
        self._char_scroll = 0  # 下拉面板当前滚动位置（特征起始索引）
        # 加载路线页UI素材（带透明通道）
        self._ui_run = load_png(resource_path(os.path.join("data", "ui_run.png")))
        self._ui_stop = load_png(resource_path(os.path.join("data", "ui_stop.png")))
        self._ui_platform = load_png(resource_path(os.path.join("data", "ui_platform.png")))
        self._ui_ladder = load_png(resource_path(os.path.join("data", "ui_ladder.png")))
        self._ui_save = load_png(resource_path(os.path.join("data", "ui_save.png")))
        self._ui_plan = load_png(resource_path(os.path.join("data", "ui_plan.png")))
        self._ui_platform_clear = load_png(resource_path(os.path.join("data", "ui_platform_clear.png")))
        self._ui_ladder_clear = load_png(resource_path(os.path.join("data", "ui_ladder_clear.png")))
        self._ui_mode = load_png(resource_path(os.path.join("data", "ui_mode.png")))
        self._ui_plan_clear = load_png(resource_path(os.path.join("data", "ui_plan_clear.png")))
        self._ui_char_btn = load_png(resource_path(os.path.join("data", "ui_char_btn.png")))
        self._ui_offset_label = load_png(resource_path(os.path.join("data", "ui_offset_label.png")))
        self._ui_monster_data = load_png(resource_path(os.path.join("data", "ui_monster_data.png")))
        self._ui_winbind_bg = load_png(resource_path(os.path.join("data", "ui_winbind_bg.png")))
        self._ui_crosshair = load_png(resource_path(os.path.join("data", "ui_crosshair.png")))
        self._ui_log_bg = load_png(resource_path(os.path.join("data", "ui_log_bg.png")))
        self._ui_bound_dropdown = load_png(resource_path(os.path.join("data", "ui_bound_dropdown.png")))
        self._ui_bound_dropdown = load_png(resource_path(os.path.join("data", "ui_bound_dropdown.png")))
        # 工具栏素材（小地图上方）
        self._ui_refresh = load_png(resource_path(os.path.join("data", "ui_refresh.png")))
        self._ui_manual = load_png(resource_path(os.path.join("data", "ui_manual.png")))
        self._ui_plan_toolbar = load_png(resource_path(os.path.join("data", "ui_plan_toolbar.png")))
        # MP标签模板（遮挡检测：标签在=没挡住=吃药，标签消失=被挡住=不吃药）
        _mp_label_path = resource_path(os.path.join("data", "templates", "mp_label.png"))
        if os.path.exists(_mp_label_path):
            self._mp_label_template = cv2.imread(_mp_label_path)
            _debug_log("[MP遮挡] 标签模板已加载 %dx%d" % self._mp_label_template.shape[:2])
        else:
            self._mp_label_template = None
            _debug_log("[MP遮挡] 标签模板不存在, 跳过遮挡检测")
        # 运行日志（新信息在底部，向上流动，可滚动）
        self._runtime_logs = []  # [{time, msg, color}]
        self._log_scroll = 0  # 0=底部（最新），正数=向上滚动看历史
        self._log_max = 500
        # 窗口大小固定：绑定时记录目标大小，运行中监控拉回
        self._target_window_size = None  # (width, height) 或 None
        # 人物特征模板（最多10套）
        self._char_templates = []  # [{id, img(numpy), width, height, created_at}]
        self._load_char_templates()
        # 打怪/药品输入框状态
        self._field_values = {}  # {field_id: value_string}
        self._focused_field = None  # 当前聚焦的字段id
        self._load_input_config()
        # YOLO模型路径（手动选择）
        self._yolo_model_path = None
        self._load_yolo_config()
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
        self._monster_frame_buffer = []  # 最近3帧检测结果，合并去重消除抖动
        self._monsters_display = []  # 蒙板显示用（多帧缓冲），目标选择用self._monsters最新帧
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
        self._attack_last = {}  # atk1/aoe -> 上次释放时间戳
        self._player_screen_pos = None  # (x,y) 人物画面坐标
        self._combat_busy_until = 0  # 后摇锁定时间戳
        # === 人性化战斗状态 ===
        self._combat_react_until = 0       # 反应延迟结束时间
        self._combat_idle_until = 0        # 发呆结束时间
        self._combat_last_idle_check = 0   # 上次发呆检查
        self._combat_last_jump = 0         # 上次跳跃时间
        self._combat_last_move = 0         # 上次走位时间
        self._combat_target_idx = 0        # 当前目标索引（排序后）
        self._combat_facing = 0            # 0=未知, 1=右, -1=左
        self._combat_turn_until = 0        # 转身动画结束时间
        self._combat_had_target = False    # 上一帧是否有目标
        self._combat_timed_keys = []       # 定时释放的按键 [(vk, release_ms)]（仅用于短按转身）
        self._combat_last_target_pos = None  # 上一次攻击目标位置(x,y)，用于近战挡身体时搜血条
        self._combat_held_keys = set()     # 持续按住的方向键（流畅移动用）
        self._combat_move_dir = None       # 当前持续移动方向 "left"/"right"/None
        self._combat_locked_target = None  # 当前目标 (cx, cy)，可灵活切换
        self._combat_last_switch = 0       # 上次切换目标时间，冷却500ms防晃动
        # 拟人化随机休息：3-5分钟随机休息5-10秒
        self._resting = False
        self._rest_until = 0
        self._next_rest_time = time.time() * 1000 + random.randint(180000, 300000)
        self._hotkey_scroll_x = 0  # 热键提示跑马灯位置（从0开始立即可见）
        self._player_map_pos = None        # 玩家小地图坐标，用于判断当前平台
        self._map_screen_scale = 0.08      # 小地图/屏幕换算比，运行时自动校准
        self._scale_samples_y = []         # scale_y采样列表
        self._last_calib_screen = None     # 上次校准用屏幕坐标
        self._last_calib_map = None        # 上次校准用小地图坐标
        self._monster_hp_bars = []         # 检测到的怪物血条 [(x,y,w,h),...]
        self._monster_history = {}         # 怪物移动预测 {pos_key: (x, y, ts)}，上一帧位置
        self._combat_stuck_start = 0       # 卡住开始时间戳
        self._combat_last_player_pos = None  # 上一帧玩家位置，用于卡住检测
        self._combat_stuck_recovery_step = 0  # 卡住恢复步骤 0=无 1=后退 2=跳跃 3=反向
        self._skill_cycle_idx = 0          # 多技能循环索引
        self._route_target_platform_override = None  # 路线系统目标平台覆盖（战斗系统设置，路线系统直接去）
        self._hp_pot_wait_until = 0        # HP吃药等待到这个时间
        self._mp_pot_wait_until = 0        # MP吃药等待到这个时间
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
        self._route_moving = False  # 路线系统移动中时，战斗系统不控制移动/攻击
        self._random_route_id = None
        self._random_platform_idx = 0
        self._random_state = "idle"  # idle/moving/attacking/returning/climbing
        self._random_attack_start = 0
        self._random_move_keys = set()  # 当前按住的移动键
        # 梯子攀爬状态机
        self._climb_state = "none"  # none/to_ladder/climbing/jump_down/teleport
        self._climb_ladder_x = 0
        self._climb_ladder_y_ref = 0  # 梯子参考Y（上梯=y_bottom, 下梯=y_top），跳之前验证
        self._climb_target_y = 0
        self._climb_direction = 0  # 1=up, -1=down
        self._climb_start_y = 0    # 跳跃/瞬移前的y坐标，用于检测是否生效
        self._climb_action_time = 0  # 跳跃/瞬移动作开始时间

        # 自动刷新状态：默认开启，手动框选后关闭，点刷新重新开启
        self._auto_refresh = True

        self.last_player_pos = None
        self.frame_count = 0

        # 热键状态（保留以备鼠标回调复用_handle_hotkey）
        self._key_state = {vk: False for vk in [VK_F5, VK_F6, VK_F8, VK_F10, VK_F12]}
        self._running = False  # 脚本运行状态，F10启动 F12停止
        self._last_input_change = 0  # 输入框最后修改时间，用于3秒自动失焦
        # 偏移视觉反馈：设好偏移后等3秒，在人物偏移点位画黄点闪烁5次
        self._offset_feedback_start = 0  # 偏移修改时间戳
        self._offset_feedback_done = True  # 是否已完成本次反馈（避免重复触发）
        # 怪物检测透明蒙板（统一蒙板：黄点+怪物框+血条红点+蓝条蓝点）
        self._monster_overlay_running = False
        self._overlay_hwnd = None
        self._monster_overlay_data = None  # {char_pos, monsters, hp_marker, mp_marker, blink_until}
        self._monster_overlay_thread = None
        # 按钮点击特效
        self._pressed_btn = None       # 当前按下的按钮rect (x,y,w,h)
        self._btn_flashes = []         # [(rect, start_ms, color_bgr), ...]

        # 加载UI背景图（五个标签页）
        self._ui_bgs = {}
        for tab, fname in [("route", "ui_bg_blank.png"), ("fight", "ui_tab_fight.png"),
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
            "route": (_s(5), _s(34), _s(75), _s(36)),
            "fight": (_s(82), _s(34), _s(60), _s(36)),
            "potion": (_s(145), _s(34), _s(60), _s(36)),
            "chat": (_s(207), _s(34), _s(58), _s(36)),
            "lie": (_s(266), _s(34), _s(58), _s(36)),
        }

        # 日志
        self._logs = []

        if self.map_area_rect:
            print("Map area:", self.map_area_rect["width"], "x", self.map_area_rect["height"])
        else:
            print("Map area: 未检测到小地图")
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
            self._tpl_minimap_bottom = cv2.imread(os.path.join(base, "minimap_bottom.png"))
            print("Templates loaded: mini%dx%d big%dx%d bottom%dx%d" % (
                self._tpl_minimap.shape[1], self._tpl_minimap.shape[0],
                self._tpl_bigmap.shape[1], self._tpl_bigmap.shape[0],
                self._tpl_minimap_bottom.shape[1], self._tpl_minimap_bottom.shape[0]))

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

        # 4. 模板匹配底部边界图（替代蓝色线颜色检测，避免人物经过时误判）
        tpl_btm = self._tpl_minimap_bottom
        btm_h, btm_w = tpl_btm.shape[:2]
        search_y1 = top
        search_y2 = min(fh, top + 350)
        # 在小地图左右边界内搜索底部模板（宽度可能小于小地图宽度，居中或偏左都能匹配）
        search_x1 = max(0, left - 20)
        search_x2 = min(fw, right + 20)
        roi_btm = frame[search_y1:search_y2, search_x1:search_x2]
        bottom = None
        if roi_btm.shape[0] >= btm_h and roi_btm.shape[1] >= btm_w:
            res_btm = cv2.matchTemplate(roi_btm, tpl_btm, cv2.TM_CCOEFF_NORMED)
            _, val_btm, _, loc_btm = cv2.minMaxLoc(res_btm)
            if val_btm >= 0.55:
                # 底部边界定在模板图片的上下正中间
                bottom = search_y1 + loc_btm[1] + btm_h // 2
                if debug:
                    print("底部模板: val=%.3f at (%d,%d), bottom_y=%d" % (
                        val_btm, search_x1 + loc_btm[0], search_y1 + loc_btm[1], bottom))
        if bottom is None:
            if debug:
                print("底部模板未找到(匹配度过低)，跳过本帧")
            return

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
        scan = user32.MapVirtualKeyW(vk, 0)
        ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
        user32.keybd_event(vk, scan, ext, 0)
        self._random_move_keys.add(vk)

    def _key_up(self, vk):
        scan = user32.MapVirtualKeyW(vk, 0)
        ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
        user32.keybd_event(vk, scan, ext | 0x0002, 0)  # KEYEVENTF_KEYUP
        self._random_move_keys.discard(vk)

    def _release_all_keys(self):
        for vk in list(self._random_move_keys):
            scan = user32.MapVirtualKeyW(vk, 0)
            ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
            user32.keybd_event(vk, scan, ext | 0x0002, 0)
        self._random_move_keys.clear()

    def _start_random(self):
        """启动随机模式：停止录制，清空按键，开始状态机"""
        if self._random_running:
            return
        if self.hwnd is None:
            print("[启动] 未绑定游戏窗口，请先绑定")
            self._add_log("未绑定窗口，无法启动")
            return
        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []
        self._release_all_keys()
        self._reset_climb()
        self._random_running = True
        self._random_state = "idle"
        self._random_platform_idx = 0
        self._random_no_route_logged = False
        # 同时启动战斗逻辑和透明蒙板（与F10一致）
        self._running = True
        print("[随机] 模式已启动，将自动选方案打平台")
        self._add_log("随机模式已启动（含战斗+蒙板）")
        _debug_log("[随机] 运行按钮已触发, _running=True, _random_running=True")

    def _stop_random(self):
        """停止随机模式：松开所有按键"""
        if not self._random_running:
            return
        self._release_all_keys()
        self._reset_climb()
        self._random_running = False
        self._random_state = "idle"
        # 同时停止战斗逻辑和透明蒙板
        self._running = False
        if self._monster_overlay_running:
            self._stop_monster_overlay()
        print("[随机] 模式已停止")
        self._add_log("随机模式已停止")
        _debug_log("[随机] 模式已停止")

    def _random_pick_route(self):
        """随机选一个有数据的方案，排除当前方案（避免连续重复）"""
        available = [i for i in range(1, 4) if self._route_has_file(i)]
        if not available:
            return None
        if len(available) > 1 and self._random_route_id in available:
            available = [i for i in available if i != self._random_route_id]
        return random.choice(available)

    def _find_nearest_ladder(self, px, py, target_y=None):
        """找最近的可用梯子。
        target_y不为None时：找能连接当前高度和目标高度的梯子（范围有重叠即可）
        target_y为None时：找包含当前高度的梯子"""
        best = None
        best_dist = 9999
        y_lo = min(py, target_y) if target_y is not None else py
        y_hi = max(py, target_y) if target_y is not None else py
        for ld in self.ladders:
            lx = ld["x"]
            y_top = ld["y_top"]
            y_bottom = ld["y_bottom"]
            # 梯子范围与[当前高度,目标高度]有重叠（允许±5误差）
            if y_bottom + 5 >= y_lo and y_top - 5 <= y_hi:
                dist = abs(lx - px)
                if dist < best_dist:
                    best_dist = dist
                    best = ld
        return best

    def _find_connecting_ladder(self, px, py, target_y, going_up, current_pf=None):
        """找连接当前平台和目标平台的梯子。
        验证梯子上下端点Y/X值：
        - 向上时：下端点Y≈当前平台Y，上端点Y≈目标平台Y
        - 向下时：上端点Y≈当前平台Y，下端点Y≈目标平台Y
        梯子X值应在当前平台X范围内。"""
        best = None
        best_score = 9999
        cur_y_min, cur_y_max = 9999, -9999
        if current_pf:
            cur_pts = self._platform_points(current_pf)
            cur_y_min = min(p[1] for p in cur_pts)
            cur_y_max = max(p[1] for p in cur_pts)

        for ld in self.ladders:
            lx = ld["x"]
            y_top = ld["y_top"]
            y_bottom = ld["y_bottom"]
            if going_up:
                bottom_ok = (y_bottom >= cur_y_min - 8) and (y_bottom <= cur_y_max + 8) if current_pf else True
                top_ok = abs(y_top - target_y) < 15
                if not (bottom_ok and top_ok):
                    continue
            else:
                top_ok = (y_top >= cur_y_min - 8) and (y_top <= cur_y_max + 8) if current_pf else True
                bottom_ok = abs(y_bottom - target_y) < 15
                if not (top_ok and bottom_ok):
                    continue
            x_dist = abs(lx - px)
            if x_dist < best_score:
                best_score = x_dist
                best = ld
        if best is None:
            best = self._find_nearest_ladder(px, py, target_y)
            if best:
                _debug_log("[路线] 未找到精确连接梯子，回退最近梯子x=%.0f" % best["x"])
        return best

    def _reset_climb(self):
        """重置攀爬/跳跃/瞬移状态"""
        if VK_UP in self._random_move_keys:
            self._key_up(VK_UP)
        if VK_DOWN in self._random_move_keys:
            self._key_up(VK_DOWN)
        self._climb_state = "none"
        self._climb_ladder_x = 0
        self._climb_target_y = 0
        self._climb_direction = 0
        self._climb_start_y = 0
        self._climb_action_time = 0

    def _do_teleport(self, current_y):
        """执行一次瞬移：按方向键+瞬移技能键"""
        fight_cfg = self._get_fight_config()
        tp_key = fight_cfg.get("teleport_key", "")
        if not tp_key:
            return
        # 先按方向键（上/下）
        if self._climb_direction > 0:
            if VK_DOWN in self._random_move_keys:
                self._key_up(VK_DOWN)
            if VK_UP not in self._random_move_keys:
                self._key_down(VK_UP)
        else:
            if VK_UP in self._random_move_keys:
                self._key_up(VK_UP)
            if VK_DOWN not in self._random_move_keys:
                self._key_down(VK_DOWN)
        # 按瞬移技能键
        self._press_game_key(tp_key, duration=60)
        self._climb_start_y = current_y
        self._climb_action_time = time.time() * 1000

    def _move_to(self, player_pos, target_x, target_y):
        """移动角色到目标位置（小地图坐标），支持梯子攀爬。返回是否到达"""
        if player_pos is None:
            return False
        px, py = player_pos
        dx = target_x - px
        dy = target_y - py
        now_ms = time.time() * 1000

        # === 跳跃反馈检测：上次跳跃后300ms Y没变化=跳失败，标记位置5秒内不再跳 ===
        last_jump_y = getattr(self, '_last_jump_y', None)
        last_jump_time = getattr(self, '_last_jump_time', 0)
        if last_jump_y is not None and now_ms - last_jump_time > 300:
            y_change = abs(py - last_jump_y)
            if y_change < 3:
                # 跳失败了，Y几乎没变化
                fail_pos = (px, py)
                if not hasattr(self, '_jump_failed_positions'):
                    self._jump_failed_positions = {}
                self._jump_failed_positions[fail_pos] = now_ms + 5000
                _debug_log("[跳跃反馈] 跳失败Y变化%.1f<3，标记位置(%.0f,%.0f)5秒内不再跳" % (y_change, px, py))
            self._last_jump_y = None  # 重置，只检测一次

        # 清理过期的跳跃失败标记
        if hasattr(self, '_jump_failed_positions'):
            self._jump_failed_positions = {k: v for k, v in self._jump_failed_positions.items() if v > now_ms}

        # 检查当前位置是否在跳跃失败标记附近（30px内）
        jump_blocked = False
        if hasattr(self, '_jump_failed_positions'):
            for (fx, fy) in self._jump_failed_positions:
                if abs(px - fx) < 30 and abs(py - fy) < 30:
                    jump_blocked = True
                    break

        # === 攀爬状态机 ===
        if self._climb_state == "to_ladder":
            # 移动到梯子x位置
            ldx = self._climb_ladder_x - px
            y_gap = abs(py - self._climb_ladder_y_ref)  # 人物Y与梯子端点Y差距（小地图坐标）
            fight_cfg = self._get_fight_config()
            jump_key = fight_cfg.get("jump_key", "")
            _log_throttle = time.time() - getattr(self, '_last_climb_log', 0) > 0.5
            if abs(ldx) > 6:
                # 还远（>6px），水平移动靠近
                if ldx > 0:
                    if VK_LEFT in self._random_move_keys: self._key_up(VK_LEFT)
                    if VK_RIGHT not in self._random_move_keys: self._key_down(VK_RIGHT)
                else:
                    if VK_RIGHT in self._random_move_keys: self._key_up(VK_RIGHT)
                    if VK_LEFT not in self._random_move_keys: self._key_down(VK_LEFT)
                if _log_throttle:
                    self._last_climb_log = time.time()
                    _debug_log("[爬梯-步骤1] 向梯子移动，梯子x=%.0f 玩家x=%.0f ldx=%.0f(>6) Y差=%.0f" % (
                        self._climb_ladder_x, px, ldx, y_gap))
                return False
            elif abs(ldx) > 5 and jump_key:
                # 5<X差≤6：跑跳（固定值，提前起跳，带方向）
                if ldx > 0:
                    if VK_LEFT in self._random_move_keys: self._key_up(VK_LEFT)
                    if VK_RIGHT not in self._random_move_keys: self._key_down(VK_RIGHT)
                else:
                    if VK_RIGHT in self._random_move_keys: self._key_up(VK_RIGHT)
                    if VK_LEFT not in self._random_move_keys: self._key_down(VK_LEFT)
                self._press_game_key(jump_key, duration=80)
                self._climb_start_y = py
                self._climb_action_time = time.time() * 1000
                # 跑跳延时计算：基础150ms，Y差每增加1加15ms，最大300ms
                # 延时后按上键抓梯子
                self._climb_up_press_delay = 150 + min(y_gap, 10) * 15
                self._climb_up_pressed = False
                self._climb_state = "ladder_jump_wait"
                _debug_log("[爬梯] 跑跳上梯 ldx=%.0f Y差%.0f 延时%dms后按上键" % (ldx, y_gap, self._climb_up_press_delay))
                return False
            elif abs(ldx) > 3:
                # 3<X差≤5：正常移动对齐梯子（不跳，全速走，直到X差≤3px直跳）
                if ldx > 0:
                    if VK_LEFT in self._random_move_keys: self._key_up(VK_LEFT)
                    if VK_RIGHT not in self._random_move_keys: self._key_down(VK_RIGHT)
                else:
                    if VK_RIGHT in self._random_move_keys: self._key_up(VK_RIGHT)
                    if VK_LEFT not in self._random_move_keys: self._key_down(VK_LEFT)
                return False
            elif y_gap > 15:
                # X对齐了（≤3px）但Y没对齐（不在梯子端点），不空跳，继续水平移动找梯子底部
                if ldx >= 0:
                    if VK_LEFT in self._random_move_keys: self._key_up(VK_LEFT)
                    if VK_RIGHT not in self._random_move_keys: self._key_down(VK_RIGHT)
                else:
                    if VK_RIGHT in self._random_move_keys: self._key_up(VK_RIGHT)
                    if VK_LEFT not in self._random_move_keys: self._key_down(VK_LEFT)
                _debug_log("[爬梯] X对齐但Y差%.0f>15，继续找梯子底部" % y_gap)
                return False
            elif jump_key:
                # X差≤3px（光点和蓝线重合）且Y在梯子端点：直跳+延时+上键
                if VK_LEFT in self._random_move_keys: self._key_up(VK_LEFT)
                if VK_RIGHT in self._random_move_keys: self._key_up(VK_RIGHT)
                self._press_game_key(jump_key, duration=80)
                self._climb_start_y = py
                self._climb_action_time = time.time() * 1000
                # 直跳延时：基础120ms，Y差每增加1加12ms，最大250ms
                self._climb_up_press_delay = 120 + min(y_gap, 10) * 12
                self._climb_up_pressed = False
                self._climb_state = "ladder_jump_wait"
                _debug_log("[爬梯] 直跳上梯 ldx=%.0f Y差%.0f 延时%dms后按上键" % (ldx, y_gap, self._climb_up_press_delay))
                return False
            else:
                # 没配置跳跃键，直接开始攀爬
                if VK_LEFT in self._random_move_keys: self._key_up(VK_LEFT)
                if VK_RIGHT in self._random_move_keys: self._key_up(VK_RIGHT)
                self._climb_state = "climbing"
                if self._climb_direction > 0:
                    if VK_DOWN in self._random_move_keys: self._key_up(VK_DOWN)
                    if VK_UP not in self._random_move_keys: self._key_down(VK_UP)
                else:
                    if VK_UP in self._random_move_keys: self._key_up(VK_UP)
                    if VK_DOWN not in self._random_move_keys: self._key_down(VK_DOWN)
                return False

        if self._climb_state == "ladder_jump_wait":
            # 等待跳跃结果：先延时→按上键抓梯子→等Y变化确认
            now_ms = time.time() * 1000
            elapsed = now_ms - self._climb_action_time
            delay = getattr(self, '_climb_up_press_delay', 180)
            up_pressed = getattr(self, '_climb_up_pressed', False)

            # 1. 延时到了按上键抓梯子
            if not up_pressed and elapsed >= delay:
                if VK_LEFT in self._random_move_keys: self._key_up(VK_LEFT)
                if VK_RIGHT in self._random_move_keys: self._key_up(VK_RIGHT)
                if self._climb_direction > 0:
                    if VK_DOWN in self._random_move_keys: self._key_up(VK_DOWN)
                    if VK_UP not in self._random_move_keys: self._key_down(VK_UP)
                else:
                    if VK_UP in self._random_move_keys: self._key_up(VK_UP)
                    if VK_DOWN not in self._random_move_keys: self._key_down(VK_DOWN)
                self._climb_up_pressed = True
                _debug_log("[爬梯] 延时%dms后按%s键抓梯子" % (delay, "上" if self._climb_direction > 0 else "下"))
                return False

            # 2. 按上键后等Y变化确认抓到梯子
            if up_pressed:
                y_changed = abs(py - self._climb_start_y) > 3
                if y_changed:
                    # 抓到梯子了，开始攀爬
                    self._climb_state = "climbing"
                    self._climb_start_y = py
                    self._climb_action_time = now_ms
                    _debug_log("[爬梯-步骤4] 抓到梯子成功！Y变化%.1fpx，耗时%dms，开始攀爬目标Y=%.0f" % (
                        abs(py - self._climb_start_y), int(elapsed), self._climb_target_y))
                    return False
                # 按上键后超过400ms还没Y变化=没抓到，重置
                if elapsed - delay > 400:
                    _debug_log("[爬梯-步骤4] 上梯子失败！按上键后400ms Y未变化(当前Y=%.0f 起始Y=%.0f)，重置重试" % (
                        py, self._climb_start_y))
                    self._reset_climb()
                    return False
            else:
                # 还没到延时，等
                if elapsed > 600:
                    _debug_log("[爬梯-步骤3] 跳抓超时600ms，重置重试")
                    self._reset_climb()
                    return False
            return False

        if self._climb_state == "climbing":
            # 攀爬停滞检测：Y超过1.5秒没变化=没在梯子上，重置重试
            now_ms = time.time() * 1000
            if now_ms - self._climb_action_time > 1500 and abs(py - self._climb_start_y) < 5:
                _debug_log("[爬梯-步骤5] 攀爬停滞！1.5秒Y未变化(当前Y=%.0f)，重置重试" % py)
                self._reset_climb()
                return False
            # 持续按住上/下，检测是否到达目标高度
            cdy = self._climb_target_y - py
            if abs(cdy) <= 4:
                # 到达目标高度，停止攀爬
                _debug_log("[爬梯-步骤5] 到达目标高度！当前Y=%.0f 目标Y=%.0f 差值=%.0f，攀爬完成，重新检测怪物" % (
                    py, self._climb_target_y, cdy))
                self._reset_climb()
                return False  # 下一轮继续水平移动到目标x
            # 修正方向（可能爬过了）
            if cdy > 0 and self._climb_direction < 0:
                self._climb_direction = 1
                if VK_DOWN in self._random_move_keys:
                    self._key_up(VK_DOWN)
                if VK_UP not in self._random_move_keys:
                    self._key_down(VK_UP)
            elif cdy < 0 and self._climb_direction > 0:
                self._climb_direction = -1
                if VK_UP in self._random_move_keys:
                    self._key_up(VK_UP)
                if VK_DOWN not in self._random_move_keys:
                    self._key_down(VK_DOWN)
            return False

        # === 向上跳状态（跳跃键，检测y是否上升）===
        if self._climb_state == "jump_up":
            now_ms = time.time() * 1000
            elapsed = now_ms - self._climb_action_time
            # 小地图y减小=向上移动
            went_up = py < self._climb_start_y - 5
            if went_up:
                if abs(py - self._climb_target_y) <= 8:
                    self._reset_climb()
                else:
                    self._climb_state = "none"
                return False
            if elapsed > 800:
                # 跳不上去（Y未上升），设置3秒冷却，直接改用梯子，不反复跳
                self._jump_up_fail_time = now_ms
                ladder = self._find_nearest_ladder(px, py, self._climb_target_y)
                if ladder:
                    self._climb_state = "to_ladder"
                    self._climb_ladder_x = ladder["x"]
                    self._climb_direction = 1
                    self._climb_ladder_y_ref = ladder["y_bottom"]
                    _debug_log("[上跳] 跳不上去，改用梯子x=%.0f" % ladder["x"])
                else:
                    self._climb_state = "none"
                    _debug_log("[上跳] 跳不上去且无梯子，重置")
                return False
            return False

        # === 向下跳状态（下+跳跃键，检测y是否下降）===
        if self._climb_state == "jump_down":
            now_ms = time.time() * 1000
            elapsed = now_ms - self._climb_action_time
            # 检测y是否下降（小地图y增大=向下移动）
            went_down = py > self._climb_start_y + 5
            if went_down:
                # 成功跳下，松开下键
                self._key_up(VK_DOWN)
                if abs(py - self._climb_target_y) <= 8:
                    self._reset_climb()
                else:
                    # 还没到目标层，下一轮继续判断（可能再跳或走梯子）
                    self._climb_state = "none"
                return False
            if elapsed > 800:
                # 跳不下去（Y未下降），设置3秒冷却，直接改用梯子，不反复跳
                self._jump_down_fail_time = now_ms
                self._key_up(VK_DOWN)
                ladder = self._find_nearest_ladder(px, py, self._climb_target_y)
                if ladder:
                    self._climb_state = "to_ladder"
                    self._climb_ladder_x = ladder["x"]
                    self._climb_direction = -1
                    self._climb_ladder_y_ref = ladder["y_top"]
                    _debug_log("[下跳] 跳不下去，改用梯子x=%.0f" % ladder["x"])
                else:
                    self._climb_state = "none"
                    _debug_log("[下跳] 跳不下去且无梯子，重置")
                return False
            return False

        # === 瞬移状态（方向键+瞬移技能，检测是否生效）===
        if self._climb_state == "teleport":
            now_ms = time.time() * 1000
            elapsed = now_ms - self._climb_action_time
            y_changed = abs(py - self._climb_start_y) > 3
            if y_changed or elapsed > 800:
                if abs(py - self._climb_target_y) <= 8:
                    self._reset_climb()
                    return False
                # 没到目标层，再瞬移一次（最多3秒）
                if elapsed > 3000:
                    self._reset_climb()
                    _debug_log("[瞬移] 多次未到达目标，改用梯子")
                else:
                    self._do_teleport(py)
            return False

        # === 正常移动（非攀爬状态）===
        # 先判断目标是否在当前平台曲线上（斜坡/高低差平台），在的话直接水平走，不触发梯子/跳跃
        current_pf = self._get_current_platform()
        target_on_same_pf = False
        if current_pf:
            pts = self._platform_points(current_pf)
            if self._point_to_polyline_dist(target_x, target_y, pts) <= 12:
                target_on_same_pf = True
        else:
            # current_pf=None（光点抖动/scale不准导致没匹配到平台）
            # 用目标点反查属于哪个平台，再判断玩家Y是否在该平台范围内
            target_pf = None
            for pf in self.platforms:
                pts = self._platform_points(pf)
                if self._point_to_polyline_dist(target_x, target_y, pts) <= 12:
                    target_pf = pf
                    break
            if target_pf:
                tpts = self._platform_points(target_pf)
                ty_min = min(p[1] for p in tpts)
                ty_max = max(p[1] for p in tpts)
                # 玩家Y在目标平台Y范围内（±15容忍），算同平台
                if ty_min - 15 <= py <= ty_max + 15:
                    target_on_same_pf = True
                    current_pf = target_pf
                    _debug_log("[路线] current_pf=None，反查目标平台成功，玩家Y=%.0f在平台Y范围[%.0f,%.0f]内，按同平台处理" % (py, ty_min, ty_max))

        if not target_on_same_pf:
            # 不同平台：目标点不在当前绿线上 → 走梯子/瞬移
            now_ms = time.time() * 1000
            fight_cfg = self._get_fight_config()
            tp_key = fight_cfg.get("teleport_key", "")
            tp_dist = fight_cfg.get("teleport_distance", 0)
            going_up = target_y < py
            _debug_log("[路线-步骤1] 目标(%.0f,%.0f)不在当前平台，玩家(%.0f,%.0f)，dy=%.0f，向%s" % (
                target_x, target_y, px, py, dy, "上" if going_up else "下"))

            # 1. 瞬移（没配置直接忽略）
            if tp_key and tp_dist > 0:
                self._climb_state = "teleport"
                self._climb_target_y = target_y
                self._climb_direction = 1 if going_up else -1
                self._do_teleport(py)
                _debug_log("[路线-步骤2] 瞬移，距离配置=%d，方向=%s" % (tp_dist, "上" if going_up else "下"))
                return False
            # 2. 找连接当前平台和目标平台的梯子（验证上下端点Y/X值）
            ladder = self._find_connecting_ladder(px, py, target_y, going_up, current_pf)
            if ladder:
                self._climb_state = "to_ladder"
                self._climb_ladder_x = ladder["x"]
                self._climb_target_y = target_y
                self._climb_direction = 1 if going_up else -1
                self._climb_ladder_y_ref = ladder["y_bottom"] if going_up else ladder["y_top"]
                _debug_log("[路线-步骤2] 找到梯子x=%.0f 上端Y=%.0f 下端Y=%.0f，玩家(%.0f,%.0f)，ldx=%.0f，开始向梯子移动" % (
                    ladder["x"], ladder["y_top"], ladder["y_bottom"], px, py, ladder["x"] - px))
                return False
            else:
                _debug_log("[路线-步骤2] 未找到连接梯子，回退水平移动")
        else:
            # 同平台：小台阶只在水平移动中边走边跳（dy在2-8之间，超过8是不同平台）
            pass  # 跳跃逻辑移到下方水平移动块中，避免站原地空跳

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
            # 同平台小台阶：Y差2-8小地图单位时边走边跳（超过8是不同平台，走梯子/瞬移）
            # 跳跃反馈：如果这个位置最近跳失败过，不跳，直接继续走（或走梯子）
            if target_on_same_pf and 2 < abs(dy) <= 8 and not jump_blocked:
                fight_cfg = self._get_fight_config()
                jump_key = fight_cfg.get("jump_key", "")
                if jump_key:
                    last_jump = getattr(self, '_last_platform_gap_jump', 0)
                    if now_ms - last_jump > 400:
                        self._press_game_key(jump_key, duration=60)
                        self._last_platform_gap_jump = now_ms
                        self._last_jump_y = py  # 记录跳跃前Y，用于反馈检测
                        self._last_jump_time = now_ms
                        if time.time() - getattr(self, '_last_same_pf_log', 0) > 2:
                            self._last_same_pf_log = time.time()
                            _debug_log("[路线] 同平台小台阶 dy=%.0f，边走边跳" % dy)
        else:
            if VK_LEFT in self._random_move_keys:
                self._key_up(VK_LEFT)
            if VK_RIGHT in self._random_move_keys:
                self._key_up(VK_RIGHT)

        # 到达判断
        if abs(dx) <= 4 and abs(dy) <= 6:
            self._reset_climb()
            return True
        return False

    def _random_step(self, player_pos):
        """随机模式每帧状态机"""
        if not self._random_running:
            return
        # 拟人化休息中：路线系统也不移动
        if getattr(self, '_resting', False):
            self._release_all_keys()
            return

        if self._random_state == "idle":
            if self.route_mode == "手动":
                # 手动模式：用当前指定的方案，不随机选
                route_id = self.current_route if self._route_has_file(self.current_route) else None
            else:
                # 随机模式：随机选方案（排除上一个）
                route_id = self._random_pick_route()
            if route_id is None:
                # 没有保存路线时原地打怪，不跑平台，只检测身边怪（保持_running=True战斗继续）
                if not getattr(self, '_random_no_route_logged', False):
                    self._random_no_route_logged = True
                    print("[随机] 没有可用路线，原地打怪中（不跑平台）")
                    _debug_log("[随机] 没有可用路线，原地打怪中（不跑平台）")
                    self._add_log("无路线，原地打怪中")
                return
            self._switch_route(route_id)
            self._random_route_id = route_id
            self._random_platform_idx = 0
            self._random_state = "moving"
            print("[随机] 选择方案%d（%d平台），开始逐个打" % (route_id, len(self.platforms)))

        elif self._random_state == "moving":
            self._route_moving = True
            # 遇怪即停：移动途中检测到同平台怪（区分近战/远程），立即停下来打
            if self._monsters and self._player_screen_pos:
                _, ppy = self._player_screen_pos
                fight_cfg = self._get_fight_config()
                atk_dist = fight_cfg.get("atk1_distance", 150)
                y_thresh = 100 if atk_dist >= 250 else 50
                nearby = [m for m in self._monsters if abs(m[3] - ppy) <= y_thresh]
                if nearby:
                    self._release_all_keys()
                    self._random_state = "attacking"
                    self._route_moving = False
                    self._random_attack_start = time.time()
                    _debug_log("[路线] moving中遇怪%d只(Y差≤%d)，立即停下战斗" % (len(nearby), y_thresh))
                    return
                elif time.time() - getattr(self, '_last_route_nomonster_log', 0) > 2:
                    self._last_route_nomonster_log = time.time()
                    y_gaps = [abs(m[3] - ppy) for m in self._monsters[:5]]
                    _debug_log("[路线] moving中检测%d只怪但Y差都>%d(最近:%s)，继续移动" % (
                        len(self._monsters), y_thresh, y_gaps))
            if self._random_platform_idx >= len(self.platforms):
                # 全部平台打完，回起点
                self._random_state = "returning"
                return
            # 智能选平台覆盖：战斗系统设置了目标平台，直接去那里
            if self._route_target_platform_override is not None:
                self._random_platform_idx = self._route_target_platform_override
                self._route_target_platform_override = None
                _debug_log("[路线] 智能选平台覆盖：直接去平台%d" % self._random_platform_idx)
            pf = self.platforms[self._random_platform_idx]
            pts = self._platform_points(pf)
            # 目标=曲线中点（路径中间的点）
            mid_pt = pts[len(pts) // 2]
            target_x, target_y = float(mid_pt[0]), float(mid_pt[1])
            arrived = self._move_to(player_pos, target_x, target_y)
            # 路线诊断日志（每1秒一次）
            if player_pos and time.time() - getattr(self, '_last_route_log', 0) > 1.0:
                self._last_route_log = time.time()
                px, py = player_pos
                _debug_log("[路线] 平台%d/%d 状态=%s 玩家(%.0f,%.0f) 目标(%.0f,%.0f) dx=%.0f dy=%.0f climb=%s" % (
                    self._random_platform_idx + 1, len(self.platforms),
                    self._random_state, px, py, target_x, target_y,
                    target_x - px, target_y - py, self._climb_state))
            if arrived:
                self._release_all_keys()
                self._random_state = "attacking"
                self._route_moving = False
                self._random_attack_start = time.time()
                print("[随机] 到达平台%d，战斗接管" % self._random_platform_idx)

        elif self._random_state == "attacking":
            self._route_moving = False
            # 当前平台清完后才切换下一个平台（至少1秒避免YOLO未检测到就走）
            attack_elapsed = time.time() - self._random_attack_start
            if attack_elapsed > 1.0:
                monsters_on_platform = self._filter_monsters_on_platform(
                    self._monsters, self._player_screen_pos) if self._player_screen_pos else self._monsters
                if not monsters_on_platform:
                    self._random_platform_idx += 1
                    self._random_state = "moving"
                    print("[随机] 平台%d已清完，前往下一个" % (self._random_platform_idx - 1))

        elif self._random_state == "returning":
            self._route_moving = True
            # 回到起点（第一个平台位置），然后重新随机选方案
            if self.platforms:
                pf = self.platforms[0]
                pts = self._platform_points(pf)
                mid_pt = pts[len(pts) // 2]
                target_x, target_y = float(mid_pt[0]), float(mid_pt[1])
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

    def _point_to_polyline_dist(self, px, py, points):
        """点到折线的最近距离（小地图坐标）。points为[(x,y),...]列表。"""
        if not points or len(points) < 2:
            return 999.0
        min_dist = 999.0
        for i in range(len(points) - 1):
            x1, y1 = float(points[i][0]), float(points[i][1])
            x2, y2 = float(points[i+1][0]), float(points[i+1][1])
            dx, dy = x2 - x1, y2 - y1
            if dx == 0 and dy == 0:
                d = ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
                proj_x = x1 + t * dx
                proj_y = y1 + t * dy
                d = ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5
            if d < min_dist:
                min_dist = d
        return min_dist

    def _platform_points(self, pf):
        """获取平台的折线路径点，兼容旧格式{x_min,x_max,y_base}（转成水平线）。"""
        if "points" in pf and pf["points"] and len(pf["points"]) >= 2:
            return pf["points"]
        # 旧格式兼容：生成水平直线
        x_min, x_max, y_base = pf["x_min"], pf["x_max"], pf["y_base"]
        return [[x_min, y_base], [x_max, y_base]]

    def _find_platform_at_point(self, x, y):
        """找到点(x,y)所在的平台（点到折线距离≤12），返回平台对象或None"""
        for pf in self.platforms:
            pts = self._platform_points(pf)
            if self._point_to_polyline_dist(x, y, pts) <= 12:
                return pf
        return None

    def _find_junction(self, pf1, pf2):
        """找两条平台曲线的交汇点（距离≤15的点对中点），返回(x,y)或None"""
        if pf1 is None or pf2 is None or pf1.get("id") == pf2.get("id"):
            return None
        pts1 = self._platform_points(pf1)
        pts2 = self._platform_points(pf2)
        best = None
        best_dist = 15
        for p1 in pts1:
            for p2 in pts2:
                d = ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5
                if d < best_dist:
                    best_dist = d
                    best = ((p1[0]+p2[0])//2, (p1[1]+p2[1])//2)
        return best

    def _platform_x_range(self, pf):
        """获取平台的x范围（兼容新旧格式）。"""
        pts = self._platform_points(pf)
        xs = [p[0] for p in pts]
        return min(xs), max(xs)

    def _is_monster_in_platform_range(self, monster_cx, monster_cy):
        """判断怪是否在当前平台范围内（区分近战/远程）。
        近战(攻击距离<250)：X差≤攻击距离，Y差≤50
        远程/法师(攻击距离≥250)：X差≤300，Y差≤100"""
        if not self._player_screen_pos:
            return True
        px, py = self._player_screen_pos
        fight_cfg = self._get_fight_config()
        atk_dist = fight_cfg.get("atk1_distance", 150)
        dx = abs(monster_cx - px)
        dy = abs(monster_cy - py)
        if atk_dist >= 250:
            # 远程/法师：X差≤300，Y差≤100
            return dx <= 300 and dy <= 100
        else:
            # 近战：X差≤攻击距离，Y差≤50
            return dx <= atk_dist and dy <= 50

    def extract_platform(self, points):
        """录制的路径点抽稀后保存为折线（曲线），一条录制=一个平台。"""
        if len(points) < 2:
            return []
        # 按间距抽稀（至少2小地图px一个点），保留曲线形状
        simplified = [points[0]]
        for p in points[1:]:
            last = simplified[-1]
            dist = ((p[0] - last[0]) ** 2 + (p[1] - last[1]) ** 2) ** 0.5
            if dist >= 2:
                simplified.append(p)
        if simplified[-1] != points[-1]:
            simplified.append(points[-1])
        return [{
            "id": len(self.platforms),
            "points": [[float(x), float(y)] for x, y in simplified]
        }]

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
        for vk in [VK_F5, VK_F6, VK_F8, VK_F10, VK_F12]:
            pressed = bool(user32.GetAsyncKeyState(vk) & 0x8000)
            if pressed and not self._key_state[vk]:
                _debug_log("[热键] 检测到按键 VK=0x%X" % vk)
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
            # F8弹出保存方案下拉菜单，鼠标点击选择保存到哪个方案
            self._dropdown = "save"
            print("[F8] 请选择保存方案")
        elif vk == VK_F9:
            print("Manual select triggered (F9)")
            self.manual_select_region()
        elif vk == VK_F10:
            if self.hwnd is None:
                print("[启动] 未绑定游戏窗口，请先绑定")
                self._add_log("未绑定窗口，无法启动")
            else:
                self._running = True
                # 有录制平台时同时启动路线系统（含梯子攀爬），否则纯战斗模式
                if self.platforms:
                    self._random_running = True
                    self._random_state = "idle"
                    print("[启动] F10 战斗+路线模式（%d平台%d梯子）" % (len(self.platforms), len(self.ladders)))
                else:
                    print("[启动] F10 纯战斗模式（无录制平台）")
                self._add_log("脚本已启动 F10")
                _debug_log("[启动] F10 已触发, _running=True, hwnd=%s" % self.hwnd)
        elif vk == VK_F12:
            if self._running or self._random_running:
                self._running = False
                self._resting = False  # 重置休息状态
                self._release_combat_move()  # 释放战斗中持续按住的方向键
                if self._random_running:
                    self._release_all_keys()
                    self._reset_climb()
                    self._random_running = False
                    self._random_state = "idle"
                if self._monster_overlay_running:
                    self._stop_monster_overlay()
                print("[停止] 脚本已停止 (F12)")
                self._add_log("脚本已停止 F12")

    def _on_mouse(self, event, x, y, flags, param):
        """鼠标点击回调：标签页切换 + 路线页按钮"""
        # 松开按钮：清除按下状态
        if event == cv2.EVENT_LBUTTONUP:
            self._pressed_btn = None
        if event == cv2.EVENT_LBUTTONDOWN:
            _debug_log("[鼠标] 点击 tab=%s pos=(%d,%d)" % (self._current_tab, x, y))
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

        # 路线页输入框（X/Y偏移）聚焦处理
        if event == cv2.EVENT_LBUTTONDOWN:
            self._handle_input_mouse(x, y)

        # 人物特征下拉面板（向下弹出）
        dd_top = BTN_CHAR[1] + BTN_CHAR[3]
        dd_bottom = dd_top + CHAR_DD_VISIBLE * CHAR_DD_ITEM_H
        dd_main_x2 = CHAR_DD_X + CHAR_DD_W
        dd_scroll_x2 = dd_main_x2 + CHAR_DD_SCROLL_W
        in_dd_main = (dd_top <= y < dd_bottom and CHAR_DD_X <= x < dd_main_x2)
        in_dd_scroll = (dd_top <= y < dd_bottom and dd_main_x2 <= x < dd_scroll_x2)
        in_dd = in_dd_main or in_dd_scroll
        on_char_btn = (BTN_CHAR[1] <= y < BTN_CHAR[1] + BTN_CHAR[3] and BTN_CHAR[0] <= x < BTN_CHAR[0] + BTN_CHAR[2])

        if self._char_dropdown:
            # 右键：删除单个特征
            if event == cv2.EVENT_RBUTTONDOWN and in_dd_main:
                row = (y - dd_top) // CHAR_DD_ITEM_H
                if row >= 1:  # row0是删除全部
                    slot_idx = self._char_scroll + (row - 1)
                    if 0 <= slot_idx < len(self._char_templates):
                        self._delete_char_template(slot_idx)
                return
            # 左键
            if event == cv2.EVENT_LBUTTONDOWN:
                if in_dd_main:
                    row = (y - dd_top) // CHAR_DD_ITEM_H
                    if row == 0:
                        # 删除全部
                        self._clear_character_features()
                        self._char_scroll = 0
                    else:
                        slot_idx = self._char_scroll + (row - 1)
                        if 0 <= slot_idx < len(self._char_templates):
                            self._char_dropdown = False
                            print("[鼠标] 选中人物特征#%d" % self._char_templates[slot_idx]["id"])
                        elif slot_idx < CHAR_DD_ITEMS:
                            self._char_dropdown = False
                            self._capture_character_feature()
                    return
                elif in_dd_scroll:
                    # 翻页箭头
                    mid_y = dd_top + (dd_bottom - dd_top) // 2
                    if y < mid_y:
                        self._char_scroll = max(0, self._char_scroll - 1)
                    else:
                        max_scroll = CHAR_DD_ITEMS - CHAR_DD_FEAT_PER_PAGE
                        self._char_scroll = min(max_scroll, self._char_scroll + 1)
                    return
                elif not on_char_btn:
                    # 点击菜单外收起
                    self._char_dropdown = False
                    return

        # 日志滚动条点击
        if event == cv2.EVENT_LBUTTONDOWN:
            sb_x = UI_LOG_X + UI_LOG_W - 10
            sb_y = UI_LOG_Y + 22
            sb_w = 8
            sb_h = UI_LOG_H - 24
            if sb_x <= x < sb_x + sb_w and sb_y <= y < sb_y + sb_h:
                mid = sb_y + sb_h // 2
                if y < mid:
                    self._log_scroll = max(0, self._log_scroll - 1)
                else:
                    total = len(self._runtime_logs)
                    max_lines = max(1, (UI_LOG_H - 24) // 16)
                    self._log_scroll = min(max(0, total - max_lines), self._log_scroll + 1)
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
            dd_btn_map = {"save": BTN_SAVE, "route": BTN_PLAN, "mode": BTN_MODE, "clear_route": BTN_PLAN_CLR}
            bx, by, bw, bh = dd_btn_map[self._dropdown]
            items = self._dropdown_items()
            n = len(items)
            menu_h = n * DROPDOWN_ITEM_H
            menu_y1 = by + bh
            if bx <= x < bx + bw and menu_y1 <= y < menu_y1 + menu_h:
                item_idx = (y - menu_y1) // DROPDOWN_ITEM_H
                if 0 <= item_idx < n:
                    self._handle_dropdown_item(self._dropdown, item_idx)
                self._dropdown = None
                return
            if bx <= x < bx + bw and by <= y < by + bh:
                self._dropdown = None
                return
            self._dropdown = None

        # 4. 工具栏（小地图上方，帧坐标）
        def _in(rect, x, y):
            return rect[0] <= x < rect[0]+rect[2] and rect[1] <= y < rect[1]+rect[3]

        # 按钮按下特效：命中任意按钮时记录按下状态+闪光
        _EFFECT_BTNS = [BTN_REFRESH, BTN_MANUAL, BTN_PLATFORM, BTN_LADDER, BTN_SAVE, BTN_PLAN,
                        BTN_PLATFORM_CLR, BTN_LADDER_CLR, BTN_MODE, BTN_PLAN_CLR,
                        BTN_RUN, BTN_STOP, BTN_CHAR, BTN_MONSTER]
        for _br in _EFFECT_BTNS:
            if _in(_br, x, y):
                self._pressed_btn = _br
                break

        if _in(BTN_REFRESH, x, y):
            print("[鼠标] 刷新")
            self._auto_refresh = True
            self._detect_minimap()
            self.frame_count = 0
            self.last_player_pos = None
            return
        if _in(BTN_MANUAL, x, y):
            print("[鼠标] 手动框选")
            self.manual_select_region()
            return
        # BTN_PLAN_TOOLBAR 仅显示方案名/自动，不处理点击

        # 5. 小地图区域内点击
        if UI_MAP_X <= x < UI_MAP_X + UI_MAP_W and UI_MAP_Y <= y < UI_MAP_Y + UI_MAP_H:
            return
        if _in(BTN_PLATFORM, x, y):
            print("[鼠标] 平台"); self._handle_hotkey(VK_F5); return
        if _in(BTN_LADDER, x, y):
            print("[鼠标] 梯子"); self._handle_hotkey(VK_F6); return
        if _in(BTN_SAVE, x, y):
            self._dropdown = "save" if self._dropdown != "save" else None; return
        if _in(BTN_PLAN, x, y):
            self._dropdown = "route" if self._dropdown != "route" else None; return

        # 6. 第二排按钮（清除平台/清除梯子/模式▼/清除方案▼）
        if _in(BTN_PLATFORM_CLR, x, y):
            self._pop_platform(); return
        if _in(BTN_LADDER_CLR, x, y):
            self._pop_ladder(); return
        if _in(BTN_MODE, x, y):
            self._dropdown = "mode" if self._dropdown != "mode" else None; return
        if _in(BTN_PLAN_CLR, x, y):
            self._dropdown = "clear_route" if self._dropdown != "clear_route" else None; return

        # 7. 运行/停止
        if _in(BTN_RUN, x, y):
            print("[鼠标] 运行")
            if self.route_mode == "随机":
                self._start_random()
            elif self.hwnd is not None:
                # 手动模式：有录制路线就启动路线跟随（用当前方案），没路线只启动战斗
                if self._route_has_file(self.current_route):
                    self._start_random()
                    self._add_log("路线%d已启动（手动）" % self.current_route)
                else:
                    self._running = True
                    self._add_log("战斗已启动（无路线）")
                    _debug_log("[运行] 手动模式无路线，仅启动战斗")
            else:
                self._add_log("未绑定窗口，无法启动")
                _debug_log("[运行] 未绑定窗口")
            return
        if _in(BTN_STOP, x, y):
            print("[鼠标] 停止")
            if self._random_running:
                self._stop_random()
            elif self._running:
                # 手动模式：只停战斗+蒙板
                self._running = False
                self._release_combat_move()  # 释放持续按住的方向键
                if self._monster_overlay_running:
                    self._stop_monster_overlay()
                self._add_log("战斗已停止")
                _debug_log("[停止] 手动模式已停止")
            return

        # 8. 子标签页（人物特征下拉/怪物数据，偏移框已由输入框处理）
        if _in(BTN_CHAR, x, y):
            self._char_dropdown = not self._char_dropdown
            self._bound_dropdown = False
            self._char_scroll = 0
            print("[鼠标] 人物特征下拉:", "展开" if self._char_dropdown else "收起")
            return
        if _in(BTN_MONSTER, x, y):
            _debug_log("[鼠标] 点击怪物数据按钮")
            print("[鼠标] 怪物数据 - 选择YOLO模型"); self._select_yolo_model(); return

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
            pts = self._platform_points(p)
            if len(pts) >= 2:
                cv2.polylines(display, [np.array(pts, np.int32).reshape(-1, 1, 2)], False, COLOR_PLATFORM, 1)
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

        # 手动框选拖拽矩形
        if self._selecting and self._select_rect and self._select_dragging:
            x1, y1, x2, y2 = self._select_rect
            cv2.rectangle(map_display, (x1, y1), (x2, y2), (0, 255, 255), 1)

        # === 工具栏（小地图上方）===
        draw_asset(frame, self._ui_refresh, *BTN_REFRESH)
        draw_asset(frame, self._ui_manual, *BTN_MANUAL)
        draw_asset(frame, self._ui_plan_toolbar, *BTN_PLAN_TOOLBAR)
        # 第三个框显示当前方案名或"随机"
        plan_label = "随机" if self.route_mode == "随机" else "方案%d" % self.current_route
        (plw, plh), _ = cv2.getTextSize(plan_label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        plx = BTN_PLAN_TOOLBAR[0] + (BTN_PLAN_TOOLBAR[2] - plw) // 2
        ply = BTN_PLAN_TOOLBAR[1] + (BTN_PLAN_TOOLBAR[3] + plh) // 2 - 2
        cv2.putText(frame, plan_label, (plx, ply), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)

        # === 缩放到UI尺寸并合成到背景 ===
        map_scaled = cv2.resize(map_display, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H, UI_MAP_X:UI_MAP_X+UI_MAP_W] = map_scaled

        # === 路线页按钮素材（参考图精确坐标，支持透明）===
        draw_asset(frame, self._ui_platform, *BTN_PLATFORM)
        draw_asset(frame, self._ui_ladder, *BTN_LADDER)
        draw_asset(frame, self._ui_save, *BTN_SAVE)
        draw_asset(frame, self._ui_plan, *BTN_PLAN)
        draw_asset(frame, self._ui_platform_clear, *BTN_PLATFORM_CLR)
        draw_asset(frame, self._ui_ladder_clear, *BTN_LADDER_CLR)
        draw_asset(frame, self._ui_mode, *BTN_MODE)
        draw_asset(frame, self._ui_plan_clear, *BTN_PLAN_CLR)
        draw_asset(frame, self._ui_run, *BTN_RUN)
        draw_asset(frame, self._ui_stop, *BTN_STOP)
        draw_asset(frame, self._ui_char_btn, *BTN_CHAR)
        draw_asset(frame, self._ui_offset_label, *BTN_OFFSET)
        draw_asset(frame, self._ui_monster_data, *BTN_MONSTER)
        # 在怪物数据按钮右侧白色区域显示文件夹名+BEST.ONNX（自动换行，最多2行）
        if self._yolo_model_path:
            _folder = os.path.basename(os.path.dirname(self._yolo_model_path)) or ""
            _fname = os.path.basename(self._yolo_model_path)
            if _fname.lower().endswith('.onnx'):
                _fname = _fname[:-5].upper() + ".ONNX"
            _right_x = BTN_MONSTER[0] + int(BTN_MONSTER[2] * 0.50)
            _right_w = BTN_MONSTER[2] - int(BTN_MONSTER[2] * 0.50) - 8
            _base_scale = 0.55
            _thickness = 2
            _full = ("%s\\%s" % (_folder, _fname)) if _folder else _fname
            # 先试单行
            (mw, mh), _ = cv2.getTextSize(_full, cv2.FONT_HERSHEY_SIMPLEX, _base_scale, _thickness)
            if mw <= _right_w:
                _lines = [_full]
                _scale = _base_scale
            else:
                # 超出则在 \ 处换行，最多2行
                if _folder and "\\" in _full:
                    _line1 = _folder + "\\"
                    _line2 = _fname
                else:
                    _line1 = _full
                    _line2 = ""
                # 测第二行宽度，超了就缩
                (mw2, _), _ = cv2.getTextSize(_line2, cv2.FONT_HERSHEY_SIMPLEX, _base_scale, _thickness)
                _scale = _base_scale
                if mw2 > _right_w:
                    _scale = max(0.38, _base_scale * _right_w / mw2)
                (mw1, mh), _ = cv2.getTextSize(_line1, cv2.FONT_HERSHEY_SIMPLEX, _scale, _thickness)
                if mw1 > _right_w:
                    # 第一行也超，截断
                    while _line1 and cv2.getTextSize(_line1, cv2.FONT_HERSHEY_SIMPLEX, _scale, _thickness)[0][0] > _right_w:
                        _line1 = _line1[:-2]
                    _line1 = _line1[:-1] + ".." if len(_line1) > 2 else _line1
                _lines = [_line1]
                if _line2:
                    _lines.append(_line2)
            # 绘制（垂直居中，2行时向上偏移给第二行腾空间）
            _line_h = mh + 4
            _total_h = len(_lines) * _line_h - 4
            _start_y = BTN_MONSTER[1] + (BTN_MONSTER[3] - _total_h) // 2 + mh
            for _i, _line in enumerate(_lines):
                cv2.putText(frame, _line,
                            (_right_x + 4, _start_y + _i * _line_h),
                            cv2.FONT_HERSHEY_SIMPLEX, _scale, (40, 40, 40), _thickness, cv2.LINE_AA)
        draw_asset(frame, self._ui_winbind_bg, *BTN_WINBIND)
        # 已绑定窗口下拉框
        draw_asset(frame, self._ui_bound_dropdown, UI_BOUND_X, UI_BOUND_Y, UI_BOUND_W, UI_BOUND_H)

        # === 录制状态红色闪烁指示器（在对应按钮左上角）===
        import time as _t
        if int(_t.time() * 3) % 2 == 0:
            if self.recording_platform:
                cv2.circle(frame, (BTN_PLATFORM[0] + 8, BTN_PLATFORM[1] + 8), 5, (0, 0, 255), -1)
                cv2.circle(frame, (BTN_PLATFORM[0] + 8, BTN_PLATFORM[1] + 8), 5, (0, 0, 180), 1)
            if self.recording_ladder:
                cv2.circle(frame, (BTN_LADDER[0] + 8, BTN_LADDER[1] + 8), 5, (0, 0, 255), -1)
                cv2.circle(frame, (BTN_LADDER[0] + 8, BTN_LADDER[1] + 8), 5, (0, 0, 180), 1)

        # === 下拉菜单 ===
        if self._dropdown is not None:
            items = self._dropdown_items()
            n = len(items)
            dd_btn_map = {"save": BTN_SAVE, "route": BTN_PLAN, "mode": BTN_MODE, "clear_route": BTN_PLAN_CLR}
            bx, by, bw, bh = dd_btn_map[self._dropdown]
            menu_h = n * DROPDOWN_ITEM_H
            menu_y1 = by + bh
            menu_y2 = menu_y1 + menu_h
            cv2.rectangle(frame, (bx, menu_y1), (bx + bw - 1, menu_y2 - 1), (58, 58, 58), -1)
            cv2.rectangle(frame, (bx, menu_y1), (bx + bw - 1, menu_y2 - 1), (110, 110, 110), 1)
            for i, text in enumerate(items):
                iy = menu_y1 + i * DROPDOWN_ITEM_H
                if i > 0:
                    cv2.line(frame, (bx + 3, iy), (bx + bw - 4, iy), (85, 85, 85), 1)
                is_current = False
                if self._dropdown == "route" and (i + 1) == self.current_route:
                    is_current = True
                elif self._dropdown == "mode" and text == self.route_mode:
                    is_current = True
                if is_current:
                    cv2.rectangle(frame, (bx + 1, iy + 1), (bx + bw - 2, iy + DROPDOWN_ITEM_H - 1), (0, 70, 0), -1)
                color = (0, 255, 0) if is_current else (240, 240, 240)
                cv2.putText(frame, text, (bx + 6, iy + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1)

        # === 运行日志区域（日志底板+向上流动+右侧滚动条）===
        lx, ly, lw, lh = UI_LOG_X, UI_LOG_Y, UI_LOG_W, UI_LOG_H
        draw_asset(frame, self._ui_log_bg, lx, ly, lw, lh)
        # 日志内容（新信息在底部，向上流动）
        log_content_y = UI_LOG_CONTENT_Y
        log_content_h = UI_LOG_H - (UI_LOG_CONTENT_Y - UI_LOG_Y) - 4
        line_h = 16
        max_lines = max(1, log_content_h // line_h)
        total = len(self._runtime_logs)
        # _log_scroll=0 显示最新；>0 向上滚动看历史
        end_idx = total - self._log_scroll
        start_idx = max(0, end_idx - max_lines)
        visible = self._runtime_logs[start_idx:end_idx]
        for i, entry in enumerate(visible):
            ty = log_content_y + (i + 1) * line_h - 2
            if ty > ly + lh - 2:
                break
            text = "[%s] %s" % (entry["t"], entry["msg"])
            col = entry.get("color", (40, 40, 40))
            cv2.putText(frame, text, (lx+4, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.35, col, 1)
        # 右侧滚动条
        sb_w = 8
        sb_x = lx + lw - sb_w - 2
        sb_y = log_content_y
        sb_h = log_content_h
        cv2.rectangle(frame, (sb_x, sb_y), (sb_x+sb_w-1, sb_y+sb_h-1), (220, 220, 220), -1)
        if total > max_lines:
            thumb_h = max(10, int(sb_h * max_lines / total))
            max_scroll = total - max_lines
            thumb_y = sb_y + int((sb_h - thumb_h) * (self._log_scroll / max(max_scroll, 1)))
            cv2.rectangle(frame, (sb_x+1, thumb_y), (sb_x+sb_w-2, thumb_y+thumb_h-1), (140, 140, 140), -1)

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

        # === 可拖拽准星（窗口绑定，用素材，支持透明）===
        chx, chy = self._crosshair_pos
        cs = self._crosshair_size
        if self._ui_crosshair is not None:
            draw_asset(frame, self._ui_crosshair, chx-cs//2, chy-cs//2, cs, cs)
        else:
            r = cs // 2
            cv2.circle(frame, (chx, chy), r, (0, 0, 255), 2)
            cv2.circle(frame, (chx, chy), max(1, r // 3), (0, 0, 255), -1)
            cv2.line(frame, (chx - r - 4, chy), (chx - r + 1, chy), (0, 0, 255), 2)
            cv2.line(frame, (chx + r - 1, chy), (chx + r + 4, chy), (0, 0, 255), 2)
            cv2.line(frame, (chx, chy - r - 4), (chx, chy - r + 1), (0, 0, 255), 2)
            cv2.line(frame, (chx, chy + r - 1), (chx, chy + r + 4), (0, 0, 255), 2)

        # === 准星拖拽模式提示 ===
        if self._drag_crosshair:
            cv2.putText(frame, "DRAG TO GAME WINDOW", (UI_W // 2 - 100, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # === 人物特征下拉面板（向下弹出，5行：删除全部+4特征）===
        if self._char_dropdown:
            dd_top = BTN_CHAR[1] + BTN_CHAR[3]
            dd_bottom = dd_top + CHAR_DD_VISIBLE * CHAR_DD_ITEM_H
            dd_main_x2 = CHAR_DD_X + CHAR_DD_W
            dd_scroll_x2 = dd_main_x2 + CHAR_DD_SCROLL_W
            # 主体背景
            cv2.rectangle(frame, (CHAR_DD_X, dd_top), (dd_main_x2 - 1, dd_bottom - 1), (48, 48, 48), -1)
            cv2.rectangle(frame, (CHAR_DD_X, dd_top), (dd_main_x2 - 1, dd_bottom - 1), (100, 100, 100), 1)
            # 翻页条背景
            cv2.rectangle(frame, (dd_main_x2, dd_top), (dd_scroll_x2 - 1, dd_bottom - 1), (58, 58, 58), -1)
            cv2.rectangle(frame, (dd_main_x2, dd_top), (dd_scroll_x2 - 1, dd_bottom - 1), (100, 100, 100), 1)
            # 翻页箭头
            mid_y = dd_top + (dd_bottom - dd_top) // 2
            cv2.putText(frame, "^", (dd_main_x2 + 5, mid_y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            cv2.putText(frame, "v", (dd_main_x2 + 5, dd_bottom - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            # 行0：删除全部
            cv2.line(frame, (CHAR_DD_X + 2, dd_top + CHAR_DD_ITEM_H), (dd_main_x2 - 3, dd_top + CHAR_DD_ITEM_H), (80, 80, 80), 1)
            cv2.putText(frame, "[Delete All]", (CHAR_DD_X + 18, dd_top + 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, (0, 80, 255), 1)
            # 行1-4：特征槽位
            for row in range(CHAR_DD_FEAT_PER_PAGE):
                slot_idx = self._char_scroll + row
                iy = dd_top + (row + 1) * CHAR_DD_ITEM_H
                if row > 0:
                    cv2.line(frame, (CHAR_DD_X + 2, iy), (dd_main_x2 - 3, iy), (75, 75, 75), 1)
                if slot_idx < len(self._char_templates):
                    t = self._char_templates[slot_idx]
                    try:
                        thumb = cv2.resize(t["img"], (14, 14))
                        th, tw = thumb.shape[:2]
                        if iy + 3 + th <= frame.shape[0] and CHAR_DD_X + 4 + tw <= frame.shape[1]:
                            frame[iy + 3:iy + 3 + th, CHAR_DD_X + 4:CHAR_DD_X + 4 + tw] = thumb
                    except Exception:
                        pass
                    cv2.putText(frame, "#%d %dx%d" % (t["id"], t["width"], t["height"]),
                                (CHAR_DD_X + 22, iy + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (230, 230, 230), 1)
                elif slot_idx < CHAR_DD_ITEMS:
                    cv2.putText(frame, "[%d] +" % slot_idx, (CHAR_DD_X + 6, iy + 14),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.28, (140, 140, 140), 1)
            # 滚动位置提示
            cv2.putText(frame, "%d/%d" % (self._char_scroll + 1, CHAR_DD_ITEMS - CHAR_DD_FEAT_PER_PAGE + 1),
                        (dd_main_x2 + 1, dd_top + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.22, (160, 160, 160), 1)

        # === 路线页输入框（X/Y偏移，标签下方）===
        self._draw_input_fields(frame)

        # === 按钮点击特效（仅按下变暗，圆角）===
        now_ms = time.time() * 1000
        if self._pressed_btn is not None:
            bx, by, bw, bh = self._pressed_btn
            overlay = frame.copy()
            draw_rounded_rect(overlay, bx, by, bw, bh, 10, (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
        self._btn_flashes.clear()

        # === 热键提示跑马灯（平台按钮上方空隙，透明背景，右向左流动）===
        hotkey_text = "F5平台  F6梯子  F8保存  F10开始  F12结束"
        (tw, th), _ = cv2.getTextSize(hotkey_text, cv2.FONT_HERSHEY_SIMPLEX, 0.75, 1)
        hk_text_y = 435  # 小地图底部(y=410)与平台按钮(y=451)之间空隙居中
        cv2.putText(frame, hotkey_text, (int(self._hotkey_scroll_x), hk_text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 120, 0), 1, cv2.LINE_AA)
        # 滚动：每帧左移2px，文字完全出去后从右边重新进来
        self._hotkey_scroll_x -= 2
        if self._hotkey_scroll_x + tw < 0:
            self._hotkey_scroll_x = UI_W

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

    def _rlog(self, msg, color=None):
        """添加运行日志（新信息在底部，向上流动）"""
        if color is None:
            color = (40, 40, 40)
        t = time.strftime("%H:%M:%S")
        self._runtime_logs.append({"t": t, "msg": msg, "color": color})
        if len(self._runtime_logs) > self._log_max:
            self._runtime_logs = self._runtime_logs[-self._log_max:]
        # 自动滚动到底部（最新）
        self._log_scroll = 0

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

    def _delete_char_template(self, index):
        """删除指定索引的人物特征模板"""
        if index < 0 or index >= len(self._char_templates):
            return
        t = self._char_templates.pop(index)
        img_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % t["id"])
        if os.path.exists(img_path):
            os.remove(img_path)
        self._save_char_meta()
        self._add_log("已删除人物特征#%d" % t["id"])
        print("[人物特征] 已删除 #%d" % t["id"])

    def _match_character(self, frame):
        """在游戏画面中用模板匹配查找人物位置
        Args:
            frame: 游戏窗口截图 (BGR numpy)
        Returns:
            (center_x, center_y, confidence) 或 None
            坐标为游戏窗口内的像素坐标
        """
        if not self._char_templates or frame is None:
            if not self._char_templates:
                _now = time.time()
                if not hasattr(self, '_last_no_tpl_log') or _now - self._last_no_tpl_log > 5:
                    self._last_no_tpl_log = _now
                    print("[人物匹配] 没有人物特征模板，请先在'人物特征'下拉中添加")
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
        # 匹配分数不足：节流日志提示实际分数，方便排查阈值/模板问题
        _now = time.time()
        if not hasattr(self, '_last_lowscore_log') or _now - self._last_lowscore_log > 5:
            self._last_lowscore_log = _now
            _debug_log("[人物匹配] 最佳匹配度 %.2f 低于阈值 %.2f" % (best_score, CHAR_MATCH_THRESHOLD))
        return None

    def _show_offset_feedback(self):
        """偏移视觉反馈：输入完成3秒后，在统一蒙板上让黄点闪烁约5秒"""
        if self._offset_feedback_done or self._offset_feedback_start == 0:
            return
        now_ms = time.time() * 1000
        elapsed = now_ms - self._offset_feedback_start
        if elapsed < 3000:
            return  # 等3秒
        # 只触发一次
        self._offset_feedback_done = True
        print("[偏移反馈] 偏移黄点将在蒙板上闪烁5秒")
        # 在蒙板数据中设置闪烁截止时间（蒙板主循环负责闪烁）
        if self._monster_overlay_data is not None:
            self._monster_overlay_data['blink_until'] = now_ms + 5000
        else:
            # 蒙板还没数据，先建一个空壳，等角色匹配到了自然会闪烁
            self._monster_overlay_data = {'blink_until': now_ms + 5000}

    def _start_monster_overlay(self):
        """启动怪物检测透明蒙板（置顶透明窗口，绿色线条从角色偏移点指向怪物）"""
        if self._monster_overlay_running:
            return
        self._monster_overlay_running = True
        # 保留已有数据（如偏移闪烁blink_until），不重置为None
        if self._monster_overlay_data is None:
            self._monster_overlay_data = {}
        t = threading.Thread(target=self._monster_overlay_loop, daemon=True)
        self._monster_overlay_thread = t
        t.start()
        _debug_log("[怪物蒙板] 已启动（人物模板%d套，阈值%.2f）" % (len(self._char_templates), CHAR_MATCH_THRESHOLD))
        if not self._char_templates:
            self._add_log("蒙板已启动，但未添加人物特征模板，黄点不会显示")

    def _stop_monster_overlay(self):
        """停止怪物检测透明蒙板"""
        self._monster_overlay_running = False
        self._monster_overlay_data = None
        # Force destroy the overlay window immediately (don't wait for thread loop)
        if self._overlay_hwnd:
            try:
                user32 = ctypes.windll.user32
                user32.DestroyWindow(self._overlay_hwnd)
                _debug_log("[怪物蒙板] 强制销毁窗口 hwnd=%s" % self._overlay_hwnd)
            except Exception as e:
                _debug_log("[怪物蒙板] DestroyWindow异常: %s" % e)
            self._overlay_hwnd = None
        # Wait for overlay thread to exit (max 1 second)
        if self._monster_overlay_thread and self._monster_overlay_thread.is_alive():
            self._monster_overlay_thread.join(timeout=1.0)
            _debug_log("[怪物蒙板] 线程已join")
        _debug_log("[怪物蒙板] 已停止")

    def _monster_overlay_loop(self):
        """后台线程：创建置顶透明蒙板窗口，每100ms更新
        优先使用Win32原生API（打包可靠），失败回退tkinter
        统一显示：角色偏移黄点 + 怪物绿框/连线 + 血条红点 + 蓝条蓝点"""
        try:
            self._win32_overlay_loop()
        except Exception as e:
            _debug_log("[怪物蒙板] Win32窗口失败: %s" % e)
            try:
                self._tkinter_overlay_loop()
            except Exception as e2:
                _debug_log("[怪物蒙板] tkinter也失败: %s" % e2)
        finally:
            # 线程退出时重置标志，允许下次重启
            self._monster_overlay_running = False
            _debug_log("[怪物蒙板] 线程已退出，标志已重置")

    def _win32_overlay_loop(self):
        """Win32原生分层透明窗口（不依赖tkinter，打包后可靠）"""
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        kernel32 = ctypes.windll.kernel32
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

        # === 64位函数签名（必须设置，否则句柄被截断成32位）===
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.RegisterClassW.argtypes = [ctypes.c_void_p]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetTimer.restype = ctypes.c_void_p
        user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p]
        user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.BeginPaint.restype = wintypes.HDC
        user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.EndPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
        user32.PeekMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.TranslateMessage.argtypes = [ctypes.c_void_p]
        user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
        user32.DefWindowProcW.restype = ctypes.c_longlong
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        gdi32.CreateSolidBrush.restype = ctypes.c_void_p
        gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
        gdi32.CreatePen.restype = ctypes.c_void_p
        gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi32.SelectObject.restype = ctypes.c_void_p
        gdi32.SelectObject.argtypes = [wintypes.HDC, ctypes.c_void_p]
        user32.FillRect.restype = ctypes.c_int
        user32.FillRect.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.HBRUSH]
        gdi32.MoveToEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        gdi32.LineTo.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi32.Rectangle.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        gdi32.Ellipse.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
        gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        gdi32.TextOutW.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
        gdi32.GetStockObject.restype = ctypes.c_void_p
        gdi32.GetStockObject.argtypes = [ctypes.c_int]

        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080
        WS_POPUP = 0x80000000
        WS_VISIBLE = 0x10000000
        LWA_COLORKEY = 0x00000001
        WM_PAINT = 0x000F
        WM_TIMER = 0x0113
        WM_DESTROY = 0x0002
        WM_ERASEBKGND = 0x0014
        COLOR_MAGENTA = 0x00FF00FF  # BGR: R=255,G=0,B=255
        IDT_TIMER = 1

        # 回调函数类型（必须在WNDCLASS之前定义，字段类型用它）
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class PAINTSTRUCT(ctypes.Structure):
            _fields_ = [
                ("hdc", wintypes.HDC),
                ("fErase", wintypes.BOOL),
                ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL),
                ("fIncUpdate", wintypes.BOOL),
                ("rgbReserved", wintypes.BYTE * 32),
            ]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", wintypes.POINT),
            ]

        hinst = kernel32.GetModuleHandleW(None)
        if not hasattr(self, '_overlay_class_seq'):
            self._overlay_class_seq = 0
        self._overlay_class_seq += 1
        className = "MapleBotOverlay_%d_%d" % (id(self), self._overlay_class_seq)
        first_draw = [True]
        _paint_count = [0]

        def wnd_proc(hwnd, msg, wParam, lParam):
            try:
                if msg == WM_TIMER:
                    user32.InvalidateRect(hwnd, None, True)
                    return 0
                elif msg == WM_ERASEBKGND:
                    return 1
                elif msg == WM_PAINT:
                    _paint_count[0] += 1
                    if _paint_count[0] <= 3 or _paint_count[0] % 30 == 0:
                        _debug_log("[怪物蒙板] WM_PAINT 第%d次" % _paint_count[0])
                    ps = PAINTSTRUCT()
                    hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                    gdi_objs = []
                    try:
                        rect = wintypes.RECT()
                        user32.GetClientRect(hwnd, ctypes.byref(rect))
                        brush = gdi32.CreateSolidBrush(COLOR_MAGENTA)
                        if brush:
                            gdi_objs.append(brush)
                        user32.FillRect(hdc, ctypes.byref(rect), brush)
                        data = self._monster_overlay_data
                        now_ms = time.time() * 1000
                        if data:
                            # HP/MP阈值标记框已移除——mss截屏会截到蒙板，
                            # 红/蓝框画在血条上会被当成填充色，导致吃药检测永远不触发
                            # MP标签最佳匹配位置（绿=匹配成功,红=匹配失败，方便看程序匹配到哪里）
                            mp_lpos = data.get('mp_label_pos')
                            if mp_lpos:
                                lx, ly, lw, lh = mp_lpos[:4]
                                visible = mp_lpos[4] if len(mp_lpos) > 4 else True
                                box_color = 0x00FF00 if visible else 0x0000FF
                                ypen = gdi32.CreatePen(0, 2, box_color)
                                if ypen:
                                    gdi_objs.append(ypen)
                                old_pen2 = gdi32.SelectObject(hdc, ypen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))
                                gdi32.Rectangle(hdc, lx, ly, lx + lw, ly + lh)
                                gdi32.SelectObject(hdc, old_pen2)
                            char_pos = data.get('char_pos')
                            if char_pos:
                                if first_draw[0]:
                                    first_draw[0] = False
                                    _debug_log("[怪物蒙板] 首次绘制黄点 at %s" % (char_pos,))
                                cx, cy = char_pos
                                blink_until = data.get('blink_until', 0)
                                draw_dot = True
                                r = 5
                                if blink_until > now_ms:
                                    if int(now_ms / 300) % 2 == 0:
                                        r = 6
                                    else:
                                        draw_dot = False
                                if draw_dot:
                                    pen = gdi32.CreatePen(0, 2, 0x0080FF)
                                    if pen:
                                        gdi_objs.append(pen)
                                    brush = gdi32.CreateSolidBrush(0x00FFFF)
                                    if brush:
                                        gdi_objs.append(brush)
                                    old_pen = gdi32.SelectObject(hdc, pen)
                                    old_brush = gdi32.SelectObject(hdc, brush)
                                    gdi32.Ellipse(hdc, cx - r, cy - r, cx + r + 1, cy + r + 1)
                                    gdi32.SelectObject(hdc, old_pen)
                                    gdi32.SelectObject(hdc, old_brush)
                                green_pen = gdi32.CreatePen(0, 2, 0x00FF00)
                                if green_pen:
                                    gdi_objs.append(green_pen)
                                old_pen = gdi32.SelectObject(hdc, green_pen)
                                null_brush = gdi32.GetStockObject(5)
                                old_brush = gdi32.SelectObject(hdc, null_brush)
                                for (x1, y1, x2, y2, score) in data.get('monsters', []):
                                    mx, my = (x1 + x2) // 2, (y1 + y2) // 2
                                    gdi32.MoveToEx(hdc, cx, cy, None)
                                    gdi32.LineTo(hdc, mx, my)
                                    gdi32.Rectangle(hdc, x1, y1, x2, y2)
                                    # 置信度显示在怪物框上方
                                    conf_txt = "%.0f%%" % (score * 100)
                                    gdi32.SetTextColor(hdc, 0x00FF00)
                                    gdi32.SetBkMode(hdc, 1)
                                    gdi32.TextOutW(hdc, x1, max(0, y1 - 16), conf_txt, len(conf_txt))
                                gdi32.SelectObject(hdc, old_pen)
                                gdi32.SelectObject(hdc, old_brush)

                                # 锁定目标：黄色粗框(4px) + 黄色连线 + "LOCK"标签
                                locked = data.get('locked_target')
                                if locked:
                                    lcx, lcy = locked
                                    # 找锁定目标的bbox（锁定目标存的是脚的位置y2，用y2匹配）
                                    lx1, ly1, lx2, ly2 = lcx-25, lcy-40, lcx+25, lcy+10
                                    for (x1, y1, x2, y2, score) in data.get('monsters', []):
                                        mx = (x1 + x2) // 2
                                        if abs(mx - lcx) < 40 and abs(y2 - lcy) < 50:
                                            lx1, ly1, lx2, ly2 = x1, y1, x2, y2
                                            break
                                    yellow_pen = gdi32.CreatePen(0, 4, 0x00FFFF)
                                    if yellow_pen:
                                        gdi_objs.append(yellow_pen)
                                    old_ypen = gdi32.SelectObject(hdc, yellow_pen)
                                    gdi32.SelectObject(hdc, gdi32.GetStockObject(5))
                                    gdi32.Rectangle(hdc, lx1, ly1, lx2, ly2)
                                    # 黄色连线
                                    gdi32.MoveToEx(hdc, cx, cy, None)
                                    gdi32.LineTo(hdc, (lx1+lx2)//2, (ly1+ly2)//2)
                                    gdi32.SelectObject(hdc, old_ypen)
                                    # LOCK标签
                                    gdi32.SetTextColor(hdc, 0x00FFFF)
                                    gdi32.SetBkMode(hdc, 1)
                                    lock_txt = "LOCK"
                                    gdi32.TextOutW(hdc, lx1, max(0, ly1 - 20), lock_txt, len(lock_txt))
                                for (x1, y1, x2, y2, score) in data.get('monsters', []):
                                    mx, my = (x1 + x2) // 2, (y1 + y2) // 2
                                    dist = int(((mx - cx) ** 2 + (my - cy) ** 2) ** 0.5)
                                    txt = str(dist)
                                    gdi32.SetTextColor(hdc, 0x00FF00)
                                    gdi32.SetBkMode(hdc, 1)
                                    gdi32.TextOutW(hdc, (cx + mx) // 2 - 8, (cy + my) // 2 - 7, txt, len(txt))
                                # 怪物头顶血条绿色标记（近战挡住怪时凭血条定位）
                                for (bx, by, bw, bh) in data.get('monster_hp_bars', []):
                                    gdi32.Rectangle(hdc, bx, by, bx + bw, by + bh)
                    except Exception as e:
                        _debug_log("[怪物蒙板] 绘制异常: %s" % e)
                    finally:
                        for _obj in gdi_objs:
                            try:
                                gdi32.DeleteObject(_obj)
                            except Exception:
                                pass
                        user32.EndPaint(hwnd, ctypes.byref(ps))
                    return 0
                elif msg == WM_DESTROY:
                    user32.KillTimer(hwnd, IDT_TIMER)
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, msg, wParam, lParam)
            except Exception as _e:
                try:
                    _debug_log("[怪物蒙板] wnd_proc未捕获异常 msg=%d: %s" % (msg, _e))
                except Exception:
                    pass
                return 0

        wnd_proc_ref = WNDPROC(wnd_proc)
        # 保留所有历史回调对象，防止被GC后旧窗口残余消息调用已回收内存
        if not hasattr(self, '_overlay_wndprocs'):
            self._overlay_wndprocs = []
        self._overlay_wndprocs.append(wnd_proc_ref)
        self._overlay_wndproc = wnd_proc_ref

        wc = WNDCLASS()
        wc.lpfnWndProc = wnd_proc_ref
        wc.hInstance = hinst
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszClassName = className
        atom = user32.RegisterClassW(ctypes.byref(wc))
        _debug_log("[怪物蒙板] RegisterClass atom=%s hinst=%s" % (atom, hinst))
        if not atom:
            _err = ctypes.get_last_error()
            _debug_log("[怪物蒙板] RegisterClass失败 err=%d，先注销再重试" % _err)
            try:
                user32.UnregisterClassW(className, hinst)
            except Exception:
                pass
            atom = user32.RegisterClassW(ctypes.byref(wc))
            _debug_log("[怪物蒙板] RegisterClass重试 atom=%s" % atom)

        hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST,
            className, "Overlay", WS_POPUP | WS_VISIBLE,
            0, 0, 100, 100, None, None, hinst, None)
        _debug_log("[怪物蒙板] CreateWindow hwnd=%s" % hwnd)
        self._overlay_hwnd = hwnd
        if not hwnd:
            err = ctypes.get_last_error()
            _debug_log("[怪物蒙板] CreateWindowExW失败, 错误码: %d" % err)
            raise RuntimeError("CreateWindowExW失败, 错误码: %d" % err)

        user32.SetLayeredWindowAttributes(hwnd, COLOR_MAGENTA, 0, LWA_COLORKEY)
        user32.ShowWindow(hwnd, 5)  # SW_SHOW
        # 创建后立即定位到游戏窗口，不依赖循环第一次迭代
        if self.hwnd and self.window_rect:
            wr = self.window_rect
            _debug_log("[怪物蒙板] 立即定位: %dx%d +%d+%d" % (wr['width'], wr['height'], wr['left'], wr['top']))
            user32.SetWindowPos(hwnd, -1, wr['left'], wr['top'],
                                wr['width'], wr['height'], 0x0050)
        else:
            # 无游戏窗口坐标时默认显示在屏幕中央，确保窗口可见用于诊断
            _sw = user32.GetSystemMetrics(0)
            _sh = user32.GetSystemMetrics(1)
            _dw, _dh = 800, 600
            _dx, _dy = (_sw - _dw) // 2, (_sh - _dh) // 2
            _debug_log("[怪物蒙板] 无游戏坐标，默认定位: %dx%d +%d+%d" % (_dw, _dh, _dx, _dy))
            user32.SetWindowPos(hwnd, -1, _dx, _dy, _dw, _dh, 0x0050)
        user32.UpdateWindow(hwnd)
        user32.SetTimer(hwnd, IDT_TIMER, 100, None)
        _vis = user32.IsWindowVisible(hwnd)
        _style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        _debug_log("[怪物蒙板] 窗口状态: visible=%s exstyle=0x%X" % (_vis, _style))
        _debug_log("[怪物蒙板] Win32窗口已创建，等待数据...")

        msg = MSG()
        while self._monster_overlay_running:
            try:
                if self.hwnd and self.window_rect:
                    wr = self.window_rect
                    if first_draw[0]:
                        _debug_log("[怪物蒙板] 窗口几何: %dx%d +%d+%d" % (wr['width'], wr['height'], wr['left'], wr['top']))
                    user32.SetWindowPos(hwnd, -1, wr['left'], wr['top'],
                                        wr['width'], wr['height'], 0x0050)
                elif first_draw[0]:
                    _debug_log("[怪物蒙板] 警告：hwnd或window_rect无效")
            except Exception as e:
                _debug_log("[怪物蒙板] SetWindowPos异常: %s" % e)

            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_DESTROY:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.05)

        user32.DestroyWindow(hwnd)
        self._overlay_hwnd = None
        try:
            user32.UnregisterClassW(className, hinst)
        except Exception:
            pass
        _debug_log("[怪物蒙板] Win32窗口已销毁")

    def _tkinter_overlay_loop(self):
        """tkinter透明蒙板（回退方案）"""
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        overlay = tk.Toplevel(root)
        overlay.overrideredirect(True)
        overlay.attributes('-topmost', True)
        overlay.attributes('-transparentcolor', 'magenta')
        canvas = tk.Canvas(overlay, bg='magenta', highlightthickness=0, bd=0)
        canvas.pack(fill='both', expand=True)
        print("[怪物蒙板] Tk窗口已创建，等待数据...")
        _overlay_first_draw = [True]

        def update():
            if not self._monster_overlay_running:
                root.destroy()
                return
            try:
                if self.hwnd and self.window_rect:
                    wr = self.window_rect
                    overlay.geometry("%dx%d+%d+%d" % (
                        wr['width'], wr['height'], wr['left'], wr['top']))
                    if _overlay_first_draw[0]:
                        print("[怪物蒙板] 窗口几何: %dx%d +%d+%d" % (wr['width'], wr['height'], wr['left'], wr['top']))
                elif _overlay_first_draw[0]:
                    print("[怪物蒙板] 警告：hwnd或window_rect无效，蒙板无法定位")
                canvas.delete('all')
                data = self._monster_overlay_data
                now_ms = time.time() * 1000
                if data:
                    hp_marker = data.get('hp_marker')
                    if hp_marker:
                        hx, hy = hp_marker
                        # 整条HP条范围（半透明红框）
                        hp_bar_full = data.get('hp_bar_full')
                        if hp_bar_full:
                            bx, by, bw = hp_bar_full
                            canvas.create_rectangle(bx, by, bx + bw, by + 10, outline='red', width=1, dash=(2,2))
                        # 竖框检测位置（粗红框+标签）
                        canvas.create_rectangle(hx - 3, hy, hx + 3, hy + 10, outline='red', width=3)
                        canvas.create_text(hx, hy - 8, text="HP竖框", fill='red', font=('Arial', 8, 'bold'))
                    mp_marker = data.get('mp_marker')
                    if mp_marker:
                        mx, my = mp_marker
                        # 整条MP条范围（半透明蓝框）
                        mp_bar_full = data.get('mp_bar_full')
                        if mp_bar_full:
                            bx, by, bw = mp_bar_full
                            canvas.create_rectangle(bx, by, bx + bw, by + 10, outline='#0080FF', width=1, dash=(2,2))
                        # 竖框检测位置（粗蓝框+标签）
                        canvas.create_rectangle(mx - 3, my, mx + 3, my + 10, outline='#0080FF', width=3)
                        canvas.create_text(mx, my - 8, text="MP竖框", fill='#0080FF', font=('Arial', 8, 'bold'))
                    char_pos = data.get('char_pos')
                    if char_pos:
                        if _overlay_first_draw[0]:
                            _overlay_first_draw[0] = False
                            print("[怪物蒙板] 首次绘制黄点 at", char_pos)
                        cx, cy = char_pos
                        blink_until = data.get('blink_until', 0)
                        if blink_until > now_ms:
                            if int(now_ms / 300) % 2 == 0:
                                canvas.create_oval(cx - 6, cy - 6, cx + 6, cy + 6,
                                                   fill='yellow', outline='orange', width=2)
                        else:
                            canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5,
                                               fill='yellow', outline='orange', width=2)
                        for (x1, y1, x2, y2, score) in data.get('monsters', []):
                            mx, my = (x1 + x2) // 2, (y1 + y2) // 2
                            canvas.create_line(cx, cy, mx, my, fill='#00FF00', width=2)
                            canvas.create_rectangle(x1, y1, x2, y2, outline='#00FF00', width=2)
                            dist = int(((mx - cx) ** 2 + (my - cy) ** 2) ** 0.5)
                            canvas.create_text((cx + mx) // 2, (cy + my) // 2,
                                               text=str(dist), fill='#00FF00',
                                               font=('Arial', 9, 'bold'))
            except Exception as e:
                print("[怪物蒙板] 更新异常:", e)
            overlay.after(100, update)

        overlay.after(100, update)
        root.mainloop()

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
        known_ids = set(f[5] for f in FIGHT_FIELDS + POTION_FIELDS + ROUTE_FIELDS)
        to_save = {k: v for k, v in self._field_values.items() if k in known_ids and v}
        try:
            with open(INPUT_CONFIG_FILE, "w", encoding="utf-8") as fp:
                json.dump(to_save, fp, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[输入框] 保存配置失败:", e)

    def _load_yolo_config(self):
        """加载YOLO模型路径配置"""
        try:
            if os.path.exists(YOLO_CONFIG_FILE):
                with open(YOLO_CONFIG_FILE, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                self._yolo_model_path = data.get("model_path")
                if self._yolo_model_path:
                    print("[YOLO] 已配置模型:", self._yolo_model_path)
        except Exception as e:
            print("[YOLO] 加载配置失败:", e)

    def _save_yolo_config(self):
        """保存YOLO模型路径配置"""
        try:
            with open(YOLO_CONFIG_FILE, "w", encoding="utf-8") as fp:
                json.dump({"model_path": self._yolo_model_path}, fp, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[YOLO] 保存配置失败:", e)

    def _select_yolo_model(self):
        """弹出文件选择框，手动选择YOLO onnx模型文件
        优先使用Win32原生对话框（打包后可靠），失败则回退tkinter"""
        path = self._win32_open_file(
            title="选择YOLO模型文件(.onnx)",
            filter_str="ONNX模型 (*.onnx)\0*.onnx\0所有文件 (*.*)\0*.*\0",
            def_ext="onnx",
        )
        if path is None:
            return  # 用户取消
        if path is False:
            self._add_log("文件对话框打开失败，请查看日志")
            print("[YOLO] 文件对话框打开失败（Win32和tkinter均不可用）")
            return
        if path:
            self._yolo_model_path = path
            self._yolo_net = None  # 重置，强制下次重新加载
            self._save_yolo_config()
            if self._init_yolo():
                self._add_log("YOLO模型已加载: %s" % os.path.basename(path))
                print("[YOLO] 模型已加载:", path)
            else:
                self._add_log("YOLO模型加载失败")
                print("[YOLO] 模型加载失败")

    @staticmethod
    def _win32_open_file(title, filter_str, def_ext=""):
        """Win32原生打开文件对话框，返回路径字符串或None（取消）/False（失败）"""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            comdlg32 = ctypes.windll.comdlg32

            # 正确设置64位函数签名
            user32.FindWindowW.restype = wintypes.HWND
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetCurrentThreadId.restype = wintypes.DWORD
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            user32.BringWindowToTop.restype = wintypes.BOOL
            user32.BringWindowToTop.argtypes = [wintypes.HWND]
            user32.SetWindowsHookExW.restype = ctypes.c_void_p
            user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]
            user32.UnhookWindowsHookEx.restype = wintypes.BOOL
            user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
            user32.CallNextHookEx.restype = ctypes.c_longlong
            user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]

            class OPENFILENAMEW(ctypes.Structure):
                _fields_ = [
                    ("lStructSize", wintypes.DWORD),
                    ("hwndOwner", wintypes.HWND),
                    ("hInstance", wintypes.HINSTANCE),
                    ("lpstrFilter", wintypes.LPCWSTR),
                    ("lpstrCustomFilter", wintypes.LPWSTR),
                    ("nMaxCustFilter", wintypes.DWORD),
                    ("nFilterIndex", wintypes.DWORD),
                    ("lpstrFile", wintypes.LPWSTR),
                    ("nMaxFile", wintypes.DWORD),
                    ("lpstrFileTitle", wintypes.LPWSTR),
                    ("nMaxFileTitle", wintypes.DWORD),
                    ("lpstrInitialDir", wintypes.LPCWSTR),
                    ("lpstrTitle", wintypes.LPCWSTR),
                    ("Flags", wintypes.DWORD),
                    ("nFileOffset", wintypes.WORD),
                    ("nFileExtension", wintypes.WORD),
                    ("lpstrDefExt", wintypes.LPCWSTR),
                    ("lCustData", wintypes.LPARAM),
                    ("lpfnHook", ctypes.c_void_p),
                    ("lpTemplateName", wintypes.LPCWSTR),
                    ("pvReserved", ctypes.c_void_p),
                    ("dwReserved", wintypes.DWORD),
                    ("FlagsEx", wintypes.DWORD),
                ]

            OFN_EXPLORER = 0x00080000
            OFN_FILEMUSTEXIST = 0x00001000
            OFN_PATHMUSTEXIST = 0x00000800
            OFN_NOCHANGEDIR = 0x00000008
            OFN_HIDEREADONLY = 0x00000004

            file_buf = ctypes.create_unicode_buffer(260)
            ofn = OPENFILENAMEW()
            ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
            ofn.lpstrFilter = filter_str
            ofn.lpstrFile = ctypes.cast(file_buf, wintypes.LPWSTR)
            ofn.nMaxFile = 260
            ofn.lpstrTitle = title
            ofn.Flags = OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_HIDEREADONLY
            ofn.lpstrDefExt = def_ext
            # 取自身UI窗口作为父窗口
            owner = user32.FindWindowW(None, "PLAY AND HAPPY")
            ofn.hwndOwner = owner if owner else None
            if owner:
                user32.SetForegroundWindow(owner)

            # CBT钩子：对话框激活时强制置顶（防止藏在其他窗口后面）
            WH_CBT = 5
            HCBT_ACTIVATE = 5
            CBTProc = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int,
                                         wintypes.WPARAM, wintypes.LPARAM)
            hook_ref = [None]  # 保持引用防止GC

            def cbt_proc(nCode, wParam, lParam):
                if nCode == HCBT_ACTIVATE:
                    dlg_hwnd = wParam
                    user32.SetForegroundWindow(dlg_hwnd)
                    user32.BringWindowToTop(dlg_hwnd)
                return user32.CallNextHookEx(hook_ref[0], nCode, wParam, lParam)

            cbt_callback = CBTProc(cbt_proc)
            hook_ref[0] = user32.SetWindowsHookExW(
                WH_CBT, cbt_callback,
                kernel32.GetModuleHandleW(None),
                kernel32.GetCurrentThreadId())
            _debug_log("[文件选择] CBT钩子=%s owner=%s structSize=%d" % (hook_ref[0], owner, ctypes.sizeof(OPENFILENAMEW)))

            result = comdlg32.GetOpenFileNameW(ctypes.byref(ofn))

            if hook_ref[0]:
                user32.UnhookWindowsHookEx(hook_ref[0])

            if result:
                _debug_log("[文件选择] 成功: %s" % file_buf.value)
                return file_buf.value
            # 返回0：用户取消或出错
            try:
                err = comdlg32.CommDlgExtendedError()
            except Exception:
                err = 0
            if err != 0:
                _debug_log("[文件选择] GetOpenFileNameW错误码: 0x%X" % err)
            else:
                _debug_log("[文件选择] 用户取消")
            return None  # 用户取消
        except Exception as e:
            _debug_log("[文件选择] Win32对话框异常: %s" % e)
            # 回退到tkinter
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                path = filedialog.askopenfilename(
                    title=title,
                    filetypes=[("ONNX模型", "*.onnx"), ("所有文件", "*.*")]
                )
                root.destroy()
                return path if path else None
            except Exception as e2:
                _debug_log("[文件选择] tkinter也失败: %s" % e2)
                return False

    def _get_fields_for_tab(self, tab):
        """返回指定标签页的字段列表"""
        if tab == "fight":
            return FIGHT_FIELDS
        elif tab == "potion":
            return POTION_FIELDS
        elif tab == "route":
            return ROUTE_FIELDS
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
            _is_offset = fid in ("char_x_offset", "char_y_offset")
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
            elif _is_offset and key == 45:  # 负号（仅偏移字段允许）
                cur = self._field_values.get(fid, "")
                if getattr(self, '_num_field_replace', False):
                    new_val = "-"
                    self._num_field_replace = False
                elif not cur.startswith("-"):
                    new_val = "-" + cur  # 在开头加负号
                else:
                    new_val = cur[1:]  # 已有负号则去掉
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

            # 偏移字段使用实际绘制区域画聚焦框
            if fid == "char_x_offset":
                fx, fy, fw, fh = OFFSET_X_DRAW
            elif fid == "char_y_offset":
                fx, fy, fw, fh = OFFSET_Y_DRAW

            # 聚焦时画橙色边框
            if is_focused:
                cv2.rectangle(frame, (fx, fy), (fx + fw - 1, fy + fh - 1),
                              INPUT_FOCUS_COLOR, 2)

            # 只在用户已录入时画值
            if val:
                if fid in ("char_x_offset", "char_y_offset"):
                    # 偏移数字：小一号、不加粗
                    fscale = 0.6
                    fthick = 1
                    (tw, th), _ = cv2.getTextSize(val, INPUT_FONT, fscale, fthick)
                    tx = fx + (fw - tw) // 2
                    ty = fy + (fh + th) // 2 - 1 + 2  # 向下微调
                    cv2.putText(frame, val, (tx, ty), INPUT_FONT, fscale,
                                INPUT_TEXT_COLOR, fthick, cv2.LINE_AA)
                else:
                    fscale = 0.32 if fh < 20 else INPUT_FONT_SCALE
                    fthick = 1 if fh < 20 else INPUT_FONT_THICKNESS
                    (tw, th), _ = cv2.getTextSize(val, INPUT_FONT, fscale, fthick)
                    tx = fx + (fw - tw) // 2
                    ty = fy + (fh + th) // 2 - 1
                    cv2.putText(frame, val, (tx, ty), INPUT_FONT, fscale,
                                INPUT_TEXT_COLOR, fthick, cv2.LINE_AA)
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
            "teleport_distance": int(self._field_values.get("teleport_distance", "0") or "0"),
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

    def _poll_num_input(self):
        """用GetAsyncKeyState轮询捕获数字输入（全局有效，不依赖UI窗口焦点）
        支持主键盘0-9、小键盘0-9、退格、回车、ESC
        只捕获新按下的键（不捕获按住不放的）"""
        if self._focused_field is None or self._is_key_field(self._focused_field):
            return
        fid = self._focused_field
        if not hasattr(self, '_prev_num_states'):
            self._prev_num_states = set()
        # 轮询：主键盘0-9(0x30-0x39) + 小键盘0-9(0x60-0x69) + 退格(0x08) + 回车(0x0D) + ESC(0x1B)
        poll_vks = list(range(0x30, 0x3A)) + list(range(0x60, 0x6A)) + [0x08, 0x0D, 0x1B, 0xBD, 0x6D]
        current = set()
        for vk in poll_vks:
            if user32.GetAsyncKeyState(vk) & 0x8000:
                current.add(vk)
        new_keys = current - self._prev_num_states
        self._prev_num_states = current
        if not new_keys:
            return
        vk = min(new_keys)
        # 解析按键
        if 0x30 <= vk <= 0x39:
            digit = chr(vk)
        elif 0x60 <= vk <= 0x69:
            digit = chr(vk - 0x60 + 0x30)  # 小键盘转数字字符
        elif vk == 0x08:
            # 退格
            cur = self._field_values.get(fid, "")
            if cur:
                self._field_values[fid] = cur[:-1]
                self._last_input_change = time.time() * 1000
            self._num_field_replace = False
            return
        elif vk == 0x0D:
            # 回车确认（HP/MP上限校验）
            val = self._field_values.get(fid, "")
            if val and fid in ("hp_value", "mp_value"):
                max_val = self._max_hp if fid == "hp_value" else self._max_mp
                if max_val > 0 and int(val) > max_val:
                    print("[校验] %s阈值 %s 超出上限 %d，已清空" % (fid, val, max_val))
                    self._field_values[fid] = ""
            self._focused_field = None
            self._save_input_config()
            self._prev_num_states = set()
            return
        elif vk == 0x1B:
            # ESC取消
            self._focused_field = None
            self._save_input_config()
            self._prev_num_states = set()
            return
        elif vk in (0xBD, 0x6D):
            # minus key - toggle negative sign only for offset fields
            if fid not in ("char_x_offset", "char_y_offset"):
                return
            cur = self._field_values.get(fid, "")
            if getattr(self, "_num_field_replace", False):
                new_val = "-"
                self._num_field_replace = False
            elif not cur.startswith("-"):
                new_val = "-" + cur
            else:
                new_val = cur[1:]
            if len(new_val) <= 10:
                self._field_values[fid] = new_val
                self._last_input_change = time.time() * 1000
                self._offset_feedback_start = time.time() * 1000
                self._offset_feedback_done = False
            return
        else:
            return
        # 数字输入：首次覆盖，后续追加
        cur = self._field_values.get(fid, "")
        if getattr(self, '_num_field_replace', False):
            new_val = digit
            self._num_field_replace = False
        else:
            new_val = cur + digit
        # HP/MP阈值百分比上限100
        if fid in ("hp_value", "mp_value") and int(new_val) > 100:
            return
        if len(new_val) <= 10:
            self._field_values[fid] = new_val
            self._last_input_change = time.time() * 1000
            if fid in ("char_x_offset", "char_y_offset"):
                self._offset_feedback_start = time.time() * 1000
                self._offset_feedback_done = False

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

    def _press_game_key(self, key_name, duration=None):
        """keybd_event发键 + AttachThreadInput强制前台。duration为按键保持ms，默认随机30-120"""
        vk = self._key_to_vk(key_name)
        if vk is None:
            _debug_log("按键未知: %s" % key_name)
            return
        if not self.hwnd:
            _debug_log("无窗口句柄")
            return
        if duration is None:
            duration = random.randint(30, 120)
        kernel32 = ctypes.windll.kernel32
        scan = user32.MapVirtualKeyW(vk, 0)
        EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0xA3, 0xA5}
        ext = 0x0001 if vk in EXTENDED_VKS else 0
        old_fg = user32.GetForegroundWindow()
        _debug_log("发键 %s vk=0x%02X scan=0x%02X ext=%d dur=%d" % (key_name, vk, scan, ext, duration))
        if old_fg != self.hwnd:
            fg_thread = user32.GetWindowThreadProcessId(old_fg, None)
            cur_thread = kernel32.GetCurrentThreadId()
            user32.AttachThreadInput(cur_thread, fg_thread, True)
            user32.BringWindowToTop(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
            user32.AttachThreadInput(cur_thread, fg_thread, False)
        time.sleep(0.03)
        user32.keybd_event(vk, scan, ext, 0)
        time.sleep(duration / 1000.0)
        user32.keybd_event(vk, scan, ext | 0x0002, 0)
        _debug_log("keybd_event已发送")
        time.sleep(0.02)
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
        # MP蓝紫色（样品色H≈160，范围放宽覆盖蓝到紫蓝）
        mp_mask = cv2.inRange(hsv, np.array([80, 50, 70]), np.array([175, 255, 255])) > 0
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

    # ========== 加药最终方案（2026-08-20）从原图取样，未经用户允许请勿修改 ==========
    # HP/MP条参考色（从用户提供的样品图直接取样，BGR格式）
    HP_REF_COLOR = (0, 0, 255)      # HP纯红（取样平均(19,19,255)，取纯红）
    MP_REF_COLOR = (249, 146, 18)   # MP蓝青色（取样平均(249,146,18)，范围B238-255 G119-170 R0-18）
    COLOR_MATCH_DIST = 55            # 欧氏距离阈值，MP蓝色有渐变，55覆盖取样范围

    # HP/MP条空的部分是灰色背景，直接取原色检测
    BAR_EMPTY_GRAY = (59, 55, 46)  # 灰色背景色（从样品图取样）
    GRAY_MATCH_DIST = 35            # 灰色欧氏距离阈值，小于此值算灰色

    def _is_bar_blank_at(self, frame, bar, pct, color_type):
        """小竖方框检测：在pct%位置取竖框，框内全部是灰色(空的部分)则判定为低于阈值。
        HP和MP空的部分都是同一个灰色背景，直接检灰色，不分红蓝。
        框内全部是灰色像素 = 空 = 血量/蓝量低于阈值 = 加药"""
        if bar is None or frame is None:
            return False
        x, y, bw = bar
        check_x = x + int(bw * pct / 100.0)
        if check_x >= frame.shape[1] or check_x < 0:
            return False
        bar_h = min(10, frame.shape[0] - y)
        if bar_h <= 0:
            return False
        gb, gg, gr = self.BAR_EMPTY_GRAY
        dist_sq = self.GRAY_MATCH_DIST ** 2
        gray_count = 0
        total = 0
        for dx in range(-1, 2):
            for dy in range(0, bar_h):
                xx = check_x + dx
                yy = y + dy
                if 0 <= xx < frame.shape[1] and 0 <= yy < frame.shape[0]:
                    b, g, r = frame[yy, xx]
                    total += 1
                    if (int(b) - gb) ** 2 + (int(g) - gg) ** 2 + (int(r) - gr) ** 2 <= dist_sq:
                        gray_count += 1
        # 框内全部是灰色（100%）→ 空 → 加药
        result = total > 0 and gray_count == total
        _debug_log("竖框灰色检测 %s: x=%d pct=%d 灰色=%d/%d -> %s" % (
            color_type, check_x, pct, gray_count, total, result))
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
        # 优先使用手动选择的模型路径
        model_path = self._yolo_model_path
        if not model_path or not os.path.exists(model_path):
            model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best.onnx")
        if not os.path.exists(model_path):
            model_path = "best.onnx"
        if not os.path.exists(model_path):
            print("[YOLO] 未找到模型文件，请点击'怪物数据'选择.onnx模型")
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
                # 完全去掉二次过滤（大小/颜色/宽高比都去掉）
                # 只靠YOLO置信度阈值，误检靠攻击后血条验证：打一下没血条就拉黑换怪
                detections.append((x1, y1, x2, y2, float(score)))
        # NMS去重
        if detections:
            boxes = [[d[0], d[1], d[2]-d[0], d[3]-d[1]] for d in detections]
            scores = [d[4] for d in detections]
            indices = cv2.dnn.NMSBoxes(boxes, scores, self._yolo_conf, self._yolo_nms)
            detections = [detections[i] for i in indices] if len(indices) > 0 else []
        return detections

    def _detect_monster_hp_bars(self, frame, search_areas=None):
        """检测怪物头顶血条，返回 [(x, y, w, h), ...]
        用纯绿色BGR检测（样本色(0,243,0)），比HSV范围更精准。
        search_areas: 限定搜索区域，None则全屏搜索"""
        if frame is None:
            return []
        h, w = frame.shape[:2]
        # 绿色血条检测：G>220 且 G>R+30 且 G>B+30
        # 正常血条BGR(0,243,0)，雾挡血条BGR(76-167,243-249,77-167)，两种都覆盖
        b, g, r = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
        green_mask = (g > 220) & (g > r + 30) & (g > b + 30)
        mask = green_mask.astype(np.uint8) * 255
        # 形态学膨胀，连接抗锯齿导致的断裂轮廓
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 2))
        mask = cv2.dilate(mask, kernel, iterations=1)
        bars = []
        areas = search_areas if search_areas else [(0, 0, w, h)]
        for (sx1, sy1, sx2, sy2) in areas:
            sx1, sy1 = max(0, sx1), max(0, sy1)
            sx2, sy2 = min(w, sx2), min(h, sy2)
            if sx2 <= sx1 or sy2 <= sy1:
                continue
            roi = mask[sy1:sy2, sx1:sx2]
            contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                x, y, bw, bh = cv2.boundingRect(cnt)
                # 血条特征：宽>高*1.5，宽度10-100px，高度1-10px
                if bw > bh * 1.5 and 10 <= bw <= 100 and 1 <= bh <= 10:
                    bars.append((sx1 + x, sy1 + y, bw, bh))
        # 去重：位置接近的只保留一个
        if bars:
            filtered = []
            for b in sorted(bars, key=lambda x: x[2] * x[3], reverse=True):
                if not any(abs(b[0] - f[0]) < 25 and abs(b[1] - f[1]) < 12 for f in filtered):
                    filtered.append(b)
            bars = filtered
        return bars

    def _get_player_screen_pos(self, frame):
        """获取人物在游戏画面中的坐标（复用_match_character内存模板+X/Y偏移，失败返回None）"""
        match = self._match_character(frame)
        if match:
            mx, my, _ = match
            x_off = int(self._field_values.get("char_x_offset", "0") or "0")
            y_off = int(self._field_values.get("char_y_offset", "0") or "0")
            return (mx + x_off, my + y_off)
        # 匹配失败：节流提示，返回None（不攻击、不显示黄点）
        _now = time.time()
        if not hasattr(self, '_last_posfail_log') or _now - self._last_posfail_log > 5:
            self._last_posfail_log = _now
            _debug_log("[人物定位] 未匹配到角色（模板%d套，阈值%.2f）" % (len(self._char_templates), CHAR_MATCH_THRESHOLD))
        return None

    def _draw_monster_overlay(self, frame, player_pos):
        """在游戏画面上画怪物框、人物位置、连线、距离、偏移信息（调试用，已由透明蒙板取代）"""
        disp = frame.copy()
        px, py = player_pos
        x_off = int(self._field_values.get("char_x_offset", "0") or "0")
        y_off = int(self._field_values.get("char_y_offset", "0") or "0")
        # 人物参考点（黄色实心圆）
        cv2.circle(disp, (px, py), 6, (0, 255, 255), -1)
        cv2.circle(disp, (px, py), 9, (0, 255, 255), 1)
        cv2.putText(disp, "PLAYER(%d,%d) X%+d Y%+d" % (px, py, x_off, y_off),
                    (px + 12, py - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        # 怪物框 + 连线 + 距离
        for i, (x1, y1, x2, y2, score) in enumerate(self._monsters):
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            cv2.rectangle(disp, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(disp, "M%d %.0f%%" % (i, score * 100), (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            cv2.line(disp, (px, py), (cx, cy), (0, 165, 255), 1)
            dist = int(np.sqrt((cx - px) ** 2 + (cy - py) ** 2))
            mid_x, mid_y = (px + cx) // 2, (py + cy) // 2
            cv2.putText(disp, str(dist), (mid_x, mid_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 165, 255), 1)
        # 左上角状态栏
        cv2.putText(disp, "Monsters:%d  Offset X:%d Y:%d" % (len(self._monsters), x_off, y_off),
                    (5, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        return disp

    def _is_mp_label_visible(self, frame):
        """全窗口搜索MP标签模板，找到=没被遮挡，没找到=被挡住。每次全图搜，简单可靠。"""
        if self._mp_label_template is None or frame is None:
            return True
        th, tw = self._mp_label_template.shape[:2]
        h, w = frame.shape[:2]
        result = cv2.matchTemplate(frame, self._mp_label_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        visible = max_val >= 0.75
        abs_x, abs_y = max_loc
        self._mp_label_pos = (abs_x, abs_y, tw, th, visible)
        if not visible:
            print("[MP标签] 全窗口未找到(匹配度=%.3f)，判定被挡" % max_val)
        return visible

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

        # 遮挡判定：MP标签被挡住时跳过吃药（避免弹窗遮挡时误判），但仍显示检测标记
        occluded = not self._is_mp_label_visible(frame)
        hp_thresh = min(int(self._field_values.get("hp_value", "30") or "30"), 100)
        mp_thresh = min(int(self._field_values.get("mp_value", "30") or "30"), 100)

        if occluded:
            # 每2秒提示一次，避免刷屏
            if now - getattr(self, '_last_occluded_log', 0) > 2000:
                self._last_occluded_log = now
                self._rlog("MP标志被挡 暂不吃药", (200, 100, 0))
                print("[吃药] MP标签被遮挡，跳过吃药")
        elif getattr(self, '_was_occluded', False):
            # 遮挡解除时提示一次
            self._rlog("遮挡解除，恢复自动吃药", (0, 180, 0))
        self._was_occluded = occluded

        if not occluded:
            # HP检测 — 小竖框内没红色=低于阈值=吃红
            hp_blank = self._is_bar_blank_at(frame, self._hp_bar, hp_thresh, "hp")
            _debug_log("HP检测: blank=%s thresh=%d key=%s bar=%s" % (hp_blank, hp_thresh, cfg.get("hp_key"), self._hp_bar))
            if hp_blank and cfg.get("hp_key"):
                if self._hp_pot_wait_until == 0:
                    self._hp_pot_wait_until = now + random.randint(0, 800)
                if now >= self._hp_pot_wait_until and now - self._last_hp_pot > self._hp_pot_delay:
                    self._press_game_key(cfg["hp_key"])
                    self._last_hp_pot = now
                    self._hp_pot_delay = random.randint(500, 1000)
                    self._hp_pot_wait_until = 0
                    self._rlog("加血 %s" % cfg["hp_key"], (0, 0, 200))
                    print("[自动吃药] HP低于%d%%, 按 %s" % (hp_thresh, cfg["hp_key"]))
            else:
                self._hp_pot_wait_until = 0

            # MP检测 — 小竖框内没蓝色=低于阈值=吃蓝
            mp_blank = self._is_bar_blank_at(frame, self._mp_bar, mp_thresh, "mp")
            _debug_log("MP检测: blank=%s thresh=%d key=%s bar=%s" % (mp_blank, mp_thresh, cfg.get("mp_key"), self._mp_bar))
            if mp_blank and cfg.get("mp_key"):
                if self._mp_pot_wait_until == 0:
                    self._mp_pot_wait_until = now + random.randint(0, 800)
                if now >= self._mp_pot_wait_until and now - self._last_mp_pot > self._mp_pot_delay:
                    self._press_game_key(cfg["mp_key"])
                    self._last_mp_pot = now
                    self._mp_pot_delay = random.randint(500, 1000)
                    self._mp_pot_wait_until = 0
                    self._rlog("加蓝 %s" % cfg["mp_key"], (200, 100, 0))
                    print("[自动吃药] MP低于%d%%, 按 %s" % (mp_thresh, cfg["mp_key"]))
            else:
                self._mp_pot_wait_until = 0

            # 吃药诊断日志（每秒一次）
            if now - getattr(self, '_last_pot_diag_log', 0) > 1000:
                self._last_pot_diag_log = now
                hp_info = "无条" if not self._hp_bar else "x=%d,w=%d" % (self._hp_bar[0], self._hp_bar[2])
                mp_info = "无条" if not self._mp_bar else "x=%d,w=%d" % (self._mp_bar[0], self._mp_bar[2])
                print("[吃药诊断] 遮挡=%s HP条:%s HP空=%s MP条:%s MP空=%s" % (
                    occluded, hp_info, hp_blank, mp_info, mp_blank))

        # 宠物食品 — 按冷却周期自动喂（不受运行状态控制，不受遮挡影响，脚本开了就生效）
        pet_key = cfg.get("pet_key", "")
        pet_cd = cfg.get("pet_cd", 0)
        if pet_key and pet_cd > 0:
            last = self._potion_last.get("pet", 0)
            if now - last > pet_cd:
                self._press_game_key(pet_key)
                self._potion_last["pet"] = now
                self._rlog("宠物食 %s" % pet_key, (0, 200, 0))
                print("[宠物食] %s 释放" % pet_key)

        # 将血条/蓝条检测点传给统一透明蒙板显示
        if self._monster_overlay_running:
            if self._monster_overlay_data is None:
                self._monster_overlay_data = {}
            # 保留已有字段（char_pos/monsters/blink_until）
            if self._hp_bar:
                hx, hy, hw = self._hp_bar
                self._monster_overlay_data['hp_marker'] = (
                    hx + int(hw * hp_thresh / 100.0), hy)
                self._monster_overlay_data['hp_bar_full'] = self._hp_bar
            else:
                self._monster_overlay_data['hp_marker'] = None
                self._monster_overlay_data['hp_bar_full'] = None
            if self._mp_bar:
                mx, my, mw = self._mp_bar
                self._monster_overlay_data['mp_marker'] = (
                    mx + int(mw * mp_thresh / 100.0), my)
                self._monster_overlay_data['mp_bar_full'] = self._mp_bar
            else:
                self._monster_overlay_data['mp_marker'] = None
                self._monster_overlay_data['mp_bar_full'] = None
            # MP标签最佳匹配位置（黄框显示，方便看程序匹配到哪里了）
            if hasattr(self, '_mp_label_pos') and self._mp_label_pos:
                self._monster_overlay_data['mp_label_pos'] = self._mp_label_pos

    def _hold_combat_key(self, vk):
        """持续按住一个键（如果没按住的话）"""
        if vk not in self._combat_held_keys:
            scan = user32.MapVirtualKeyW(vk, 0)
            ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
            user32.keybd_event(vk, scan, ext, 0)
            self._combat_held_keys.add(vk)

    def _release_combat_key(self, vk):
        """释放一个持续按住的键"""
        if vk in self._combat_held_keys:
            scan = user32.MapVirtualKeyW(vk, 0)
            ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
            user32.keybd_event(vk, scan, ext | 0x0002, 0)
            self._combat_held_keys.discard(vk)

    def _release_combat_move(self):
        """释放所有持续按住的移动键"""
        for vk in list(self._combat_held_keys):
            self._release_combat_key(vk)
        self._combat_move_dir = None

    def _set_combat_move(self, direction):
        """设置持续移动方向，direction='left'/'right'/None。流畅切换不卡顿。"""
        if direction == self._combat_move_dir:
            return
        # 先松开所有方向键
        self._release_combat_key(VK_LEFT)
        self._release_combat_key(VK_RIGHT)
        # 按新方向
        if direction == "left":
            self._hold_combat_key(VK_LEFT)
        elif direction == "right":
            self._hold_combat_key(VK_RIGHT)
        self._combat_move_dir = direction

    # ========== 加药最终方案结束（2026-08-19）未经用户允许请勿修改 ==========

    def _get_current_platform(self):
        """根据小地图玩家坐标判断当前在哪个平台上（点到折线最近距离≤10）。"""
        if not self._player_map_pos or not self.platforms:
            return None
        px, py = self._player_map_pos
        best = None
        best_dist = 999
        for pf in self.platforms:
            pts = self._platform_points(pf)
            d = self._point_to_polyline_dist(px, py, pts)
            if d < best_dist:
                best_dist = d
                best = pf
        if best and best_dist <= 10:
            return best
        return None

    def _get_player_platform(self):
        """玩家黄光点和哪条绿线重合就在哪个平台，返回平台索引，没有返回-1"""
        if not self.platforms or not self._player_map_pos:
            return -1
        px, py = self._player_map_pos
        for i, pf in enumerate(self.platforms):
            pts = self._platform_points(pf)
            if self._point_to_polyline_dist(px, py, pts) <= 12:
                return i
        return -1

    def _filter_monsters_on_platform(self, monsters, player_screen_pos):
        """过滤出当前层的怪（区分近战/远程）。
        近战(攻击距离<250)：Y差≤50
        远程/法师(攻击距离≥250)：Y差≤100"""
        if not player_screen_pos or not monsters:
            return monsters
        _, py = player_screen_pos
        fight_cfg = self._get_fight_config()
        atk_dist = fight_cfg.get("atk1_distance", 150)
        y_thresh = 100 if atk_dist >= 250 else 50
        same_layer = []
        for m in monsters:
            x1, y1, x2, y2, score = m
            if abs(y2 - py) <= y_thresh:
                same_layer.append(m)
        return same_layer

    def _is_monster_on_platform(self, monster_cx, monster_cy):
        """判断怪是否在玩家当前平台（绿线曲线）上。
        1. 有平台数据：估算怪的小地图坐标 → 点到当前平台折线距离≤12
        2. 无平台数据：回退到屏幕y差判断（怪脚vs人脚≤50）"""
        current_pf = self._get_current_platform()
        if not current_pf or not self._player_map_pos or not self._player_screen_pos:
            # 无平台数据时不限制，所有怪都可打，靠综合距离排序优先近的
            return True
        pmap_x, pmap_y = self._player_map_pos
        pscr_x, pscr_y = self._player_screen_pos
        # 小地图px/屏幕px换算比（默认0.08，录制时可自动校准）
        scale = getattr(self, '_map_screen_scale', 0.08)
        # 估算怪的小地图坐标
        m_map_x = pmap_x + (monster_cx - pscr_x) * scale
        m_map_y = pmap_y + (monster_cy - pscr_y) * scale
        # 点到平台折线距离≤12算在平台上
        pts = self._platform_points(current_pf)
        dist = self._point_to_polyline_dist(m_map_x, m_map_y, pts)
        on_platform = dist <= 12
        return on_platform

    def _get_monster_platform(self, monster_cx, monster_cy):
        """判断怪在哪个平台上，返回平台对象或None"""
        if not self.platforms or not self._player_map_pos or not self._player_screen_pos:
            return None
        pmap_x, pmap_y = self._player_map_pos
        pscr_x, pscr_y = self._player_screen_pos
        scale = getattr(self, '_map_screen_scale', 0.08)
        m_map_x = pmap_x + (monster_cx - pscr_x) * scale
        m_map_y = pmap_y + (monster_cy - pscr_y) * scale
        best = None
        best_dist = 999
        for pf in self.platforms:
            pts = self._platform_points(pf)
            d = self._point_to_polyline_dist(m_map_x, m_map_y, pts)
            if d < best_dist:
                best_dist = d
                best = pf
        if best and best_dist <= 12:
            return best
        return None

    def _curve_nearest_index(self, x, y, pts):
        """找到点(x,y)在曲线上的最近点索引"""
        best_idx = 0
        best_dist = 9999
        for i, p in enumerate(pts):
            d = ((p[0] - x) ** 2 + (p[1] - y) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best_idx = i
        return best_idx

    def _curve_arc_length(self, pts, idx1, idx2):
        """计算曲线上idx1到idx2之间的弧长"""
        if idx1 == idx2 or not pts or len(pts) < 2:
            return 0
        lo, hi = min(idx1, idx2), max(idx1, idx2)
        length = 0.0
        for i in range(lo, hi):
            length += ((pts[i+1][0] - pts[i][0]) ** 2 + (pts[i+1][1] - pts[i][1]) ** 2) ** 0.5
        return length

    def _calc_path_cost(self, monster_cx, monster_cy):
        """计算从玩家到怪的实际路径成本（屏幕像素单位）。
        同平台：沿曲线弧长 / scale
        不同平台：人→梯子底(弧长) + 梯子长×3 + 梯子顶→怪(弧长)，全部转屏幕单位
        上层到下层可跳：水平距离 + 跳跃固定成本(80)
        返回 (cost, same_platform)"""
        player_pf = self._get_current_platform()
        scale = getattr(self, '_map_screen_scale', 0.08)
        if not player_pf or not self._player_map_pos or not self._player_screen_pos:
            # 无平台数据：用近似实际距离（屏幕单位）
            h = abs(monster_cx - self._player_screen_pos[0])
            v = abs(monster_cy - self._player_screen_pos[1])
            return (h + v * 3, False)

        monster_pf = self._get_monster_platform(monster_cx, monster_cy)
        pmap_x, pmap_y = self._player_map_pos
        pscr_x, pscr_y = self._player_screen_pos
        m_map_x = pmap_x + (monster_cx - pscr_x) * scale
        m_map_y = pmap_y + (monster_cy - pscr_y) * scale

        # 第一优先级：X相差≤100且Y相差>50 → 肯定不在同平台（覆盖曲线匹配）
        dx_screen = abs(monster_cx - pscr_x)
        dy_screen = abs(monster_cy - pscr_y)
        if dx_screen <= 100 and dy_screen > 50:
            monster_pf = None  # 强制判定为不同平台

        # Y差回退：曲线匹配说不同平台，但屏幕Y差≤50 → 算同平台（scale不准时的回退，同平台斜坡Y差可能大）
        same_by_y = dy_screen <= 50
        if (not monster_pf or monster_pf.get("id") != player_pf.get("id")) and same_by_y:
            monster_pf = player_pf  # 强制判定为同平台

        # 同平台：沿曲线弧长（地图单位→屏幕单位）
        if monster_pf and monster_pf.get("id") == player_pf.get("id"):
            pts = self._platform_points(player_pf)
            p_idx = self._curve_nearest_index(pmap_x, pmap_y, pts)
            m_idx = self._curve_nearest_index(m_map_x, m_map_y, pts)
            cost_map = self._curve_arc_length(pts, p_idx, m_idx)
            return (max(cost_map / scale, 1.0), True)

        # 不同平台：找梯子连接
        player_pts = self._platform_points(player_pf)
        p_idx = self._curve_nearest_index(pmap_x, pmap_y, player_pts)

        # 找能连接两层的梯子（范围覆盖两层高度差）
        best_ladder_cost = 99999
        y_lo = min(pmap_y, m_map_y)
        y_hi = max(pmap_y, m_map_y)
        for ld in self.ladders:
            if ld["y_bottom"] + 5 >= y_lo and ld["y_top"] - 5 <= y_hi:
                lx = ld["x"]
                # 人→梯子底 的曲线距离
                l_idx = self._curve_nearest_index(lx, pmap_y, player_pts)
                dist_to_ladder = self._curve_arc_length(player_pts, p_idx, l_idx)
                # 梯子长度 × 3（攀爬成本，地图单位）
                ladder_len = abs(ld["y_bottom"] - ld["y_top"])
                # 梯子顶→怪 的距离
                if monster_pf:
                    m_pts = self._platform_points(monster_pf)
                    m_idx = self._curve_nearest_index(m_map_x, m_map_y, m_pts)
                    l_top_idx = self._curve_nearest_index(lx, m_map_y, m_pts)
                    dist_from_ladder = self._curve_arc_length(m_pts, l_top_idx, m_idx)
                else:
                    dist_from_ladder = abs(m_map_x - lx)
                total_map = dist_to_ladder + ladder_len * 3 + dist_from_ladder
                total_screen = total_map / scale
                if total_screen < best_ladder_cost:
                    best_ladder_cost = total_screen

        # 上层到下层：跳跃成本（怪在玩家下方，屏幕单位）
        jump_cost = 99999
        if m_map_y > pmap_y + 5:  # 怪在下方
            jump_cost = abs(m_map_x - pmap_x) / scale + 80

        cost = min(best_ladder_cost, jump_cost)
        return (cost, False)

    def _combat_tick(self):
        """人性化战斗：反应延迟→转身→走位→攻击，群攻3只起，带随机容错"""
        if not self._running or self.hwnd is None:
            return
        now = time.time() * 1000

        # === 拟人化随机休息：3-5分钟休息5-10秒，休息时不打怪不移动 ===
        if self._resting:
            if now >= self._rest_until:
                self._resting = False
                self._next_rest_time = now + random.randint(180000, 300000)
                print("[休息] 结束，继续战斗")
            else:
                self._release_combat_move()
                return
        elif now >= self._next_rest_time:
            self._resting = True
            self._rest_until = now + random.randint(5000, 10000)
            self._release_combat_move()
            self._release_all_keys()
            print("[休息] 开始休息%d秒（拟人化）" % ((self._rest_until - now) // 1000))
            return

        fight_cfg = self._get_fight_config()
        pot_cfg = self._get_potion_config()

        # === 释放到期的定时按键（走位用，不阻塞主循环）===
        if self._combat_timed_keys:
            _rem = []
            for _vk, _rel in self._combat_timed_keys:
                if now >= _rel:
                    _scan = user32.MapVirtualKeyW(_vk, 0)
                    _ext = 0x0001 if _vk in (0x25, 0x26, 0x27, 0x28) else 0
                    user32.keybd_event(_vk, _scan, _ext | 0x0002, 0)
                else:
                    _rem.append((_vk, _rel))
            self._combat_timed_keys = _rem

        # === YOLO怪物检测 + 血条检测（每30ms一次，33帧/秒，框跟随怪更流畅）===
        if now - self._last_yolo_check > 30:
            self._last_yolo_check = now
            _t0 = time.time()
            frame = self._capture_window()
            _t_shot = (time.time() - _t0) * 1000
            if frame is not None:
                _t1 = time.time()
                yolo_monsters = self._detect_monsters(frame)
                _t_yolo = (time.time() - _t1) * 1000
                _t2 = time.time()
                new_pos = self._get_player_screen_pos(frame)
                _t_player = (time.time() - _t2) * 1000

                # === 位置保留：某帧没检测到的怪，用上一帧位置补100ms，避免移动时丢框 ===
                _now_ms = time.time() * 1000
                if not hasattr(self, '_last_known_monsters'):
                    self._last_known_monsters = {}
                # 更新当前检测到的怪的位置
                for (x1, y1, x2, y2, score) in yolo_monsters:
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    self._last_known_monsters[(cx, cy)] = _now_ms
                # 清理超过100ms的旧位置
                self._last_known_monsters = {k: v for k, v in self._last_known_monsters.items()
                                              if _now_ms - v < 100}
                # 合并：当前检测 + 保留的旧位置（去重）
                _retained = []
                for (lcx, lcy), _t in self._last_known_monsters.items():
                    _dup = False
                    for (x1, y1, x2, y2, _) in yolo_monsters:
                        cx = (x1 + x2) // 2
                        cy = (y1 + y2) // 2
                        if abs(cx - lcx) < 40 and abs(cy - lcy) < 50:
                            _dup = True
                            break
                    if not _dup:
                        _retained.append((lcx - 25, lcy - 35, lcx + 25, lcy + 35, 0.35))
                yolo_monsters = yolo_monsters + _retained
                if new_pos:
                    self._player_screen_pos = new_pos
                    self._last_player_screen_time = now
                elif now - getattr(self, '_last_player_screen_time', 0) > 800:
                    # 检测丢失超过800ms才清空，短暂丢失保留最后位置避免发呆
                    self._player_screen_pos = None
                _has_pos = self._player_screen_pos is not None
                if _has_pos != getattr(self, '_last_player_pos_ok', None):
                    self._last_player_pos_ok = _has_pos
                    if _has_pos:
                        _debug_log("[人物定位] 成功，黄点位置: %s" % (self._player_screen_pos,))
                    else:
                        _debug_log("[人物定位] 丢失，黄点隐藏")

                # 血条搜索区域：YOLO检测到的怪头顶 + 上一次攻击目标头顶（近战挡身体时YOLO检测不到但血条还在）
                _search = []
                if yolo_monsters:
                    _search = [(max(0, x1-15), max(0, y1-40), x2+15, y1+5)
                               for (x1, y1, x2, y2, _) in yolo_monsters]
                if self._combat_last_target_pos:
                    tx, ty = self._combat_last_target_pos
                    _search.append((max(0, tx-50), max(0, ty-55),
                                    min(frame.shape[1], tx+50), ty+10))

                # 血条检测：只在人物周围双向、技能范围内搜索（不全窗口，减少误检）
                fight_cfg = self._get_fight_config()
                atk_dist = fight_cfg.get("atk1_distance", 150)
                if self._player_screen_pos:
                    ppx, ppy = self._player_screen_pos
                    h, w = frame.shape[:2]
                    # 血条搜索：人物X±攻击距离，Y-200到+50（以人物脚为基点，只检测近身怪）
                    hp_search = [(max(0, ppx - atk_dist), max(0, ppy - 200),
                                  min(w, ppx + atk_dist), min(h, ppy + 50))]
                    self._monster_hp_bars = self._detect_monster_hp_bars(frame, hp_search)
                else:
                    # 无人物位置时回退全窗口搜索
                    self._monster_hp_bars = self._detect_monster_hp_bars(frame, None)

                # 血条位置转怪物坐标（血条正下方就是怪的位置）
                hp_monsters = []
                for (bx, by, bw, bh) in self._monster_hp_bars:
                    hp_monsters.append((bx, by+bh+5, bx+bw, by+bh+55, 0.4))

                # YOLO结果按置信度过滤（降到0.4，和主检测一致，避免0.4-0.5的怪被误杀）
                conf_thresh = getattr(self, '_yolo_conf_thresh', 0.4)
                filtered_yolo = [m for m in yolo_monsters if m[4] >= conf_thresh]
                # 调试：输出所有检测的置信度，方便调阈值
                if yolo_monsters:
                    scores = [round(m[4], 2) for m in yolo_monsters]
                    print("[YOLO] 检测%d只 置信度:%s 过滤后剩%d只(阈值%.1f)" % (
                        len(yolo_monsters), scores, len(filtered_yolo), conf_thresh))

                # 合并去重：YOLO结果 + 血条单独检测的怪
                merged = list(filtered_yolo)
                for hm in hp_monsters:
                    hx, hy, hw, hh = hm  # 血条: 左上角x,y 宽w 高h
                    hcx = hx + hw // 2
                    hcy = hy + hh // 2
                    dup = False
                    for ym in filtered_yolo:
                        ycx = (ym[0] + ym[2]) // 2
                        ycy = (ym[1] + ym[3]) // 2
                        if abs(hcx - ycx) < 35 and abs(hcy - ycy) < 50:
                            dup = True
                            break
                    if not dup:
                        # 血条在怪头顶，估算怪脚在血条下方约60px，转成统一格式(x1,y1,x2,y2,score)
                        merged.append((hx, hy, hx + hw, hy + hh + 60, 0.9))

                # 用最新帧检测结果，怪移动后框立即跟随新位置，不残留旧位置
                self._monsters = merged
                self._monsters_display = merged

                # === 检测耗时统计（每2秒输出平均）===
                if not hasattr(self, '_detect_time_acc'):
                    self._detect_time_acc = {'shot': 0, 'yolo': 0, 'player': 0, 'count': 0, 'last_log': 0}
                _total_frame = (time.time() - _t0) * 1000
                self._detect_time_acc['shot'] += _t_shot
                self._detect_time_acc['yolo'] += _t_yolo
                self._detect_time_acc['player'] += _t_player
                self._detect_time_acc['count'] += 1
                if time.time() - self._detect_time_acc['last_log'] > 2.0:
                    _c = max(1, self._detect_time_acc['count'])
                    _debug_log("[检测耗时] 平均: 截图%.1fms YOLO%.1fms 人物%.1fms 总%.1fms | %d帧 保留旧位置%d只" % (
                        self._detect_time_acc['shot']/_c, self._detect_time_acc['yolo']/_c,
                        self._detect_time_acc['player']/_c, _total_frame, _c, len(_retained)))
                    self._detect_time_acc = {'shot': 0, 'yolo': 0, 'player': 0, 'count': 0, 'last_log': time.time()}

                _mc = len(self._monsters)
                if _mc > 0 and _mc != getattr(self, "_last_logged_mc", -1):
                    self._rlog("发现怪物%d只(YOLO%d+血条%d,阈值%.1f)" % (
                        _mc, len(filtered_yolo), len(hp_monsters), conf_thresh), (0, 100, 200))
                    self._last_logged_mc = _mc
                elif _mc == 0:
                    self._last_logged_mc = 0

        # === 攻击无血条验证：打了没血条→按位置拉黑3秒+换怪（防背景误检空打）===
        _pending = getattr(self, '_combat_pending_blood_check', None)
        if _pending:
            check_target, check_time = _pending
            if now - check_time > 200:  # 200ms给血条出现时间
                ctx, cty = check_target
                has_blood = False
                for (bx, by, bw, bh) in self._monster_hp_bars:
                    bcx = bx + bw // 2
                    if abs(bcx - ctx) < 80 and by < cty + 20:
                        has_blood = True
                        break
                if not has_blood:
                    # 按位置拉黑3秒（不是按怪拉黑），3秒内不去这个位置打怪
                    if not hasattr(self, '_combat_missed_positions'):
                        self._combat_missed_positions = {}
                    self._combat_missed_positions[(ctx, cty)] = now + 3000
                    self._combat_locked_target = None
                    _debug_log("[打怪] 攻击后无血条，位置(%d,%d)拉黑3秒，换最近怪" % (ctx, cty))
                else:
                    _debug_log("[打怪] 攻击后检测到血条，继续打锁定怪")
                self._combat_pending_blood_check = None
        # 清理过期位置拉黑
        if hasattr(self, '_combat_missed_positions'):
            self._combat_missed_positions = {k: v for k, v in self._combat_missed_positions.items() if v > now}

        # === 高效模式：去掉反应延迟/转身延迟/忙碌延迟，检测到就打 ===
        # if now < self._combat_react_until: return
        # if now < self._combat_turn_until: return
        # if now < self._combat_busy_until: return

        # === 路线系统移动中（爬梯子/换平台）：战斗不控制移动，避免冲突 ===
        if getattr(self, '_route_moving', False):
            self._release_combat_move()
            # 诊断日志：看为什么遇怪即停没触发
            if time.time() - getattr(self, '_last_route_moving_log', 0) > 1.5:
                self._last_route_moving_log = time.time()
                if self._monsters and self._player_screen_pos:
                    _, ppy = self._player_screen_pos
                    fight_cfg = self._get_fight_config()
                    atk_dist = fight_cfg.get("atk1_distance", 150)
                    y_thresh = 100 if atk_dist >= 250 else 50
                    y_gaps = [abs(m[3] - ppy) for m in self._monsters[:5]]
                    in_range = sum(1 for m in self._monsters if abs(m[3] - ppy) <= y_thresh)
                    _debug_log("[战斗诊断] route_moving=True 暂停战斗 | YOLO检测%d只 | Y差≤%d有%d只 | 最近5只Y差:%s" % (
                        len(self._monsters), y_thresh, in_range, y_gaps))
                else:
                    _debug_log("[战斗诊断] route_moving=True 暂停战斗 | YOLO检测%d只 | 人物位置:%s" % (
                        len(self._monsters), self._player_screen_pos))
            return

        # === 不过滤怪物：保留所有检测到的怪，目标选择时同平台优先 ===
        current_platform = self._get_current_platform()
        has_target = bool(self._monsters and self._player_screen_pos)

        # === 完全无目标（一只怪都没检测到）：松开移动，由路线系统接管 ===
        if not has_target:
            self._combat_had_target = False
            self._combat_target_idx = 0
            self._combat_last_target_pos = None
            self._combat_locked_target = None
            self._release_combat_move()
            return

        # === 有目标（当前平台上有怪）===
        px, py = self._player_screen_pos

        # 首次发现目标：反应延迟
        if not self._combat_had_target:
            self._combat_had_target = True
            self._combat_react_until = now + random.randint(50, 180)
            return

        # === 目标选择：有血条的真怪优先，没血条的YOLO结果可能是误检，排后面 ===
        def _has_blood(cx, cy):
            for (bx, by, bw, bh) in self._monster_hp_bars:
                bcx = bx + bw // 2
                # 精确匹配：x中心差<50，血条在怪物头顶附近(cy-90到cy-10)，不在脚下方
                if abs(bcx - cx) < 50 and (cy - 90) < by < (cy - 10):
                    return True
            return False

        same_platform_monsters = []
        all_monsters = []
        real_with_blood = []  # 有血条的真怪
        yolo_only = []  # 只有YOLO没血条（可能误检）
        for (x1, y1, x2, y2, score) in self._monsters:
            cx = (x1 + x2) // 2
            cy = y2  # 脚的位置
            dist = abs(cx - px) + abs(cy - py)  # 曼哈顿距离
            entry = (dist, cx, cy)
            all_monsters.append(entry)
            if self._is_monster_in_platform_range(cx, cy):
                same_platform_monsters.append(entry)
            if _has_blood(cx, cy):
                real_with_blood.append(entry)
            else:
                yolo_only.append(entry)
        same_platform_monsters.sort()
        all_monsters.sort()
        real_with_blood.sort()
        yolo_only.sort()

        # === 怪物移动预测：更新历史位置（下一帧预测用）===
        _now_ms_hist = int(time.time() * 1000)
        _new_history = {}
        for (x1, y1, x2, y2, score) in self._monsters:
            _cxh = (x1 + x2) // 2
            _cyh = y2
            _key = "%d_%d" % (_cxh // 20, _cyh // 20)
            _new_history[_key] = (_cxh, _cyh, _now_ms_hist)
        self._monster_history = _new_history

        # 目标选择诊断日志（每1秒）
        if time.time() - getattr(self, '_last_target_select_log', 0) > 1.0:
            self._last_target_select_log = time.time()
            near_same_count = sum(1 for m in same_platform_monsters if m[0] <= 1000)
            _debug_log("[目标选择] YOLO=%d只 | 同平台=%d只 | 同平台1000px内=%d只 | 最近同平台=%dpx | 最近全部=%dpx | current_pf=%s" % (
                len(self._monsters), len(same_platform_monsters), near_same_count,
                same_platform_monsters[0][0] if same_platform_monsters else -1,
                all_monsters[0][0] if all_monsters else -1,
                current_platform is not None))

        # === 目标选择：有血条的真怪优先，没血条的YOLO可能是误检，作为后备 ===
        if real_with_blood:
            _debug_log("[目标选择] 有血条真怪%d只，优先选择(YOLO-only %d只忽略)" % (len(real_with_blood), len(yolo_only)))
            candidate_pool = real_with_blood
        else:
            _debug_log("[目标选择] 无血条真怪，用YOLO结果(%d只，可能含误检)" % len(yolo_only))
            candidate_pool = all_monsters  # 没血条时用全部YOLO结果

        # === 怪物密度优先：周围怪物多的优先（每多1只相当于距离近25px）===
        if len(candidate_pool) >= 2:
            _density_weighted = []
            for (_d, _cx, _cy) in candidate_pool:
                _near_count = sum(1 for (_, _ox, _oy) in candidate_pool
                                   if abs(_ox - _cx) + abs(_oy - _cy) <= 150 and (_ox, _oy) != (_cx, _cy))
                _weighted = _d - _near_count * 25
                _density_weighted.append((_weighted, _d, _cx, _cy, _near_count))
            _density_weighted.sort()
            candidate_pool = [(_d, _cx, _cy) for (_, _d, _cx, _cy, _) in _density_weighted]
            if _density_weighted[0][4] >= 2:
                _debug_log("[密度优先] 选中区域密度%d只，原距离%dpx→加权%dpx" % (
                    _density_weighted[0][4], _density_weighted[0][1], _density_weighted[0][0]))

        # 从候选池中筛选同平台怪
        same_platform_candidates = []
        for (dist, cx, cy) in candidate_pool:
            if self._is_monster_in_platform_range(cx, cy):
                same_platform_candidates.append((dist, cx, cy))
        same_platform_candidates.sort()

        # 同平台1000px以内的怪
        near_same = [m for m in same_platform_candidates if m[0] <= 1000]
        num_platforms = len(self.platforms)  # 录制的平台数，0=纯战斗模式

        if near_same:
            # 本平台1000px内有怪，优先本平台
            monster_dists = near_same
        elif same_platform_candidates and num_platforms <= 1:
            # 本平台有>1000px的怪，且单平台/纯战斗模式（没别的平台可去），可以打
            _debug_log("[目标选择] 单平台模式，本平台怪>1000px(最近%dpx)，仍打" % same_platform_candidates[0][0])
            monster_dists = same_platform_candidates
        else:
            # 本平台1000px内没怪，且多平台模式：去其他录制平台找怪
            # 候选怪必须站在某个录制平台上（用_find_platform_at_point判断）
            recorded_monsters = []
            for m in candidate_pool:
                mcx, mcy = m[1], m[2]
                if self._find_platform_at_point(mcx, mcy) is not None:
                    recorded_monsters.append(m)
            if recorded_monsters:
                _debug_log("[目标选择] 本平台1000px内无怪，选录制平台上最近的怪(%dpx，共%d只)" % (
                    recorded_monsters[0][0], len(recorded_monsters)))
                monster_dists = recorded_monsters
            elif same_platform_candidates:
                # 其他录制平台也没怪，退回打本平台>1000px的怪
                _debug_log("[目标选择] 其他录制平台无怪，退回本平台>1000px的怪(%dpx)" % same_platform_candidates[0][0])
                monster_dists = same_platform_candidates
            else:
                _debug_log("[目标选择] 全图无怪，松开移动")
                self._release_combat_move()
                self._combat_locked_target = None
                self._combat_had_target = False
                return

        # 过滤攻击无血条被拉黑的位置（3秒内不去这个位置打怪）
        _missed = getattr(self, '_combat_missed_positions', {})
        if _missed and monster_dists:
            monster_dists = [(d, cx, cy) for (d, cx, cy) in monster_dists
                             if not any(abs(cx - mx) < 50 and abs(cy - my) < 60 for (mx, my) in _missed)]

        # 距离诊断（每2秒输出前3只怪）
        if monster_dists and time.time() - getattr(self, '_last_cost_log', 0) > 2.0:
            self._last_cost_log = time.time()
            top3 = monster_dists[:3]
            info = ", ".join(["%dpx" % m[0] for m in top3])
            _debug_log("[打怪] 可打怪%d只 最近3只: %s" % (len(monster_dists), info))

        # 没有可打的怪→松开移动，路线系统去别的层
        if not monster_dists:
            # === 智能选平台：多平台模式下，找到最近的有怪的录制平台，告诉路线系统直接去 ===
            if len(self.platforms) > 1 and self._monsters and self._player_screen_pos:
                _px, _py = self._player_screen_pos
                _best_pf_idx = -1
                _best_pf_dist = 99999
                for _pi, _pf in enumerate(self.platforms):
                    _pts = self._platform_points(_pf)
                    _pf_mid = _pts[len(_pts) // 2]
                    # 统计这个平台上的怪物数量
                    _pf_count = 0
                    for (_x1, _y1, _x2, _y2, _s) in self._monsters:
                        _mcx = (_x1 + _x2) // 2
                        _mcy = _y2
                        if self._find_platform_at_point(_mcx, _mcy) is _pf:
                            _pf_count += 1
                    if _pf_count > 0:
                        _dpf = abs(_px - _pf_mid[0]) + abs(_py - _pf_mid[1])
                        if _dpf < _best_pf_dist:
                            _best_pf_dist = _dpf
                            _best_pf_idx = _pi
                if _best_pf_idx >= 0:
                    self._route_target_platform_override = _best_pf_idx
                    _debug_log("[智能选平台] 本平台无怪，设置路线目标为平台%d（距离%dpx，有怪）" % (
                        _best_pf_idx, _best_pf_dist))
            self._release_combat_move()
            self._combat_locked_target = None
            self._combat_had_target = False
            return

        # === 目标锁定规则 ===
        # 移动中（怪离得远>攻击距离）：可以换更近的怪，效率优先
        # 攻击中（怪在攻击距离内）：血条还在就不换，血条消失=怪死了才换
        target = monster_dists[0]  # 默认选最近的
        atk_dist = fight_cfg.get("atk1_distance", 150)

        if self._combat_locked_target:
            lcx, lcy = self._combat_locked_target
            # 在当前怪列表中找锁定的怪（阈值加大到120px，容忍怪移动和检测抖动）
            locked_found = None
            for d, cx, cy in monster_dists:
                if abs(cx - lcx) <= 120 and abs(cy - lcy) <= 120:
                    locked_found = (d, cx, cy)
                    break

            if locked_found:
                ld, lcx2, lcy2 = locked_found

                if ld <= atk_dist:
                    # === 攻击中：怪在攻击距离内，血条还在就不换 ===
                    has_blood = False
                    for (bx, by, bw, bh) in self._monster_hp_bars:
                        bcx = bx + bw // 2
                        if abs(bcx - lcx2) < 50 and (lcy2 - 90) < by < (lcy2 - 10):
                            has_blood = True
                            break
                    if has_blood:
                        # 血条还在，怪没死，坚持打锁定的怪，不切换
                        target = locked_found
                        self._combat_no_blood_streak = 0  # 重置连续无血条计数
                    else:
                        # 攻击中没血条→直接换最近的怪（位置拉黑由攻击后验证处理）
                        self._combat_locked_target = None
                        self._combat_no_blood_streak = 0
                        _debug_log("[打怪] 攻击中无血条，直接换最近怪")
                else:
                    # === 移动中：怪离得远，可换更近的怪，效率优先 ===
                    if ld - target[0] > 50:
                        # 有明显更近的怪（差距>50px），切换
                        self._combat_locked_target = None
                        _debug_log("[打怪] 移动中切换更近目标: %dpx→%dpx" % (ld, target[0]))
                    else:
                        # 没有明显更近的，继续追锁定的怪
                        target = locked_found

                # 重置丢失计时
                self._combat_lock_lost_start = 0
            else:
                # 锁定的怪不在列表中（丢失），计时
                if not getattr(self, '_combat_lock_lost_start', 0):
                    self._combat_lock_lost_start = now
                elif now - self._combat_lock_lost_start > 2000:
                    # 丢失超过2秒，换目标
                    self._combat_locked_target = None
                    self._combat_lock_lost_start = 0
                    _debug_log("[打怪] 锁定怪丢失超2秒，换目标")

        t_dist, t_cx, t_cy = target

        # === 怪物移动预测：用历史位置计算速度，预测当前位置（修正检测延迟）===
        _now_ms_pred = int(time.time() * 1000)
        _best_hist = None
        _best_hist_d = 999
        for _hk, (_hx, _hy, _hts) in self._monster_history.items():
            _hd = abs(t_cx - _hx) + abs(t_cy - _hy)
            if _hd < _best_hist_d and _hd < 80:
                _best_hist_d = _hd
                _best_hist = (_hx, _hy, _hts)
        if _best_hist:
            _hx, _hy, _hts = _best_hist
            _dt = max(1, _now_ms_pred - _hts)
            _vx = (t_cx - _hx) / _dt
            _vy = (t_cy - _hy) / _dt
            _pred_cx = int(t_cx + _vx * 50)  # 预测50ms后位置
            _pred_cy = int(t_cy + _vy * 50)
            _pred_dist = abs(_pred_cx - px) + abs(_pred_cy - py)
            if abs(_pred_dist - t_dist) > 5:
                _debug_log("[怪物预测] 检测(%d,%d)→预测(%d,%d) 速度(%.2f,%.2f)px/ms 距离%d→%d" % (
                    t_cx, t_cy, _pred_cx, _pred_cy, _vx, _vy, t_dist, _pred_dist))
            t_cx, t_cy, t_dist = _pred_cx, _pred_cy, _pred_dist

        self._combat_locked_target = (t_cx, t_cy)
        # 记录目标位置，用于下一轮血条搜索
        self._combat_last_target_pos = (t_cx, t_cy)

        # === 打怪思维日志（每2秒输出一次，看决策链）===
        if time.time() - getattr(self, '_last_combat_thinking_log', 0) > 2.0:
            self._last_combat_thinking_log = time.time()
            _total = len(self._monsters)
            _layer_count = len(monster_dists)
            _atk = fight_cfg.get("atk1_distance", 150)
            _action = "攻击" if t_dist <= _atk else "移动靠近"
            _debug_log("[打怪思维] 检测%d只(当前层%d只) 选中(%d,%d)距离%dpx %s" % (
                _total, _layer_count, t_cx, t_cy, t_dist, _action))

        # 面向判断：怪在右按右键，怪在左按左键
        needed_facing = 1 if t_cx > px else -1
        if self._combat_facing != needed_facing:
            _vk = 0x27 if needed_facing > 0 else 0x25
            if random.random() < 0.03:
                _vk = 0x25 if _vk == 0x27 else 0x27
            _scan = user32.MapVirtualKeyW(_vk, 0)
            user32.keybd_event(_vk, _scan, 0x0001, 0)
            self._combat_timed_keys.append((_vk, now + random.randint(50, 120)))
            self._combat_facing = needed_facing
            self._combat_turn_until = now + random.randint(50, 150)
            _debug_log("[打怪步骤1-转身] 目标(%d,%d)在%s，当前面向%d，转身按%s" % (
                t_cx, t_cy, "右" if needed_facing > 0 else "左", self._combat_facing, "右" if needed_facing > 0 else "左"))
            return

        # === 远处怪朝怪移动靠近（用主攻距离，不用AOE距离，否则停在AOE范围内但主攻够不着）===
        atk_dist = fight_cfg.get("atk1_distance", 150)
        aoe_dist = fight_cfg.get("aoe_distance", 200)
        if t_dist > atk_dist:
            move_dir = "right" if t_cx > px else "left"
            _debug_log("[打怪步骤2-移动] 目标距离%dpx>攻击距离%dpx，向%s移动" % (t_dist, atk_dist, move_dir))
            # 平台边界：到边缘停止
            current_pf = self._get_current_platform()
            if current_pf and self._player_map_pos:
                ppx, _ = self._player_map_pos
                pf_xmin, pf_xmax = self._platform_x_range(current_pf)
                _debug_log("[打怪步骤2-平台边界] 玩家小地图X=%d，平台范围[%d,%d]，移动方向=%s" % (
                    ppx, pf_xmin, pf_xmax, move_dir))
                if move_dir == "right" and ppx >= pf_xmax - 2:
                    _debug_log("[打怪步骤2-停] 已到平台右边缘(%d>=%d)，停止移动" % (ppx, pf_xmax - 2))
                    self._release_combat_move()
                    return
                if move_dir == "left" and ppx <= pf_xmin + 2:
                    _debug_log("[打怪步骤2-停] 已到平台左边缘(%d<=%d)，停止移动" % (ppx, pf_xmin + 2))
                    self._release_combat_move()
                    return
            elif not current_pf:
                _debug_log("[打怪步骤2-警告] current_pf=None，无平台边界限制")

            # === 卡住检测与恢复：移动中位置长时间不变则执行恢复 ===
            if self._combat_last_player_pos:
                _lpx, _lpy = self._combat_last_player_pos
                _moved = abs(px - _lpx) + abs(py - _lpy)
                if _moved < 15:
                    if not self._combat_stuck_start:
                        self._combat_stuck_start = now
                    elif now - self._combat_stuck_start > 1200:
                        # 卡住超过1.2秒，执行恢复
                        _step = self._combat_stuck_recovery_step
                        _back_dir = "left" if move_dir == "right" else "right"
                        _jump_key = fight_cfg.get("jump_key", "")
                        if _step == 0:
                            # 步骤1：后退短按
                            self._press_game_key(_back_dir, duration=100)
                            self._combat_stuck_recovery_step = 1
                            _debug_log("[卡住恢复] 步骤1：后退(%s)100ms" % _back_dir)
                        elif _step == 1 and _jump_key:
                            # 步骤2：跳跃
                            self._press_game_key(_jump_key, duration=80)
                            self._combat_stuck_recovery_step = 2
                            _debug_log("[卡住恢复] 步骤2：跳跃")
                        else:
                            # 步骤3：反向走0.5秒
                            self._set_combat_move(_back_dir)
                            self._combat_stuck_recovery_step = 0
                            self._combat_stuck_start = 0
                            _debug_log("[卡住恢复] 步骤3：反向走(%s)" % _back_dir)
                        self._combat_last_player_pos = (px, py)
                        return
                else:
                    # 移动正常，重置卡住状态
                    self._combat_stuck_start = 0
                    self._combat_stuck_recovery_step = 0
            self._combat_last_player_pos = (px, py)

            self._set_combat_move(move_dir)
            self._combat_last_move = now
            _debug_log("[打怪步骤2-执行] _set_combat_move(%s)，当前_combat_move_dir=%s" % (move_dir, self._combat_move_dir))
            return
        # 进入攻击范围：松开移动专注攻击
        self._release_combat_move()
        _debug_log("[打怪步骤3-攻击] 目标距离%dpx<=攻击距离%dpx，进入攻击" % (t_dist, atk_dist))

        skill_rand = fight_cfg.get("skill_random", 50)
        skill_cast = False

        # --- 群攻：范围内>=3只怪，无固定冷却，只用随机延时 ---
        aoe_key = fight_cfg.get("aoe_key", "")
        if not skill_cast and aoe_key:
            aoe_dist = fight_cfg.get("aoe_distance", 200)
            in_range = sum(1 for d, _, _ in monster_dists if d <= aoe_dist)
            last = self._attack_last.get("aoe", 0)
            min_gap = max(20, random.randint(0, skill_rand))
            if in_range >= 3 and now - last > min_gap:
                self._press_game_key(aoe_key)
                self._attack_last["aoe"] = now
                skill_cast = True
                self._rlog("群攻 %s 范围内%d只" % (aoe_key, in_range), (0, 165, 255))
                print("[群攻] %s 释放 (范围内%d只怪)" % (aoe_key, in_range))

        # --- 多技能循环：atk1/atk2/atk3 按顺序循环释放（配置了key的才加入）---
        atk_skills = []
        for _si in range(1, 4):
            _key = fight_cfg.get("atk%d_key" % _si, "")
            if _key:
                _dist = fight_cfg.get("atk%d_distance" % _si, 150)
                atk_skills.append(("atk%d" % _si, _key, _dist))

        if not skill_cast and atk_skills:
            # 从当前循环索引开始，找第一个冷却好且在距离内的技能
            _released = False
            for _offset in range(len(atk_skills)):
                _idx = (self._skill_cycle_idx + _offset) % len(atk_skills)
                _skill_name, _skill_key, _skill_dist = atk_skills[_idx]
                _last = self._attack_last.get(_skill_name, 0)
                _min_gap = max(20, random.randint(0, skill_rand))
                if t_dist <= _skill_dist and now - _last > _min_gap:
                    # 攻击前诊断：检测血条情况
                    _blood_atk = False
                    for (bx, by, bw, bh) in self._monster_hp_bars:
                        bcx = bx + bw // 2
                        if abs(bcx - t_cx) < 50 and (t_cy - 90) < by < (t_cy - 10):
                            _blood_atk = True
                            break
                    _missed_count = len(getattr(self, '_combat_missed_positions', {}))
                    if _blood_atk:
                        _debug_log("[攻击诊断] %s：检测到血条，目标(%d,%d)距离%dpx，拉黑位置%d个" % (
                            _skill_name, t_cx, t_cy, t_dist, _missed_count))
                    else:
                        _debug_log("[攻击诊断] %s：检测到怪物但无血条，目标(%d,%d)距离%dpx，血条数%d，拉黑位置%d个" % (
                            _skill_name, t_cx, t_cy, t_dist, len(self._monster_hp_bars), _missed_count))
                    if random.random() < 0.05 and aoe_key:
                        self._press_game_key(aoe_key)
                        self._rlog("%s(按错) %s" % (_skill_name, aoe_key), (0, 200, 0))
                    else:
                        self._press_game_key(_skill_key)
                        self._rlog("%s %s 距离%d" % (_skill_name, _skill_key, t_dist), (0, 200, 0))
                    self._attack_last[_skill_name] = now
                    self._skill_cycle_idx = (_idx + 1) % len(atk_skills)
                    skill_cast = True
                    _released = True
                    print("[%s] %s 释放 (目标%dpx，循环索引%d→%d)" % (
                        _skill_name, _skill_key, t_dist, _idx, self._skill_cycle_idx))
                    break
            if not _released and len(atk_skills) > 1:
                _debug_log("[多技能] 所有技能冷却中或不在距离内，等待")

        # 攻击后设置血条验证：200ms后检查目标头顶是否有血条，没血条→按位置拉黑3秒+换怪
        if skill_cast:
            self._combat_pending_blood_check = ((t_cx, t_cy), now)

        # === BUFF 1-6（30%概率晚补2-5秒）===
        if not skill_cast:
            buff_rand = fight_cfg.get("buff_random", 50)
            for i, b in enumerate(fight_cfg.get("buffs", []), 1):
                key = b.get("key", "")
                cd = b.get("cd", 0)
                delay = b.get("delay", 0)
                if not key or cd <= 0:
                    continue
                last = self._buff_last.get("buff%d" % i, 0)
                extra = random.randint(2000, 5000) if random.random() < 0.3 else 0
                actual_cd = cd + random.randint(-buff_rand, buff_rand) + extra
                if now - last > actual_cd:
                    self._press_game_key(key)
                    self._buff_last["buff%d" % i] = now
                    if delay > 0:
                        self._combat_busy_until = now + delay
                    self._rlog("BUFF%d %s" % (i, key), (200, 0, 200))
                    print("[BUFF%d] %s 释放" % (i, key))
                    break

        # === 药品1-5（周期性，加随机）===
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
                print("[药品%d] %s 释放" % (i, key))


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
            self._player_map_pos = player_pos  # 保存小地图坐标供战斗逻辑判断平台

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

            # === scale自动校准：玩家移动时用屏幕Y差/小地图Y差计算实际比例 ===
            if self._player_screen_pos and self._player_map_pos:
                if self._last_calib_screen and self._last_calib_map:
                    dsy = abs(self._player_screen_pos[1] - self._last_calib_screen[1])
                    dmy = abs(self._player_map_pos[1] - self._last_calib_map[1])
                    if dsy > 15 and dmy > 0:
                        sy = dmy / dsy
                        self._scale_samples_y.append(sy)
                        if len(self._scale_samples_y) > 30:
                            self._scale_samples_y.pop(0)
                        if len(self._scale_samples_y) >= 5:
                            med = sorted(self._scale_samples_y)[len(self._scale_samples_y) // 2]
                            if abs(med - self._map_screen_scale) > 0.005:
                                self._map_screen_scale = med
                                print("[scale校准] Y比例=%.4f (采样%d次)" % (med, len(self._scale_samples_y)))
                self._last_calib_screen = self._player_screen_pos
                self._last_calib_map = self._player_map_pos

            # === 偏移视觉反馈（游戏画面中角色匹配点+偏移点）===
            try:
                self._show_offset_feedback()
            except Exception as e:
                print("[偏移反馈] 异常:", e)

            # === 透明蒙板（怪物/黄点/血条红点/蓝条蓝点统一显示）===
            # 检测结果由 _combat_tick 每350ms更新到 self._monsters / self._player_screen_pos
            if self._running:
                if not self._monster_overlay_running:
                    self._start_monster_overlay()
                try:
                    if self._monster_overlay_data is None:
                        self._monster_overlay_data = {}
                    # 同步怪物和人物位置到蒙板（显示用多帧缓冲，目标选择用最新帧）
                    self._monster_overlay_data["monsters"] = getattr(self, '_monsters_display', self._monsters)
                    self._monster_overlay_data["monster_hp_bars"] = self._monster_hp_bars
                    self._monster_overlay_data["locked_target"] = self._combat_locked_target
                    if self._player_screen_pos:
                        self._monster_overlay_data["char_pos"] = self._player_screen_pos
                except Exception as e:
                    print("[蒙板] 同步异常:", e)
            else:
                if self._monster_overlay_running:
                    self._stop_monster_overlay()

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

            key = cv2.waitKey(10) & 0xFF
            # 输入框自动失焦：3秒无变化（全局轮询输入不依赖UI前台，故不检查前台窗口）
            if self._focused_field is not None:
                now_ms = time.time() * 1000
                if now_ms - self._last_input_change > 3000:
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
                else:
                    self._poll_num_input()
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
        # Ensure overlay is destroyed before exit
        if self._monster_overlay_running:
            self._stop_monster_overlay()
        cv2.destroyAllWindows()
        print("Final:", len(self.platforms), "platforms,", len(self.ladders), "ladders")


if __name__ == "__main__":
    MinimapRouteRecorder().run()
