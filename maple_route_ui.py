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
    """写调试日志到文件，exe无控制台时用。超过20MB自动轮转备份。"""
    try:
        path = os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else ".", "debug.log")
        if os.path.exists(path) and os.path.getsize(path) > 20 * 1024 * 1024:
            bak = path + ".bak"
            if os.path.exists(bak):
                os.remove(bak)
            os.rename(path, bak)
        with open(path, "a", encoding="utf-8") as f:
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
# 【模块B】scale_x手动校准按钮（人物停在平台两端点按钮记录）
BTN_CALIB_LEFT  = (220, 104, 19, 24)  # 左端点按钮（记录人物在平台最左端的坐标）
BTN_CALIB_RIGHT = (245, 104, 19, 24)  # 右端点按钮（记录人物在平台最右端的坐标）

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
VK_F11 = 0x7A  # 坐标测量热键
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
        # 【模块B】平台选择：选择在哪个平台上打怪（编号从1开始，空列表=全部平台）
        self._selected_platforms = []  # 选中的平台编号列表，空=全部平台
        self._show_platform_selector = False  # 是否显示平台选择面板
        # 平台选择按钮区域（小地图左上方）
        self._btn_platform_selector = None  # "台子选择"按钮
        self._btn_platform_selector_close = None  # 选择面板关闭按钮
        # 【模块B】左右端点按钮按下特效状态
        self._calib_left_pressed = False
        self._calib_right_pressed = False
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
        # 【模块B】scale_x手动校准按钮素材（人物停在平台两端点按钮记录）
        self._ui_calib_left = load_png(resource_path(os.path.join("data", "ui_calib_left.png")))
        self._ui_calib_right = load_png(resource_path(os.path.join("data", "ui_calib_right.png")))
        # MP标签模板（遮挡检测：标签在=没挡住=吃药，标签消失=被挡住=不吃药）
        _mp_label_path = resource_path(os.path.join("data", "templates", "mp_label.png"))
        if os.path.exists(_mp_label_path):
            self._mp_label_template = cv2.imread(_mp_label_path)
            _debug_log("[MP遮挡] 标签模板已加载 %dx%d" % self._mp_label_template.shape[:2])
        else:
            self._mp_label_template = None
            _debug_log("[MP遮挡] 标签模板不存在, 跳过遮挡检测")
        # 血条空白灰色模板（竖框内模板匹配，匹配到=空白=加药）
        _gray_bar_path = resource_path(os.path.join("data", "templates", "gray_bar.png"))
        if os.path.exists(_gray_bar_path):
            self._gray_bar_template = cv2.imread(_gray_bar_path)
            _debug_log("[加药] 灰色空白模板已加载 %dx%d" % self._gray_bar_template.shape[:2])
        else:
            self._gray_bar_template = None
            _debug_log("[加药] 灰色空白模板不存在, 回退颜色检测")
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
        self._combat_locked_target = None  # 锁定的目标 (cx, cy)，打死才换，不中途切换
        # === 模块A：打怪优化新增状态变量 ===
        self._combat_active = False         # 【战斗活跃标志】技能范围内有怪时=True，此时暂停巡路移动，专心打怪
        self._combat_target_lock_x = None   # 【锁定目标首次X】记录刚锁定时目标的X坐标，用于1秒无变化检测
        self._combat_target_lock_time = 0    # 【锁定目标时间戳】记录锁定目标的时间(毫秒)，用于计算1秒是否到了
        self._combat_target_alive = False    # 【目标是否存活】有血条或伤害数字时=True，说明怪还没打死
        self._combat_range_clear = False     # 【范围清怪模式】技能范围内有怪时=True，范围内怪全部打完才恢复巡路
        self._player_map_pos = None        # 玩家小地图坐标，用于判断当前平台
        self._monster_hp_bars = []         # 检测到的怪物血条 [(x,y,w,h),...]
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
        self._random_route_id = None
        self._random_platform_idx = 0
        self._random_state = "idle"  # idle/moving/attacking/returning/climbing
        self._random_attack_start = 0
        self._random_move_keys = set()  # 当前按住的移动键
        # 梯子攀爬状态机
        self._climb_state = "none"  # none/to_ladder/climbing/jump_down/teleport
        self._climb_ladder_x = 0
        self._climb_target_y = 0
        self._climb_direction = 0  # 1=up, -1=down
        self._climb_start_y = 0    # 跳跃/瞬移前的y坐标，用于检测是否生效
        self._climb_action_time = 0  # 跳跃/瞬移动作开始时间

        # 自动刷新状态：默认开启，手动框选后关闭，点刷新重新开启
        self._auto_refresh = True

        self.last_player_pos = None
        self.frame_count = 0

        # 热键状态（保留以备鼠标回调复用_handle_hotkey）
        self._key_state = {vk: False for vk in [VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10, VK_F12]}
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

        print("Map area:", self.map_area_rect["width"], "x", self.map_area_rect["height"])
        print("方案 %d 已加载: %d 平台, %d 梯子 (模式: %s)" % (
            self.current_route, len(self.platforms), len(self.ladders), self.route_mode))
        print("UI: 左上角=刷新/手动/方案X  第一排=平台/梯子/保存▼/方案▼")
        print("    第二排=清除(绿=平台)/清除(蓝=梯子)/模式▼/清除(橙=方案)\n")

        # 自动备份线程：每30分钟备份一次源码，保留最近20个
        self._auto_backup_interval = 1800  # 30分钟
        self._last_backup_time = 0
        self._auto_backup_thread = threading.Thread(target=self._auto_backup_loop, daemon=True)
        self._auto_backup_thread.start()
        print("[自动备份] 已启动，每30分钟Git自动提交一次")

    def _auto_backup_loop(self):
        """自动备份循环：每30分钟检查一次，源码有修改则git commit并push到远程
        用途：防止本地文件丢失，自动同步到GitHub远程仓库
        注意：GitHub单文件硬限制100MB，exe约66MB可正常推送"""
        import subprocess
        git_exe = r"C:\Program Files\Git\bin\git.exe"
        work_dir = os.path.dirname(os.path.abspath(__file__))
        # Windows专用：CREATE_NO_WINDOW标志，防止subprocess弹出控制台黑窗
        CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
        while True:
            try:
                time.sleep(60)  # 每分钟检查一次
                now = time.time()
                if now - self._last_backup_time < self._auto_backup_interval:
                    continue
                if not os.path.exists(git_exe):
                    continue
                # 步骤1：检查是否有修改
                result = subprocess.run([git_exe, "status", "--porcelain"], cwd=work_dir,
                                        capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                if not result.stdout.strip():
                    self._last_backup_time = now
                    continue
                # 步骤2：git add 所有修改
                subprocess.run([git_exe, "add", "-A"], cwd=work_dir,
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
                # 步骤3：git commit
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                commit_msg = "自动备份 %s" % timestamp
                subprocess.run([git_exe, "commit", "-m", commit_msg], cwd=work_dir,
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
                self._last_backup_time = now
                print("[自动备份] Git已提交: %s" % commit_msg)
                # 步骤4：git push 到远程GitHub（大陆网络可能失败，失败不影响本地commit）
                push_result = subprocess.run([git_exe, "push", "origin", "main"], cwd=work_dir,
                                             capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
                                             timeout=60)
                if push_result.returncode == 0:
                    print("[自动备份] 已推送到远程GitHub")
                else:
                    # push失败（网络问题），本地commit已保存，下次重试
                    print("[自动备份] push失败(网络问题)，本地已保存，下次重试: %s" % push_result.stderr[:200])
            except subprocess.TimeoutExpired:
                print("[自动备份] push超时(网络慢)，本地已保存，下次重试")
            except Exception as e:
                print("[自动备份] 异常:", e)
                time.sleep(60)

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

    def _find_nearest_ladder(self, px, py, target_y):
        """找最近的可用梯子（靠近当前高度即可，不要求覆盖全程）"""
        best = None
        best_dist = 9999
        for ld in self.ladders:
            lx = ld["x"]
            y_top = ld["y_top"]
            y_bottom = ld["y_bottom"]
            # 梯子范围包含当前高度（允许±5误差）
            if y_top - 5 <= py <= y_bottom + 5:
                dist = abs(lx - px)
                if dist < best_dist:
                    best_dist = dist
                    best = ld
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
        self._move_stuck_inited = False  # 爬梯结束重置卡住检测

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

        # === 攀爬状态机 ===
        if self._climb_state == "to_ladder":
            # 移动到梯子x位置
            ldx = self._climb_ladder_x - px
            fight_cfg = self._get_fight_config()
            jump_key = fight_cfg.get("jump_key", "")
            if abs(ldx) > 10:
                # 还远，水平移动靠近
                if ldx > 0:
                    if VK_LEFT in self._random_move_keys:
                        self._key_up(VK_LEFT)
                    if VK_RIGHT not in self._random_move_keys:
                        self._key_down(VK_RIGHT)
                else:
                    if VK_RIGHT in self._random_move_keys:
                        self._key_up(VK_RIGHT)
                    if VK_LEFT not in self._random_move_keys:
                        self._key_down(VK_LEFT)
                return False
            elif abs(ldx) >= 4 and jump_key:
                # 跑着接近梯子，x还有点距离 → 提前跳+方向键抓梯子
                if ldx > 0:
                    if VK_LEFT in self._random_move_keys:
                        self._key_up(VK_LEFT)
                    if VK_RIGHT not in self._random_move_keys:
                        self._key_down(VK_RIGHT)
                else:
                    if VK_RIGHT in self._random_move_keys:
                        self._key_up(VK_RIGHT)
                    if VK_LEFT not in self._random_move_keys:
                        self._key_down(VK_LEFT)
                self._press_game_key(jump_key, duration=80)
                _debug_log("[爬梯] 跑跳抓梯子 ldx=%.0f" % ldx)
                return False
            else:
                # 到达梯子x（正下方），松开方向键，开始攀爬
                if VK_LEFT in self._random_move_keys:
                    self._key_up(VK_LEFT)
                if VK_RIGHT in self._random_move_keys:
                    self._key_up(VK_RIGHT)
                self._climb_state = "climbing"
                self._climb_start_y = py  # 记录起始Y，用于攀爬成功确认
                self._climb_action_time = time.time() * 1000  # 记录攀爬开始时间
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
                _debug_log("[爬梯] 开始攀爬 方向=%s 起始Y=%.0f 目标Y=%.0f" % (
                    "上" if self._climb_direction > 0 else "下", py, self._climb_target_y))
                return False

        if self._climb_state == "climbing":
            now_ms = time.time() * 1000
            elapsed = now_ms - self._climb_action_time
            # === Y值确认：攀爬800ms后检测Y是否变化，没变化=被怪挡住/没抓稳=失败 ===
            if elapsed > 800 and abs(py - self._climb_start_y) < 6:
                _debug_log("[爬梯] 失败：Y未变化(%.0f->%.0f) %.0fms，重置重试（战斗系统先清怪）" % (
                    self._climb_start_y, py, elapsed))
                self._reset_climb()
                return False
            # 持续按住上/下，检测是否到达目标高度
            cdy = self._climb_target_y - py
            if abs(cdy) <= 4:
                # 到达目标高度，停止攀爬
                _debug_log("[爬梯] 成功：Y从%.0f到%.0f，用时%.0fms" % (
                    self._climb_start_y, py, elapsed))
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
                # 超时没上升 = 跳不上去，改用瞬移或梯子
                self._climb_state = "none"
                _debug_log("[上跳] 跳不上去（y未上升），改用瞬移/梯子")
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
                # 超时没下降 = 跳不下去，改用梯子
                self._key_up(VK_DOWN)
                self._climb_state = "none"
                _debug_log("[下跳] 跳不下去（y未下降），改用梯子")
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
        # 需要上下层时：先找梯子，找到直接去梯子位置（不要求dx<=25，避免梯子不在平台中心就找不到）
        if abs(dy) > 8:
            ladder = self._find_nearest_ladder(px, py, target_y)
            if ladder:
                self._climb_state = "to_ladder"
                self._climb_ladder_x = ladder["x"]
                self._climb_target_y = target_y
                self._climb_direction = 1 if target_y < py else -1
                _debug_log("[路线] 需上下层dy=%.0f，直接去梯子x=%.0f" % (dy, ladder["x"]))
                return False

        # 垂直差异大且水平已对齐 → 跳跃/瞬移（没梯子时的兜底）
        if abs(dy) > 8 and abs(dx) <= 25:
            now_ms = time.time() * 1000
            fight_cfg = self._get_fight_config()
            tp_key = fight_cfg.get("teleport_key", "")
            tp_dist = fight_cfg.get("teleport_distance", 0)
            jump_key = fight_cfg.get("jump_key", "")
            vertical_gap = abs(dy)
            going_up = target_y < py  # 小地图y越小越靠上
            aligned = abs(dx) <= 6  # 水平对齐才跳，避免乱跳

            # --- 去上层：先跳 → 瞬移 → 梯子 ---
            if going_up:
                # 1. 小高度差且水平对齐才跳
                if vertical_gap <= 15 and jump_key and aligned:
                    self._climb_state = "jump_up"
                    self._climb_target_y = target_y
                    self._climb_start_y = py
                    self._climb_action_time = now_ms
                    self._press_game_key(jump_key, duration=80)
                    _debug_log("[上跳] 目标y=%.0f 当前y=%.0f，间距=%.0f，尝试跳跃" % (
                        target_y, py, vertical_gap))
                    return False
                # 2. 瞬移（没配置直接忽略）
                if tp_key and tp_dist > 0 and tp_dist >= vertical_gap:
                    self._climb_state = "teleport"
                    self._climb_target_y = target_y
                    self._climb_direction = 1
                    self._do_teleport(py)
                    _debug_log("[瞬移] 目标y=%.0f 当前y=%.0f，间距=%.0f，瞬移距离=%d，向上" % (
                        target_y, py, vertical_gap, tp_dist))
                    return False
                # 3. 都不行 → 爬梯子
                ladder = self._find_nearest_ladder(px, py, target_y)
                if ladder:
                    self._climb_state = "to_ladder"
                    self._climb_ladder_x = ladder["x"]
                    self._climb_target_y = target_y
                    self._climb_direction = 1
                    _debug_log("[爬梯] 目标y=%.0f 当前y=%.0f，找梯子x=%.0f，向上" % (
                        target_y, py, ladder["x"]))
                    return False

            # --- 去下层：先判定下跳 → 瞬移 → 梯子 ---
            else:
                # 1. 判定高度差能否下跳且水平对齐
                if jump_key and vertical_gap <= 30 and aligned:
                    self._climb_state = "jump_down"
                    self._climb_target_y = target_y
                    self._climb_start_y = py
                    self._climb_action_time = now_ms
                    self._key_down(VK_DOWN)
                    self._press_game_key(jump_key, duration=80)
                    _debug_log("[下跳] 间距%.0f<=30，下+跳跃" % vertical_gap)
                    return False
                # 2. 瞬移（没配置直接忽略）
                if tp_key and tp_dist > 0 and tp_dist >= vertical_gap:
                    self._climb_state = "teleport"
                    self._climb_target_y = target_y
                    self._climb_direction = -1
                    self._do_teleport(py)
                    _debug_log("[瞬移] 目标y=%.0f 当前y=%.0f，间距=%.0f，瞬移距离=%d，向下" % (
                        target_y, py, vertical_gap, tp_dist))
                    return False
                # 3. 都不行 → 爬梯子
                ladder = self._find_nearest_ladder(px, py, target_y)
                if ladder:
                    self._climb_state = "to_ladder"
                    self._climb_ladder_x = ladder["x"]
                    self._climb_target_y = target_y
                    self._climb_direction = -1
                    _debug_log("[爬梯] 目标y=%.0f 当前y=%.0f，找梯子x=%.0f，向下" % (
                        target_y, py, ladder["x"]))
                    return False

            # 没有梯子，小高度差尝试普通跳跃
            if abs(dy) <= 20 and jump_key:
                self._press_game_key(jump_key, duration=80)
                return False

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

            # === 卡住检测：水平移动时每1.5秒确认X是否变化，没变化=被障碍物卡住→跳跃脱困 ===
            now_ms = time.time() * 1000
            if not getattr(self, '_move_stuck_inited', False) or self._move_stuck_dir != (1 if dx > 0 else -1):
                self._move_stuck_last_x = px
                self._move_stuck_last_time = now_ms
                self._move_stuck_dir = 1 if dx > 0 else -1
                self._move_stuck_inited = True
            elif now_ms - self._move_stuck_last_time > 1500:
                if abs(px - self._move_stuck_last_x) < 5:
                    fight_cfg = self._get_fight_config()
                    jump_key = fight_cfg.get("jump_key", "")
                    if jump_key and now_ms - getattr(self, '_move_stuck_jump_time', 0) > 1200:
                        self._press_game_key(jump_key, duration=80)
                        self._move_stuck_jump_time = now_ms
                        _debug_log("[移动] 卡住：方向=%s X=%.0f 1.5秒未变化，跳跃脱困" % (
                            "右" if dx > 0 else "左", px))
                self._move_stuck_last_x = px
                self._move_stuck_last_time = now_ms

            # 微高差平台对接：Y差3-20像素，边走边跳跨上相邻平台
            if 3 <= abs(dy) <= 20:
                fight_cfg = self._get_fight_config()
                jump_key = fight_cfg.get("jump_key", "")
                if jump_key:
                    last_jump = getattr(self, '_last_platform_gap_jump', 0)
                    if now_ms - last_jump > 350:
                        self._press_game_key(jump_key, duration=60)
                        self._last_platform_gap_jump = now_ms
                        _debug_log("[平台对接] 微高差%.0fpx，边走边跳" % dy)
        else:
            if VK_LEFT in self._random_move_keys:
                self._key_up(VK_LEFT)
            if VK_RIGHT in self._random_move_keys:
                self._key_up(VK_RIGHT)
            self._move_stuck_inited = False  # 到达目标X，重置卡住检测

        # 到达判断
        if abs(dx) <= 4 and abs(dy) <= 6:
            self._reset_climb()
            return True
        return False

    def _random_step(self, player_pos):
        """随机模式每帧状态机"""
        if not self._random_running:
            return
        # 【新系统】使用重新定义的打怪/移动/梯子系统时，禁用旧巡路状态机
        if getattr(self, '_use_new_system', True):
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
            # 【模块A-需求2】战斗活跃时暂停巡路移动，由_combat_tick接管打怪
            # 原理：技能范围内有怪时_combat_active=True，此时人物应专心打怪不往别的平台跑
            if getattr(self, '_combat_active', False):
                return
            if self._random_platform_idx >= len(self.platforms):
                # 全部平台打完，回起点
                self._random_state = "returning"
                return
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
                self._random_attack_start = time.time()
                self._key_down(VK_ATTACK)
                print("[随机] 到达平台%d，开始攻击" % self._random_platform_idx)

        elif self._random_state == "attacking":
            # 第三层：当前平台清完后才切换下一个平台（至少攻击1秒避免YOLO未检测到就走）
            attack_elapsed = time.time() - self._random_attack_start
            if attack_elapsed > 1.0:
                monsters_on_platform = self._filter_monsters_on_platform(
                    self._monsters, self._player_screen_pos) if self._player_screen_pos else self._monsters
                if not monsters_on_platform:
                    self._key_up(VK_ATTACK)
                    self._random_platform_idx += 1
                    self._random_state = "moving"
                    print("[随机] 平台%d已清完，前往下一个" % (self._random_platform_idx - 1))

        elif self._random_state == "returning":
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

    def _platform_x_range(self, pf):
        """获取平台的x范围（兼容新旧格式）。"""
        pts = self._platform_points(pf)
        xs = [p[0] for p in pts]
        return min(xs), max(xs)

    def _get_current_manual_platform(self):
        """【模块B】获取人物当前所在的手动录制平台（用于移动边界限制）
        用途：判断人物在哪个手动录制平台上，限制人物在平台X范围内打怪
        原理：
          1. 遍历所有手动录制平台
          2. 计算人物小地图坐标到平台折线的距离
          3. 距离最小且≤15px的平台 = 人物当前所在平台
        返回：平台对象dict；找不到返回None"""
        if not self.platforms or not self._player_map_pos:
            return None
        mx, my = self._player_map_pos
        best_pf = None
        best_dist = 999.0
        for pf in self.platforms:
            pts = self._platform_points(pf)
            d = self._point_to_polyline_dist(mx, my, pts)
            if d < best_dist:
                best_dist = d
                best_pf = pf
        if best_pf and best_dist <= 15:
            return best_pf
        return None

    def _check_platform_boundary(self):
        """【模块B】检测人物是否超出手动录制平台的X边界，超出则返回往回走的方向
        用途：人物到了平台边缘自动回去，只打平台X范围内的怪
        原理：
          1. 获取人物当前所在的手动录制平台
          2. 获取平台X范围（x_min, x_max）
          3. 人物X < x_min → 需要往右走回去
          4. 人物X > x_max → 需要往左走回去
          5. 在范围内 → 返回None（不需要调整）
        返回：'right'=需要往右走, 'left'=需要往左走, None=在范围内"""
        pf = self._get_current_manual_platform()
        if pf is None or not self._player_map_pos:
            return None
        x_min, x_max = self._platform_x_range(pf)
        px = self._player_map_pos[0]
        if px < x_min + 2:  # 超出左边界2px
            return 'right'
        elif px > x_max - 2:  # 超出右边界2px
            return 'left'
        return None

    def _is_monster_in_manual_platform(self, screen_x, screen_y):
        """【模块B】判断怪是否在人物当前手动录制平台的X范围内
        用途：只打平台X范围内的怪，超出范围的怪不打
        原理：
          1. 获取人物当前所在的手动录制平台
          2. 估算怪的小地图X坐标
          3. 怪X在平台X范围内 → True
          4. 超出范围或没有手动录制平台 → False（没有手动录制时全地图打怪）
        参数：screen_x, screen_y = 怪屏幕坐标
        返回：True=在范围内可以打, False=超出范围不打（或没有手动录制平台）"""
        pf = self._get_current_manual_platform()
        if pf is None:
            return True  # 没有手动录制平台时，全地图打怪（用自动录制平台）
        map_pos = self._screen_to_map(screen_x, screen_y)
        if map_pos is None:
            return False
        x_min, x_max = self._platform_x_range(pf)
        return x_min <= map_pos[0] <= x_max

    # ========================================================================
    # 【模块B】平台判定优化：配合小地图绿线和人物光点，判定怪在哪个平台
    # ========================================================================

    def _screen_to_map(self, screen_x, screen_y):
        """【模块B】屏幕坐标转小地图坐标（以人物光点为参考点，比固定scale更准）
        用途：怪在屏幕中的位置(YOLO检测) → 估算怪在小地图上的坐标
        原理：怪小地图X = 人物小地图X + (怪屏幕X - 人物屏幕X) * scale
              怪小地图Y = 人物小地图Y + (怪屏幕Y - 人物屏幕Y) * scale
        参数：screen_x, screen_y = 怪在游戏画面中的屏幕坐标
        返回：(map_x, map_y) 估算的小地图坐标；人物位置未知时返回None"""
        # 人物小地图坐标（黄色光点中心）
        if not self._player_map_pos or not self._player_screen_pos:
            return None
        pmap_x, pmap_y = self._player_map_pos       # 人物在小地图上的坐标
        pscr_x, pscr_y = self._player_screen_pos     # 人物在游戏画面中的屏幕坐标
        # scale比例：小地图px / 屏幕px，默认0.10（1382px窗口≈150px小地图），后续可自动校准
        scale = getattr(self, '_map_screen_scale', 0.10)
        # 以人物为参考点，计算怪相对于人物的偏移，再转成小地图偏移
        map_x = pmap_x + (screen_x - pscr_x) * scale
        map_y = pmap_y + (screen_y - pscr_y) * scale
        return (map_x, map_y)

    def _update_scale_calibration(self):
        """【模块B】自动校准scale比例（人物移动时记录屏幕和小地图变化，计算实际比例）
        用途：替代固定scale=0.10，越跑越准
        原理：
          1. 记录上一帧人物的屏幕坐标和小地图坐标
          2. 当前帧计算变化量 Δ屏幕 和 Δ小地图
          3. 实际scale = Δ小地图 / Δ屏幕（变化量足够大时才更新，避免噪声）
          4. 用滑动平均更新校准值（新值占20%，旧值占80%）
        调用时机：每帧人物位置更新后调用"""
        if not self._player_map_pos or not self._player_screen_pos:
            return
        cur_map = self._player_map_pos
        cur_scr = self._player_screen_pos
        last_map = getattr(self, '_last_calib_map', None)
        last_scr = getattr(self, '_last_calib_scr', None)
        if last_map and last_scr:
            dx_scr = abs(cur_scr[0] - last_scr[0])
            dy_scr = abs(cur_scr[1] - last_scr[1])
            dx_map = abs(cur_map[0] - last_map[0])
            dy_map = abs(cur_map[1] - last_map[1])
            # X轴变化量>20屏幕px时才校准（避免静止时噪声）
            if dx_scr > 20 and dx_map > 1:
                scale_x = dx_map / dx_scr
                old_scale = getattr(self, '_calibrated_scale_x', 0.10)
                # 滑动平均：新值占20%，旧值占80%，防止突变
                self._calibrated_scale_x = old_scale * 0.8 + scale_x * 0.2
                self._map_screen_scale = self._calibrated_scale_x  # 更新主scale
            # Y轴变化量>15屏幕px时才校准
            if dy_scr > 15 and dy_map > 1:
                scale_y = dy_map / dy_scr
                old_scale_y = getattr(self, '_calibrated_scale_y', 0.10)
                self._calibrated_scale_y = old_scale_y * 0.8 + scale_y * 0.2
        # 保存当前帧坐标供下次校准
        self._last_calib_map = cur_map
        self._last_calib_scr = cur_scr

    def _auto_calibrate_edges(self):
        """【模块B】自动记录人物最左/最右端点（每3秒检测一次，人物站在边缘3秒自动记录）
        用途：通过记录人物在最左和最右时的屏幕X和小地图X，计算实际scale_x
        原理：
          1. 每3秒检测一次人物位置（避免每帧比较，减少性能消耗）
          2. 比最左点更左 → 更新最左点（记录屏幕X+小地图X+小地图Y）
          3. 比最右点更右 → 更新最右点
          4. 左右都记录到后 → scale_x = (右小地图X - 左小地图X) / (右屏幕X - 左屏幕X)
        使用方法：人物站在最左边3秒自动记录，再站最右边3秒自动记录
        手动校准优先：_manual_calib_done=True时，跳过自动记录（避免覆盖手动值）
        副作用（永久记住）：
          1. 自动记录的左右端点可能不是真正的平台两端（人物没走到边缘）
          2. 如果人物在小地图范围内移动，记录的范围偏小，scale_x不准
          3. 解决：不准时用手动记录（人物停在平台两端点按钮）"""
        # 手动校准已执行时，跳过自动记录（避免覆盖手动值）
        if getattr(self, '_manual_calib_done', False):
            return
        # 每3秒检测一次（避免每帧比较，减少性能消耗，人物站在边缘3秒自动记录）
        now_ms = time.time() * 1000
        last_time = getattr(self, '_last_auto_calib_time', 0)
        if now_ms - last_time < 3000:
            return
        self._last_auto_calib_time = now_ms
        if not self._player_map_pos or not self._player_screen_pos:
            # 调试：每5秒打印一次检测状态，帮助排查
            _now = time.time()
            if not hasattr(self, '_last_calib_debug') or _now - self._last_calib_debug > 5:
                self._last_calib_debug = _now
                _debug_log("[自动校准] 检测状态: 小地图位置=%s 屏幕位置=%s (屏幕位置需设置人物特征模板)" % (
                    'OK' if self._player_map_pos else 'None',
                    'OK' if self._player_screen_pos else 'None(需设置人物特征)'))
            return
        cur_scr_x = self._player_screen_pos[0]
        cur_map_x = self._player_map_pos[0]
        # 初始化左右端点记录
        left_pt = getattr(self, '_calib_left_pt', None)
        right_pt = getattr(self, '_calib_right_pt', None)
        # 自动更新最左点（当前屏幕X比记录的更左）
        if left_pt is None or cur_scr_x < left_pt[0]:
            # 记录完整坐标：(屏幕X, 小地图X, 小地图Y)
            self._calib_left_pt = (cur_scr_x, cur_map_x, self._player_map_pos[1])
            left_pt = self._calib_left_pt
        # 自动更新最右点（当前屏幕X比记录的更右）
        if right_pt is None or cur_scr_x > right_pt[0]:
            # 记录完整坐标：(屏幕X, 小地图X, 小地图Y)
            self._calib_right_pt = (cur_scr_x, cur_map_x, self._player_map_pos[1])
            right_pt = self._calib_right_pt
        # 左右都记录到后，计算scale_x
        if left_pt and right_pt and right_pt[0] > left_pt[0] + 50:
            # 屏幕X差>50px才计算（避免范围太小不准）
            dx_scr = right_pt[0] - left_pt[0]
            dx_map = right_pt[1] - left_pt[1]
            if dx_map > 1:
                scale_x = dx_map / dx_scr
                # 自动校准的scale_x权重50%（因为可能不是真正的平台两端）
                old_scale = getattr(self, '_calibrated_scale_x', 0.10)
                self._calibrated_scale_x = old_scale * 0.5 + scale_x * 0.5
                self._map_screen_scale = self._calibrated_scale_x

    def _manual_calibrate_left(self):
        """【模块B】手动记录左端点（人物停在平台最左端后点按钮）
        用途：自动记录不准时，用手动方式精确记录平台两端
        原理：记录当前人物的屏幕X和完整小地图坐标(X,Y)作为左端点
        副作用：手动记录后关闭自动记录（避免自动记录覆盖手动值）"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._add_log("手动校准失败：未检测到人物位置")
            return
        # 记录完整坐标：(屏幕X, 小地图X, 小地图Y)
        self._calib_left_pt = (self._player_screen_pos[0], self._player_map_pos[0], self._player_map_pos[1])
        self._manual_calib_done = True  # 标记手动校准已执行，关闭自动记录
        self._add_log("已记录左端点：屏幕X=%d 小地图(%d,%d)" % (
            self._player_screen_pos[0], self._player_map_pos[0], self._player_map_pos[1]))
        self._recalc_scale_from_edges()

    def _manual_calibrate_right(self):
        """【模块B】手动记录右端点（人物停在平台最右端后点按钮）
        用途：自动记录不准时，用手动方式精确记录平台两端
        原理：记录当前人物的屏幕X和完整小地图坐标(X,Y)作为右端点
        副作用：手动记录后关闭自动记录（避免自动记录覆盖手动值）"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._add_log("手动校准失败：未检测到人物位置")
            return
        # 记录完整坐标：(屏幕X, 小地图X, 小地图Y)
        self._calib_right_pt = (self._player_screen_pos[0], self._player_map_pos[0], self._player_map_pos[1])
        self._manual_calib_done = True  # 标记手动校准已执行，关闭自动记录
        self._add_log("已记录右端点：屏幕X=%d 小地图(%d,%d)" % (
            self._player_screen_pos[0], self._player_map_pos[0], self._player_map_pos[1]))
        self._recalc_scale_from_edges()

    def _recalc_scale_from_edges(self):
        """【模块B】根据左右端点重新计算scale_x（手动记录后调用）
        原理：scale_x = (右小地图X - 左小地图X) / (右屏幕X - 左屏幕X)
        记录格式：(屏幕X, 小地图X, 小地图Y)
        手动记录的scale_x权重100%（精确记录，直接覆盖）"""
        left_pt = getattr(self, '_calib_left_pt', None)
        right_pt = getattr(self, '_calib_right_pt', None)
        if left_pt and right_pt and right_pt[0] > left_pt[0]:
            dx_scr = right_pt[0] - left_pt[0]   # 屏幕X差
            dx_map = right_pt[1] - left_pt[1]   # 小地图X差
            if dx_map > 0 and dx_scr > 0:
                scale_x = dx_map / dx_scr
                self._calibrated_scale_x = scale_x  # 手动记录直接覆盖（100%权重）
                self._map_screen_scale = scale_x
                self._add_log("scale_x校准完成：%.4f (左%dx→%d, 右%dx→%d)" % (
                    scale_x, left_pt[0], left_pt[1], right_pt[0], right_pt[1]))

    def _get_monster_map_pos_verified(self, screen_x, screen_y):
        """【模块B】怪物小地图坐标验证（方法B平台绿线50% + 方法A线性转换50% 加权平均，带偏差检测）
        用途：让怪物光点在小地图上显示得更准，同时避免平台判定错误导致完全错位
        原理：
          方法A（线性转换）：用校准后的scale线性转换屏幕坐标→小地图坐标
          方法B（平台绿线校准）：判断怪在哪个平台，用绿线在对应X处的Y值
          偏差检测：方法B的Y和方法A的Y偏差>30px时，判定平台判定错误，只用方法A
          折中方案：最终Y = 方法B_Y × 0.5 + 方法A_Y × 0.5
          - 方法B权重50%：平台绿线有参考价值，但可能判定错误
          - 方法A权重50%：线性转换更稳定，防止平台判定错误导致怪物点完全跳平台
          - X坐标用方法A（线性转换更准，绿线X可能有采样误差）
        副作用（永久记住）：
          1. 平台判定错不会完全错位（有方法A兜底+偏差检测），但也不会完全落在绿线上
          2. 依赖平台录制质量，没录平台的地方只用方法A
          3. 怪物在空中（跳跃/被击退）时，方法B会拉回绿线，有50%方法A缓冲
          4. 偏差>30px时只用方法A，避免平台判定错误把怪拉到错误楼层
        参数：screen_x, screen_y = 怪物屏幕坐标
        返回：(map_x, map_y) 验证后的小地图坐标"""
        # 方法A：线性转换（用校准后的scale）
        pos_a = self._screen_to_map(screen_x, screen_y)
        if pos_a is None:
            return None
        # 【模块B】Y轴偏差检测：怪物X离人物近（<200px）时，应该是同平台的怪
        # 如果方法A的Y和人物Y差太大（>50px），说明Y转换不准（比如第二层怪跑到第三层）
        # 用人物Y作为怪物Y（同平台怪Y差不多），避免Y偏差太大
        if self._player_map_pos and self._player_screen_pos:
            dx_screen = abs(screen_x - self._player_screen_pos[0])
            if dx_screen < 200:  # 怪物离人物近，应该是同平台
                dy_map = abs(pos_a[1] - self._player_map_pos[1])
                if dy_map > 50:  # Y偏差太大，说明转换不准
                    # 用人物Y作为怪物Y（同平台怪Y差不多）
                    pos_a = (pos_a[0], self._player_map_pos[1])
        # 方法B：平台绿线校准
        monster_pf = self._get_monster_platform(screen_x, screen_y)
        pos_b_y = None
        if monster_pf:
            pts = self._platform_points(monster_pf)
            if pts:
                # 先检查怪的X是否在平台绿线的X范围内
                xs = [p[0] for p in pts]
                pf_xmin, pf_xmax = min(xs), max(xs)
                if pf_xmin <= pos_a[0] <= pf_xmax:
                    # 怪的X在平台范围内 → 用绿线Y（方法B有效）
                    best_y = pos_a[1]
                    best_dx = 999
                    for (px, py) in pts:
                        dx = abs(px - pos_a[0])
                        if dx < best_dx:
                            best_dx = dx
                            best_y = py
                    pos_b_y = best_y
                # 怪的X在平台范围外（对应不到Y）→ 不用方法B，直接用方法A
        # 如果方法B失败（怪X不在平台范围/找不到平台），直接用方法A
        if pos_b_y is None:
            return pos_a
        # 偏差检测：方法B的Y和方法A的Y偏差>30px时，判定平台判定错误，只用方法A
        # 避免平台判定错误把怪从第二层拉到第三层
        y_diff = abs(pos_b_y - pos_a[1])
        if y_diff > 30:
            return pos_a
        # 折中方案：加权平均
        # Y = 方法B(平台绿线) × 50% + 方法A(线性转换) × 50%
        # X用方法A（线性转换更准）
        final_x = pos_a[0]
        final_y = pos_b_y * 0.5 + pos_a[1] * 0.5
        return (final_x, final_y)

    def _get_monster_platform(self, screen_x, screen_y):
        """【模块B】判定怪在哪个平台上（用手动录制平台判定）
        用途：找怪时判断怪和人物是否同平台，还是在上面/下面的平台
        原理：
          1. 怪屏幕坐标(YOLO) → 估算小地图坐标(_screen_to_map)
          2. 用手动录制的平台判定：距离≤15px = 在该平台上
        参数：screen_x, screen_y = 怪在游戏画面中的屏幕坐标
        返回：平台对象dict；找不到返回None"""
        map_pos = self._screen_to_map(screen_x, screen_y)
        if map_pos is None:
            return None
        mx, my = map_pos
        # 用手动录制的平台判定
        if not self.platforms:
            return None
        best_pf = None
        best_dist = 999.0
        for pf in self.platforms:
            pts = self._platform_points(pf)
            d = self._point_to_polyline_dist(mx, my, pts)
            if d < best_dist:
                best_dist = d
                best_pf = pf
        if best_pf and best_dist <= 15:
            return best_pf
        return None

    def _get_slope_direction(self, screen_x, screen_y):
        """【模块B】判定怪相对于人物是上坡、下坡还是平地
        用途：斜坡打怪时，上坡需要跳着打，下坡直接走过去打
        原理：
          1. 先判定怪在哪个平台(_get_monster_platform)
          2. 怪和人物同平台：比较怪估算的小地图Y 和 人物在绿线上的Y
             - 怪Y < 人物Y → 上坡（怪在更高处）
             - 怪Y > 人物Y → 下坡（怪在更低处）
             - 相差≤5 → 平地
          3. 怪在不同平台：直接判定上平台/下平台
        参数：screen_x, screen_y = 怪在游戏画面中的屏幕坐标
        返回：'up'=上坡/上平台, 'down'=下坡/下平台, 'flat'=平地, None=未知"""
        if not self._player_map_pos:
            return None
        # 步骤1：怪在哪个平台
        monster_pf = self._get_monster_platform(screen_x, screen_y)
        # 步骤2：人物在哪个平台
        player_pf = self._get_current_platform()
        if monster_pf is None or player_pf is None:
            return None
        # 步骤3：同平台 → 比较Y判断上坡/下坡
        if monster_pf.get('id') == player_pf.get('id'):
            map_pos = self._screen_to_map(screen_x, screen_y)
            if map_pos is None:
                return None
            monster_y = map_pos[1]  # 怪估算的小地图Y
            player_y = self._player_map_pos[1]  # 人物小地图Y
            y_diff = monster_y - player_y
            if y_diff < -5:
                return 'up'    # 怪Y更小 = 怪在更高处 = 上坡
            elif y_diff > 5:
                return 'down'  # 怪Y更大 = 怪在更低处 = 下坡
            else:
                return 'flat'  # Y相近 = 平地
        else:
            # 步骤4：不同平台 → 比较平台Y判断上/下平台
            m_pts = self._platform_points(monster_pf)
            p_pts = self._platform_points(player_pf)
            m_avg_y = sum(p[1] for p in m_pts) / len(m_pts)
            p_avg_y = sum(p[1] for p in p_pts) / len(p_pts)
            if m_avg_y < p_avg_y:
                return 'up'    # 怪所在平台Y更小 = 上面的平台
            else:
                return 'down'  # 怪所在平台Y更大 = 下面的平台

    def _find_nearest_monster_all(self):
        """【模块B】综合找最近的怪（包括同平台和上下平台，考虑平台切换惩罚）
        用途：同平台没怪时，找最近的怪，包括需要爬梯子/跳下去的怪
        原理：
          1. 对每个检测到的怪，计算"综合距离" = 屏幕距离 + 平台切换惩罚
          2. 同平台怪：惩罚=0（直接走过去打）
          3. 上平台怪：惩罚≈爬梯子时间(约2秒=2000距离单位)
          4. 下平台怪：惩罚≈跳下去时间(约0.5秒=500距离单位)
          5. 返回综合距离最小的怪
        返回：(screen_x, screen_y, 综合距离, 平台对象, 方向)；没怪返回None"""
        if not self._monsters or not self._player_screen_pos:
            return None
        px, py = self._player_screen_pos
        best = None
        best_cost = 99999
        for (x1, y1, x2, y2, score) in self._monsters:
            cx = (x1 + x2) // 2  # 怪中心X
            cy = y2               # 怪脚底Y
            screen_dist = int(np.sqrt((cx - px) ** 2 + (cy - py) ** 2))
            # 判定怪在哪个平台
            monster_pf = self._get_monster_platform(cx, cy)
            player_pf = self._get_current_platform()
            # 平台切换惩罚
            if monster_pf and player_pf and monster_pf.get('id') != player_pf.get('id'):
                direction = self._get_slope_direction(cx, cy)
                if direction == 'up':
                    penalty = 2000  # 上平台需要爬梯子，惩罚大
                elif direction == 'down':
                    penalty = 500   # 下平台跳下去，惩罚小
                else:
                    penalty = 1000
            else:
                direction = self._get_slope_direction(cx, cy) or 'flat'
                penalty = 0       # 同平台无惩罚
            cost = screen_dist + penalty
            if cost < best_cost:
                best_cost = cost
                best = (cx, cy, cost, monster_pf, direction)
        return best

    # ========================================================================
    # 【模块C】绿线波动检测：只要绿线不是直的，有波动的地方就要跳着跑
    # ========================================================================

    def _check_platform_slope_ahead(self, move_dir, look_ahead=50):
        """【模块C】检测人物前方绿线是否有波动（断层/上坡/下坡），有则需要跳着跑
        用途：只要绿线不是直的，有波动的地方（断层、上坡、下坡），就要跳着跑过去
        原理：
          1. 获取人物当前平台的绿线折点
          2. 找到人物在绿线上的最近点
          3. 根据移动方向，取前方look_ahead距离(小地图px)内的绿线点
          4. 计算这些点的Y变化范围(maxY - minY)
          5. Y变化>阈值(10px) = 有波动，需要跳
        参数：move_dir='left'/'right'，look_ahead=前方检测距离(小地图px，默认50)
        返回：True=前方有波动需要跳，False=平直绿线不需要跳"""
        current_pf = self._get_current_platform()
        if not current_pf or not self._player_map_pos:
            return False
        pts = self._platform_points(current_pf)
        if len(pts) < 2:
            return False
        ppx, ppy = self._player_map_pos
        # 步骤1：找到人物在绿线上的最近点索引
        best_idx = 0
        best_dist = 999.0
        for i, (x, y) in enumerate(pts):
            d = ((x - ppx) ** 2 + (y - ppy) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best_idx = i
        # 步骤2：根据移动方向，取前方look_ahead距离内的绿线点
        ahead_pts = []
        if move_dir == 'right':
            # 向右移动：取索引增大方向的点（X增大）
            for i in range(best_idx, len(pts)):
                if pts[i][0] - ppx <= look_ahead:
                    ahead_pts.append(pts[i])
                else:
                    break
        else:  # left
            # 向左移动：取索引减小方向的点（X减小）
            for i in range(best_idx, -1, -1):
                if ppx - pts[i][0] <= look_ahead:
                    ahead_pts.append(pts[i])
                else:
                    break
        if len(ahead_pts) < 2:
            return False
        # 步骤3：计算前方绿线点的Y变化范围
        ys = [p[1] for p in ahead_pts]
        y_range = max(ys) - min(ys)
        # Y变化>10px判定为有波动（断层/上坡/下坡），需要跳着跑
        return y_range > 10

    def extract_platform(self, points):
        """录制的路径点抽稀后保存为折线（曲线），一条录制=一个平台。"""
        if len(points) < 2:
            return []
        # 按间距抽稀（至少5小地图px一个点），保留曲线形状
        simplified = [points[0]]
        for p in points[1:]:
            last = simplified[-1]
            dist = ((p[0] - last[0]) ** 2 + (p[1] - last[1]) ** 2) ** 0.5
            if dist >= 5:
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
        for vk in [VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10, VK_F12]:
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
                _debug_log("[启动] F10 已触发, _running=True, hwnd=%s" % self.hwnd)
        elif vk == VK_F12:
            if self._running or self._random_running:
                self._running = False
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
        # 【模块B】右键点击坐标测量（放在最开头，避免被其他处理拦截）
        # 用途：测量血条/蓝条/按钮等元素的精确坐标
        if event == cv2.EVENT_RBUTTONDOWN:
            import ctypes
            pt = (ctypes.c_long * 2)()  # [x, y] 用数组模拟POINT结构
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            screen_x, screen_y = pt[0], pt[1]
            if self.hwnd:
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
                win_x = screen_x - rect.left
                win_y = screen_y - rect.top
                # 获取该位置的像素颜色
                color_str = ""
                try:
                    frame = self._capture_window()
                    if frame is not None and 0 <= win_y < frame.shape[0] and 0 <= win_x < frame.shape[1]:
                        b, g, r = frame[win_y, win_x]
                        color_str = " RGB(%d,%d,%d)" % (r, g, b)
                except Exception:
                    pass
                msg = "坐标: (%d,%d)%s" % (win_x, win_y, color_str)
                print("[坐标测量] 窗口内=(%d,%d)%s" % (win_x, win_y, color_str))
                self._add_log(msg)
            else:
                self._add_log("请先绑定游戏窗口")
            return
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
            # 注意：这里不能return，否则其他区域的右键点击（如坐标测量）会被拦截

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
        # 【模块B】scale_x手动校准按钮点击
        if _in(BTN_CALIB_LEFT, x, y):
            print("[鼠标] 记录左端点")
            self._calib_left_pressed = 3  # 按下特效：显示3帧阴影
            self._manual_calibrate_left()
            return
        if _in(BTN_CALIB_RIGHT, x, y):
            print("[鼠标] 记录右端点")
            self._calib_right_pressed = 3  # 按下特效：显示3帧阴影
            self._manual_calibrate_right()
            return

        # 5. 小地图区域内点击
        if UI_MAP_X <= x < UI_MAP_X + UI_MAP_W and UI_MAP_Y <= y < UI_MAP_Y + UI_MAP_H:
            # 【模块B】台子选择按钮点击（小地图左上方）
            if self._btn_platform_selector and _in(self._btn_platform_selector, x, y):
                self._show_platform_selector = not self._show_platform_selector
                print("[台子选择] 打开面板" if self._show_platform_selector else "[台子选择] 关闭面板")
                return
            # 【模块B】台子选择面板中的点击
            if self._show_platform_selector and self.platforms:
                panel_x, panel_y = UI_MAP_X + 10, UI_MAP_Y + 30
                panel_w = UI_MAP_W - 20
                # 关闭按钮X
                if self._btn_platform_selector_close and _in(self._btn_platform_selector_close, x, y):
                    self._show_platform_selector = False
                    print("[台子选择] 关闭面板")
                    return
                # 平台编号点击（切换选中状态：点一下选择，再点一下取消）
                per_row = 5
                for idx, pf in enumerate(self.platforms):
                    pf_num = idx + 1
                    row = idx // per_row
                    col = idx % per_row
                    item_x = panel_x + 10 + col * 36
                    item_y = panel_y + 28 + row * 22
                    # 点击区域：圆形周围（比圆形稍大一点方便点击）
                    if item_x <= x < item_x + 18 and item_y <= y < item_y + 18:
                        if pf_num in self._selected_platforms:
                            self._selected_platforms.remove(pf_num)
                            print("[台子选择] 取消选择平台%d" % pf_num)
                        else:
                            self._selected_platforms.append(pf_num)
                            print("[台子选择] 选择平台%d" % pf_num)
                        return
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
        # 【模块B】在小地图上画scale_x校准的左右端点（白色十字，放在绿线底下）
        # 左端点：白色十字；右端点：白色十字
        # 记录格式：(屏幕X, 小地图X, 小地图Y)，所以用[1]和[2]作为小地图坐标
        calib_left = getattr(self, '_calib_left_pt', None)
        calib_right = getattr(self, '_calib_right_pt', None)
        if calib_left and len(calib_left) >= 3:
            lx, ly = int(calib_left[1]), int(calib_left[2])  # 小地图X, 小地图Y
            if 0 <= lx < w and 0 <= ly < h:
                cv2.line(display, (lx-2, ly), (lx+2, ly), (255, 255, 255), 1)
                cv2.line(display, (lx, ly-2), (lx, ly+2), (255, 255, 255), 1)
        if calib_right and len(calib_right) >= 3:
            rx, ry = int(calib_right[1]), int(calib_right[2])  # 小地图X, 小地图Y
            if 0 <= rx < w and 0 <= ry < h:
                cv2.line(display, (rx-2, ry), (rx+2, ry), (255, 255, 255), 1)
                cv2.line(display, (rx, ry-2), (rx, ry+2), (255, 255, 255), 1)
        # 梯子（蓝线）
        for l in self.ladders:
            x = int(max(0, min(l["x"], w - 1)))
            y1 = int(max(0, min(l["y_top"], h - 1)))
            y2 = int(max(0, min(l["y_bottom"], h - 1)))
            cv2.line(display, (x, y1), (x, y2), COLOR_LADDER, 1)
        # 录制中的平台/梯子（黄色）
        if self.recording_platform and len(self.platform_points) > 1:
            cv2.polylines(display, [np.array(self.platform_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        if self.recording_ladder and len(self.ladder_points) > 1:
            cv2.polylines(display, [np.array(self.ladder_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        # 人物光点（黄点+红圈）
        if player_pos:
            cv2.circle(display, player_pos, 2, COLOR_PLAYER, -1)
            cv2.circle(display, player_pos, 4, (0, 0, 255), 1)
        # 手动录制平台：画整条深绿色线（最后画，始终在最上层）
        # 同时保留Y值+X范围+边界回退功能
        for p in self.platforms:
            pts = self._platform_points(p)
            if len(pts) >= 2:
                cv2.polylines(display, [np.array(pts, np.int32).reshape(-1, 1, 2)], False, COLOR_PLATFORM, 1)
        map_display = cv2.resize(display, (FIXED_W, MAP_H), interpolation=cv2.INTER_NEAREST)

        # 【模块B】在缩放后的map_display上画怪物紫色点（半径6，清晰可见）
        # 坐标从原始分辨率转换到缩放后：x * scale_x, y * scale_y
        # 紫色点圆心重叠在绿线上：相同X时用绿线Y值，绿线在display上已画好，紫色点在其上层
        scale_x = FIXED_W / w if w > 0 else 1.0
        scale_y = MAP_H / h if h > 0 else 1.0
        if self._monsters and self._player_map_pos and self._player_screen_pos:
            COLOR_MONSTER_MAP = (255, 0, 255)  # 紫色BGR
            for (x1, y1, x2, y2, score) in self._monsters:
                mcx = (x1 + x2) // 2
                mcy = y2
                mpos = self._get_monster_map_pos_verified(mcx, mcy)
                if mpos:
                    mx, my = int(mpos[0]), int(mpos[1])
                    # 找怪物X位置对应的绿线Y值，让紫色点圆心重叠在绿线上
                    for p in self.platforms:
                        pts = self._platform_points(p)
                        if len(pts) >= 2:
                            best_y = None
                            best_dx = 999
                            for (px, py) in pts:
                                dx = abs(px - mx)
                                if dx < best_dx:
                                    best_dx = dx
                                    best_y = py
                            if best_y is not None:
                                my = best_y
                                break
                    # 转换到缩放后坐标，画半径6的实心紫色圆
                    dx_s = int(mx * scale_x)
                    dy_s = int(my * scale_y)
                    if 0 <= dx_s < FIXED_W and 0 <= dy_s < MAP_H:
                        cv2.circle(map_display, (dx_s, dy_s), 6, COLOR_MONSTER_MAP, -1)

        # 【模块B】在缩放后的map_display上画平台编号（更清晰，不会被缩放模糊）
        # 平台编号（缩放后画，红色，加大，不用加粗，LINE_AA抗锯齿）
        for p in self.platforms:
            pts = self._platform_points(p)
            if len(pts) >= 2:
                pf_id = p.get('id', 0) + 1
                xs = [pt[0] for pt in pts]
                ys = [pt[1] for pt in pts]
                cx = int(sum(xs) / len(xs) * scale_x)  # 平台X中心（缩放后）
                cy_top = int(min(ys) * scale_y) - 8     # 绿线上方8PX（缩放后，避免和绿线重叠）
                if 0 <= cx < FIXED_W and 0 <= cy_top < MAP_H:
                    # 红色数字加白色边框（先画白色粗描边，再画红色细字，更清晰）
                    cv2.putText(map_display, str(pf_id), (cx, cy_top),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 3, cv2.LINE_AA)
                    cv2.putText(map_display, str(pf_id), (cx, cy_top),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1, cv2.LINE_AA)

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
        # 【模块B】scale_x手动校准按钮（左端点/右端点）
        draw_asset(frame, self._ui_calib_left, *BTN_CALIB_LEFT)
        draw_asset(frame, self._ui_calib_right, *BTN_CALIB_RIGHT)
        # 【模块B】按钮按下阴影特效（按下时画半透明黑色覆盖层，持续3帧）
        if self._calib_left_pressed > 0:
            cv2.rectangle(frame, (BTN_CALIB_LEFT[0], BTN_CALIB_LEFT[1]),
                          (BTN_CALIB_LEFT[0]+BTN_CALIB_LEFT[2], BTN_CALIB_LEFT[1]+BTN_CALIB_LEFT[3]),
                          (0, 0, 0), -1)
            self._calib_left_pressed -= 1
        if self._calib_right_pressed > 0:
            cv2.rectangle(frame, (BTN_CALIB_RIGHT[0], BTN_CALIB_RIGHT[1]),
                          (BTN_CALIB_RIGHT[0]+BTN_CALIB_RIGHT[2], BTN_CALIB_RIGHT[1]+BTN_CALIB_RIGHT[3]),
                          (0, 0, 0), -1)
            self._calib_right_pressed -= 1
        # 【模块B】记录后按钮高亮（白色边框表示已记录）
        if getattr(self, '_calib_left_pt', None):
            cv2.rectangle(frame, (BTN_CALIB_LEFT[0]-1, BTN_CALIB_LEFT[1]-1),
                          (BTN_CALIB_LEFT[0]+BTN_CALIB_LEFT[2]+1, BTN_CALIB_LEFT[1]+BTN_CALIB_LEFT[3]+1),
                          (255, 255, 255), 1)
        if getattr(self, '_calib_right_pt', None):
            cv2.rectangle(frame, (BTN_CALIB_RIGHT[0]-1, BTN_CALIB_RIGHT[1]-1),
                          (BTN_CALIB_RIGHT[0]+BTN_CALIB_RIGHT[2]+1, BTN_CALIB_RIGHT[1]+BTN_CALIB_RIGHT[3]+1),
                          (255, 255, 255), 1)
        # 第三个框显示当前方案名或"随机"
        plan_label = "随机" if self.route_mode == "随机" else "方案%d" % self.current_route
        (plw, plh), _ = cv2.getTextSize(plan_label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        plx = BTN_PLAN_TOOLBAR[0] + (BTN_PLAN_TOOLBAR[2] - plw) // 2
        ply = BTN_PLAN_TOOLBAR[1] + (BTN_PLAN_TOOLBAR[3] + plh) // 2 - 2
        cv2.putText(frame, plan_label, (plx, ply), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)

        # === 缩放到UI尺寸并合成到背景 ===
        map_scaled = cv2.resize(map_display, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H, UI_MAP_X:UI_MAP_X+UI_MAP_W] = map_scaled

        # === 【模块B】台子选择按钮（小地图左上方）===
        # 点击弹出选择面板，可多选平台，选完关闭
        btn_sel_x, btn_sel_y, btn_sel_w, btn_sel_h = UI_MAP_X + 5, UI_MAP_Y + 5, 60, 20
        self._btn_platform_selector = (btn_sel_x, btn_sel_y, btn_sel_w, btn_sel_h)
        cv2.rectangle(frame, (btn_sel_x, btn_sel_y), (btn_sel_x+btn_sel_w, btn_sel_y+btn_sel_h), (60, 60, 60), -1)
        cv2.rectangle(frame, (btn_sel_x, btn_sel_y), (btn_sel_x+btn_sel_w, btn_sel_y+btn_sel_h), (150, 150, 150), 1)
        cv2.putText(frame, "台子选择", (btn_sel_x+5, btn_sel_y+14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
        # 显示当前选中的平台数量
        if self._selected_platforms:
            sel_text = "已选:%d" % len(self._selected_platforms)
            cv2.putText(frame, sel_text, (btn_sel_x+btn_sel_w+5, btn_sel_y+14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1, cv2.LINE_AA)
        else:
            cv2.putText(frame, "全部", (btn_sel_x+btn_sel_w+5, btn_sel_y+14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (200, 200, 200), 1, cv2.LINE_AA)

        # === 【模块B】台子选择面板（点击"台子选择"后弹出）===
        if self._show_platform_selector and self.platforms:
            # 面板位置：小地图内部，覆盖在小地图上
            panel_x, panel_y = UI_MAP_X + 10, UI_MAP_Y + 30
            panel_w, panel_h = UI_MAP_W - 20, min(150, 30 + len(self.platforms) * 22)
            # 面板背景
            cv2.rectangle(frame, (panel_x, panel_y), (panel_x+panel_w, panel_y+panel_h), (40, 40, 40), -1)
            cv2.rectangle(frame, (panel_x, panel_y), (panel_x+panel_w, panel_y+panel_h), (180, 180, 180), 1)
            # 标题
            cv2.putText(frame, "选择打怪平台（可多选）", (panel_x+8, panel_y+16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
            # 关闭按钮X
            close_x, close_y = panel_x + panel_w - 20, panel_y + 4
            self._btn_platform_selector_close = (close_x, close_y, 16, 16)
            cv2.rectangle(frame, (close_x, close_y), (close_x+16, close_y+16), (80, 80, 80), -1)
            cv2.putText(frame, "X", (close_x+4, close_y+13),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
            # 平台编号列表（每行5个，圆形样式：选中=黄底黑字，未选中=白底黑字）
            per_row = 5
            for idx, pf in enumerate(self.platforms):
                pf_num = idx + 1  # 编号从1开始
                row = idx // per_row
                col = idx % per_row
                item_x = panel_x + 10 + col * 36
                item_y = panel_y + 28 + row * 22
                # 圆形中心和半径
                circle_cx = item_x + 8
                circle_cy = item_y + 8
                circle_r = 8
                # 选中=黄底黑字，未选中=白底黑字
                checked = pf_num in self._selected_platforms
                bg_color = (0, 255, 255) if checked else (255, 255, 255)  # 黄色/白色BGR
                text_color = (0, 0, 0)  # 黑色
                cv2.circle(frame, (circle_cx, circle_cy), circle_r, bg_color, -1)
                cv2.circle(frame, (circle_cx, circle_cy), circle_r, (100, 100, 100), 1)
                # 编号文字（居中）
                num_text = str(pf_num)
                (tw, th), _ = cv2.getTextSize(num_text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
                cv2.putText(frame, num_text, (circle_cx - tw//2, circle_cy + th//2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, text_color, 1, cv2.LINE_AA)
                # 记录每个编号的点击区域（用于鼠标点击检测）
                # 存储在临时变量中，on_mouse时用
        else:
            self._btn_platform_selector_close = None

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
        1. 全图搜索（阈值0.70）
        2. 全图失败时在上次位置附近ROI搜索（阈值0.55），避免战斗中短暂丢人物
        Returns:
            (center_x, center_y, confidence) 或 None
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
            self._last_char_match_pos = (cx, cy)
            self._last_char_match_time = time.time() * 1000
            return (cx, cy, best_score)

        # === ROI回退：在上次成功位置附近160x160范围搜索，阈值降到0.55 ===
        last_pos = getattr(self, '_last_char_match_pos', None)
        if last_pos:
            lx, ly = last_pos
            roi_x1 = max(0, lx - 80)
            roi_y1 = max(0, ly - 80)
            roi_x2 = min(fw, lx + 80)
            roi_y2 = min(fh, ly + 80)
            roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]
            if roi.shape[0] > 20 and roi.shape[1] > 20:
                roi_best = 0
                roi_loc = None
                roi_tpl = None
                for tpl in self._char_templates:
                    timg = tpl["img"]
                    th, tw = timg.shape[:2]
                    if th > roi.shape[0] or tw > roi.shape[1]:
                        continue
                    result = cv2.matchTemplate(roi, timg, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(result)
                    if max_val > roi_best:
                        roi_best = max_val
                        roi_loc = max_loc
                        roi_tpl = tpl
                if roi_best >= 0.55 and roi_loc is not None:
                    cx = roi_x1 + roi_loc[0] + roi_tpl["width"] // 2
                    cy = roi_y1 + roi_loc[1] + roi_tpl["height"] // 2
                    self._last_char_match_pos = (cx, cy)
                    self._last_char_match_time = time.time() * 1000
                    _debug_log("[人物匹配] ROI回退成功 %.2f (全图%.2f) 位置(%d,%d)" % (roi_best, best_score, cx, cy))
                    return (cx, cy, roi_best)

        # 全图+ROI都失败：节流日志
        _now = time.time()
        if not hasattr(self, '_last_lowscore_log') or _now - self._last_lowscore_log > 5:
            self._last_lowscore_log = _now
            _debug_log("[人物匹配] 全图%.2f ROI失败，低于阈值%.2f" % (best_score, CHAR_MATCH_THRESHOLD))
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
                            hp_marker = data.get('hp_marker')
                            if hp_marker:
                                hx, hy = hp_marker
                                pen = gdi32.CreatePen(0, 1, 0xFFFFFF)  # 白框1px
                                if pen:
                                    gdi_objs.append(pen)
                                old_pen = gdi32.SelectObject(hdc, pen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷
                                gdi32.Rectangle(hdc, hx - 3, hy, hx + 3, hy + 10)
                                gdi32.SelectObject(hdc, old_pen)
                            mp_marker = data.get('mp_marker')
                            if mp_marker:
                                mx, my = mp_marker
                                pen = gdi32.CreatePen(0, 1, 0xFFFFFF)  # 白框1px
                                if pen:
                                    gdi_objs.append(pen)
                                old_pen = gdi32.SelectObject(hdc, pen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷
                                gdi32.Rectangle(hdc, mx - 3, my, mx + 3, my + 10)
                                gdi32.SelectObject(hdc, old_pen)
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
                                gdi32.SelectObject(hdc, old_pen)
                                gdi32.SelectObject(hdc, old_brush)
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
                        first_draw[0] = False
                    user32.SetWindowPos(hwnd, -1, wr['left'], wr['top'],
                                        wr['width'], wr['height'], 0x0050)
                elif first_draw[0]:
                    _debug_log("[怪物蒙板] 警告：hwnd或window_rect无效")
                    first_draw[0] = False
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
                canvas.delete('all')
                data = self._monster_overlay_data
                now_ms = time.time() * 1000
                if data:
                    hp_marker = data.get('hp_marker')
                    if hp_marker:
                        hx, hy = hp_marker
                        canvas.create_rectangle(hx - 2, hy, hx + 2, hy + 10, outline='red', width=2)
                    mp_marker = data.get('mp_marker')
                    if mp_marker:
                        mx, my = mp_marker
                        canvas.create_rectangle(mx - 2, my, mx + 2, my + 10, outline='#0080FF', width=2)
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
        """SendInput扫描码发键 + AttachThreadInput强制前台。duration为按键保持ms，默认随机80-180"""
        vk = self._key_to_vk(key_name)
        if vk is None:
            _debug_log("按键未知: %s" % key_name)
            return
        if not self.hwnd:
            _debug_log("无窗口句柄")
            return
        if duration is None:
            duration = random.randint(80, 180)
        kernel32 = ctypes.windll.kernel32
        scan = user32.MapVirtualKeyW(vk, 0)
        EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0xA3, 0xA5}
        ext = 0x0001 if vk in EXTENDED_VKS else 0
        old_fg = user32.GetForegroundWindow()
        _debug_log("发键 %s vk=0x%02X scan=0x%02X ext=%d dur=%d" % (key_name, vk, scan, ext, duration))

        # === 强制把游戏窗口拉到前台 ===
        game_thread = user32.GetWindowThreadProcessId(self.hwnd, None)
        cur_thread = kernel32.GetCurrentThreadId()
        attached = False
        if game_thread != 0 and game_thread != cur_thread:
            attached = user32.AttachThreadInput(cur_thread, game_thread, True)

        # 先模拟按一下Alt键，绕过Windows SetForegroundWindow限制
        user32.keybd_event(0x12, 0, 0, 0)  # Alt down
        user32.keybd_event(0x12, 0, 0x0002, 0)  # Alt up
        user32.BringWindowToTop(self.hwnd)
        fg_ret = user32.SetForegroundWindow(self.hwnd)
        # 如果还没成功，再试一次（带最小化恢复）
        if user32.GetForegroundWindow() != self.hwnd:
            if user32.IsIconic(self.hwnd):
                user32.ShowWindow(self.hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(self.hwnd)
        time.sleep(0.05)
        fg_now = user32.GetForegroundWindow()
        fg_ok = (fg_now == self.hwnd)
        if not fg_ok:
            _debug_log("[发键警告] 前台切换失败! fg_ret=%d 当前前台hwnd=%s 目标hwnd=%s attached=%d" % (
                fg_ret, fg_now, self.hwnd, attached))

        # === 用 SendInput 发送按键（比 keybd_event 更可靠）===
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
        class INPUT(ctypes.Structure):
            class _INPUT(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]
            _anonymous_ = ("_input",)
            _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT)]

        def send_key(vk_code, scan_code, flags):
            inp = INPUT()
            inp.type = 1  # INPUT_KEYBOARD
            inp.ki.wVk = 0  # 扫描码模式下wVk设0
            inp.ki.wScan = scan_code
            inp.ki.dwFlags = flags | 0x0008  # KEYEVENTF_SCANCODE，DirectInput兼容
            inp.ki.time = 0
            inp.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        # 清除可能卡住的修饰键（Alt/Ctrl/Shift），避免Alt+Key组合
        for mod_vk in (0x12, 0x11, 0x10):  # Alt, Ctrl, Shift
            if user32.GetAsyncKeyState(mod_vk) & 0x8000:
                mod_scan = user32.MapVirtualKeyW(mod_vk, 0)
                send_key(mod_vk, mod_scan, 0x0002)  # KEYEVENTF_KEYUP
                _debug_log("清除卡住的修饰键 vk=0x%02X" % mod_vk)

        send_key(vk, scan, ext)  # keydown
        time.sleep(duration / 1000.0)
        send_key(vk, scan, ext | 0x0002)  # keyup (KEYEVENTF_KEYUP)
        # keybd_event双发兜底（DirectInput游戏有时只认keybd_event）
        user32.keybd_event(vk, scan, ext, 0)
        time.sleep(duration / 1000.0 * 0.5)
        user32.keybd_event(vk, scan, ext | 0x0002, 0)
        _debug_log("SendInput(扫描码)+keybd_event双发已发送 fg_ok=%d attached=%d dur=%d" % (fg_ok, attached, duration))
        time.sleep(0.05)

        # 恢复原前台窗口并分离线程
        if attached:
            if old_fg and old_fg != self.hwnd:
                user32.SetForegroundWindow(old_fg)
            user32.AttachThreadInput(cur_thread, game_thread, False)

    def _detect_hp_mp_bars(self, frame):
        """检测HP/MP血条：搜底部50px（血条在y=770~778，距底部约30px），HSV颜色，HP在左MP在右"""
        if frame is None:
            return None, None
        h, w = frame.shape[:2]
        y_start = max(0, h - 50)  # 原h-25太小，血条在y=770距底部37px，需要搜到底部50px
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

        # === 低血量兜底：红色/蓝色填充<20px时_find_longest_hbar返回None ===
        # 用上次稳定位置兜底（条的y坐标基本不变）
        if hp_bar is None and getattr(self, '_hp_bar_stable', None):
            hp_bar = self._hp_bar_stable
            _debug_log("HP颜色检测失败(<20px)，使用稳定缓存 y=%d" % hp_bar[1])
        if mp_bar is None and getattr(self, '_mp_bar_stable', None):
            mp_bar = self._mp_bar_stable
            _debug_log("MP颜色检测失败(<20px)，使用稳定缓存 y=%d" % mp_bar[1])
        # 首次就低血量：扫描底部25px任意红色像素找y坐标
        if hp_bar is None:
            for row in range(hp_mask.shape[0]):
                if hp_mask[row].sum() >= 1:
                    hp_bar = (0, y_start + row, 0)  # 占位，下面替换为固定位置
                    _debug_log("HP首次低血量，扫描到红色行 y=%d" % (y_start + row))
                    break
        if mp_bar is None and hp_bar:
            for row in range(mp_mask.shape[0]):
                if mp_mask[row].sum() >= 1:
                    mp_bar = (0, y_start + row, 0)
                    _debug_log("MP首次低血量，扫描到蓝色行 y=%d" % (y_start + row))
                    break

        # 固定血条位置和宽度（窗口大小固定1382x807，坐标不变）
        # HP条：左=510，宽=107；MP条：左=619，宽=107（和HP一样长）
        # Y坐标固定成死值，不随检测变化，避免每次启动Y值不一样
        FIXED_HP_LEFT = 510
        FIXED_MP_LEFT = 619
        FIXED_BAR_WIDTH = 107
        FIXED_BAR_Y = 782  # HP/MP条固定Y坐标（死值，如需调整改这个数字）
        if hp_bar:
            hp_bar = (FIXED_HP_LEFT, FIXED_BAR_Y, FIXED_BAR_WIDTH)
        if mp_bar:
            mp_bar = (FIXED_MP_LEFT, FIXED_BAR_Y, FIXED_BAR_WIDTH)
        elif hp_bar:
            # MP颜色检测失败（MP不满时蓝色少），用固定Y坐标
            mp_bar = (FIXED_MP_LEFT, FIXED_BAR_Y, FIXED_BAR_WIDTH)
        # Y已固定成死值，不需要稳定性缓存，避免覆盖固定Y值导致双检测框
        _debug_log("血条检测: hp=%s mp=%s" % (hp_bar, mp_bar))
        return hp_bar, mp_bar

    def _measure_bar_total_width(self, frame, x, y, color_type):
        """从条的左边界向右扫描，找到条的右边缘（非条内颜色），返回总宽度
        MP条内=B>180(亮蓝+暗蓝), HP条内=R>100(亮红+暗红)"""
        if frame is None or y >= frame.shape[0] or x >= frame.shape[1]:
            return None
        scan_y = y + 2
        if scan_y >= frame.shape[0]:
            scan_y = y
        out_count = 0
        for i in range(200):
            cx = x + i
            if cx >= frame.shape[1]:
                break
            b, g, r = frame[scan_y, cx]
            ri, gi, bi = int(r), int(g), int(b)
            if color_type == "hp":
                # 红色占优才算条内（排除灰色空白背景）
                in_bar = ri > 80 and ri - gi > 10 and ri - bi > 10
            else:
                # 蓝色占优才算条内（排除灰色空白背景）
                in_bar = bi > 100 and bi - ri > 10 and bi - gi > 10
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

    # HP/MP条参考色（从样品图取色，BGR格式）
    HP_REF_COLOR = (0, 0, 238)    # 红色
    MP_REF_COLOR = (222, 111, 0)  # 蓝青色
    COLOR_MATCH_DIST = 50         # 欧氏距离阈值，小于此值算同色

    def _is_bar_blank_at(self, frame, bar, pct, color_type):
        """竖框检测：在pct%位置取区域，用灰色模板匹配，匹配到=空白=加药。
        模板是用户截取的血条空白灰色部分(gray_bar.png)，直接matchTemplate。"""
        if bar is None or frame is None or self._gray_bar_template is None:
            return False
        x, y, bw = bar
        check_x = x + int(bw * pct / 100.0)
        if check_x >= frame.shape[1] or check_x < 0:
            return False
        th, tw = self._gray_bar_template.shape[:2]
        # 在check_x周围取比模板大的ROI
        roi_x1 = max(0, check_x - tw // 2 - 4)
        roi_y1 = max(0, y - 3)
        roi_x2 = min(frame.shape[1], roi_x1 + tw + 8)
        roi_y2 = min(frame.shape[0], roi_y1 + th + 6)
        roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]
        if roi.shape[0] < th or roi.shape[1] < tw:
            return False
        result = cv2.matchTemplate(roi, self._gray_bar_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        match_ok = max_val >= 0.70
        _debug_log("竖框匹配 %s: x=%d pct=%d 匹配度=%.3f -> %s" % (
            color_type, check_x, pct, max_val, match_ok))
        return match_ok

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
                bw, bh = x2 - x1, y2 - y1
                # 大小过滤：怪通常宽30-110，高40-140，太大的是建筑误检
                if 20 <= bw <= 130 and 30 <= bh <= 160:
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
        search_areas: 限定搜索区域 [(x1,y1,x2,y2),...]，None则全屏搜索
        用于近战人物挡住怪物身体时，凭血条定位怪物"""
        if frame is None:
            return []
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        # 怪物血条颜色（样本取色：绿色为主 H:35-80 S:90-255 V:80-255）
        m_g = cv2.inRange(hsv, np.array([35, 90, 80]), np.array([80, 255, 255]))
        # 红色（低血量时可能变红，保留兼容）
        m_r1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([12, 255, 255]))
        m_r2 = cv2.inRange(hsv, np.array([165, 80, 80]), np.array([180, 255, 255]))
        mask = cv2.bitwise_or(cv2.bitwise_or(m_r1, m_r2), m_g)
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
                # 血条特征：宽>高*2，宽度15-80px，高度2-8px
                if bw > bh * 2 and 15 <= bw <= 80 and 2 <= bh <= 8:
                    bars.append((sx1 + x, sy1 + y, bw, bh))
        # 去重：位置接近的只保留一个
        if bars:
            filtered = []
            for b in sorted(bars, key=lambda x: x[2] * x[3], reverse=True):
                if not any(abs(b[0] - f[0]) < 25 and abs(b[1] - f[1]) < 12 for f in filtered):
                    filtered.append(b)
            bars = filtered
        return bars

    def _detect_damage_number(self, target_cx, target_cy):
        """【模块A-需求4】检测目标头顶上方是否有伤害数字（红→黄渐变+黑描边）
        用途：攻击怪物时头顶会飘出红→黄渐变的伤害数字(如422/484)，有数字=怪还活着
        参数：target_cx=目标中心X, target_cy=目标脚底Y
        原理：
          1. 从YOLO识别的怪物bbox中找到对应目标，取头顶y1作基准（不同怪物高度不同）
          2. 在头顶上方60px区域内搜索红→黄渐变色(H:0-35, 饱和度≥70, 亮度≥70)
          3. 像素≥25个且有连通区域≥10像素 → 判定有伤害数字
        返回：True=有伤害数字(怪活着), False=没有"""
        # 步骤1：从已检测怪物列表中找到离目标中心最近的怪物，获取其头顶y1
        target_y1 = None
        best_d = 999
        for (x1, y1, x2, y2, _) in self._monsters:
            cx = (x1 + x2) // 2  # 怪物中心X
            cy = y2               # 怪物脚底Y
            d = abs(cx - target_cx) + abs(cy - target_cy)  # 曼哈顿距离
            if d < best_d:
                best_d = d
                target_y1 = y1  # 记录怪物头顶Y
        if target_y1 is None:
            return False  # 没找到对应怪物，无法检测

        # 步骤2：截取游戏画面，在目标头顶上方区域搜索
        frame = self._capture_window()
        if frame is None:
            return False
        h, w = frame.shape[:2]
        # 搜索区域：头顶y1上方60px，水平中心±45px（覆盖伤害数字飘动范围）
        rx1 = max(0, target_cx - 45)
        rx2 = min(w, target_cx + 45)
        ry1 = max(0, target_y1 - 60)  # 头顶上方60px
        ry2 = min(h, target_y1 + 5)   # 包含头顶位置
        if rx2 <= rx1 or ry2 <= ry1:
            return False
        roi = frame[ry1:ry2, rx1:rx2]  # 截取搜索区域

        # 步骤3：HSV颜色空间检测红→黄渐变色
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # H:0-35覆盖红(0)、橙(15)、黄(30)；饱和度≥70排除灰色；亮度≥70排除暗色
        mask = cv2.inRange(hsv, np.array([0, 70, 70]), np.array([35, 255, 255]))
        if np.sum(mask > 0) < 25:
            return False  # 红→黄像素太少，不是伤害数字

        # 步骤4：连通区域检测，排除零散噪点
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            if cv2.contourArea(cnt) >= 10:  # 有面积≥10的连通区域=数字
                return True
        return False

    def _get_player_screen_pos(self, frame):
        """获取人物在游戏画面中的坐标（复用_match_character内存模板+X/Y偏移）
        匹配失败时：1.5秒宽限期内用上次成功位置，超过才返回None"""
        match = self._match_character(frame)
        if match:
            mx, my, _ = match
            x_off = int(self._field_values.get("char_x_offset", "0") or "0")
            y_off = int(self._field_values.get("char_y_offset", "0") or "0")
            return (mx + x_off, my + y_off)
        # 匹配失败：1.5秒宽限期内用上次成功位置（战斗中短暂丢模板不立即停手）
        last_pos = getattr(self, '_last_char_match_pos', None)
        last_time = getattr(self, '_last_char_match_time', 0)
        now_ms = time.time() * 1000
        if last_pos and now_ms - last_time < 1500:
            mx, my = last_pos
            x_off = int(self._field_values.get("char_x_offset", "0") or "0")
            y_off = int(self._field_values.get("char_y_offset", "0") or "0")
            if not hasattr(self, '_last_grace_log') or now_ms - self._last_grace_log > 1000:
                self._last_grace_log = now_ms
                _debug_log("[人物定位] 宽限期使用上次位置 (%d,%d) 丢失%.0fms" % (mx + x_off, my + y_off, now_ms - last_time))
            return (mx + x_off, my + y_off)
        # 超过宽限期：返回None
        _now = time.time()
        if not hasattr(self, '_last_posfail_log') or _now - self._last_posfail_log > 5:
            self._last_posfail_log = _now
            _debug_log("[人物定位] 未匹配到角色（模板%d套，阈值%.2f），宽限期已过" % (len(self._char_templates), CHAR_MATCH_THRESHOLD))
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
        """模板匹配检测MP标签是否可见（全窗口检测原图）。
        可见=True => 没被遮挡，可以吃药
        不可见=False => 被挡住，跳过吃药"""
        if self._mp_label_template is None or frame is None:
            return True  # 无模板时不拦截
        th, tw = self._mp_label_template.shape[:2]
        h, w = frame.shape[:2]
        if h < th or w < tw:
            return True
        # 全窗口直接检测原图，不做ROI裁剪
        result = cv2.matchTemplate(frame, self._mp_label_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        visible = max_val >= 0.35
        if not visible:
            _debug_log("[MP遮挡] 全窗口匹配度%.3f<0.35, 判定被遮挡" % max_val)
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
                self._rlog("血条被遮挡，暂不自动加血加蓝", (200, 100, 0))
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

            # 吃药诊断日志（每秒一次，无条件输出，便于排查）
            if now - getattr(self, '_last_pot_diag_log', 0) > 1000:
                self._last_pot_diag_log = now
                hp_info = "无条" if not self._hp_bar else "x=%d,w=%d" % (self._hp_bar[0], self._hp_bar[2])
                mp_info = "无条" if not self._mp_bar else "x=%d,w=%d" % (self._mp_bar[0], self._mp_bar[2])
                overlay = "开" if self._monster_overlay_running else "关"
                mp_tpl = "无" if self._mp_label_template is None else "%dx%d" % self._mp_label_template.shape[:2]
                print("[吃药诊断] 蒙板=%s 遮挡=%s MP模板=%s HP条:%s HP空=%s MP条:%s MP空=%s" % (
                    overlay, occluded, mp_tpl, hp_info, hp_blank, mp_info, mp_blank))

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
            else:
                self._monster_overlay_data['hp_marker'] = None
            if self._mp_bar:
                mx, my, mw = self._mp_bar
                self._monster_overlay_data['mp_marker'] = (
                    mx + int(mw * mp_thresh / 100.0), my)
            else:
                self._monster_overlay_data['mp_marker'] = None

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

    def _filter_monsters_on_platform(self, monsters, player_screen_pos):
        """过滤出和玩家同一平台的怪（怪用脚Y，人用手Y，同平台差约30-50px）"""
        if not player_screen_pos or not monsters:
            return monsters
        _, py = player_screen_pos
        same_platform = []
        for m in monsters:
            x1, y1, x2, y2, score = m
            if abs(y2 - py) <= 50:  # 怪脚 vs 人手
                same_platform.append(m)
        return same_platform

    def _is_monster_on_platform(self, monster_cx, monster_cy):
        """判断怪是否在玩家当前平台上（已接入新的_get_monster_platform逻辑）
        1. 有平台数据：用新函数判定怪在哪个平台，和人物当前平台ID比较
        2. 无平台数据：回退到屏幕y差判断（怪脚vs人手≤50）"""
        # 调用新函数：怪屏幕坐标 → 估算小地图坐标 → 到绿线距离最小的平台
        monster_pf = self._get_monster_platform(monster_cx, monster_cy)
        player_pf = self._get_current_platform()
        if monster_pf and player_pf:
            # 平台ID相同 = 同平台
            return monster_pf.get('id') == player_pf.get('id')
        # 无平台数据时回退到屏幕y差判断（兼容旧版本）
        if self._player_screen_pos:
            return abs(monster_cy - self._player_screen_pos[1]) <= 50
        return False

    def _combat_tick(self):
        """人性化战斗：反应延迟→转身→走位→攻击，群攻3只起，带随机容错"""
        if not self._running or self.hwnd is None:
            return
        now = time.time() * 1000
        fight_cfg = self._get_fight_config()
        pot_cfg = self._get_potion_config()

        # === 【模块B】手动录制平台边界检测 + 回退 ===
        # 人物到了平台边缘，不管在打怪还是做什么，都回退平台宽度的20%
        # 回退完成后继续正常打怪
        boundary_dir = self._check_platform_boundary()
        if boundary_dir and not getattr(self, '_platform_retreat_active', False):
            # 触发回退：计算回退目标（平台宽度的20%）
            pf = self._get_current_manual_platform()
            if pf and self._player_map_pos:
                x_min, x_max = self._platform_x_range(pf)
                platform_width = x_max - x_min
                retreat_dist = platform_width * 0.2  # 回退平台宽度的20%
                px = self._player_map_pos[0]
                if boundary_dir == 'right':
                    # 超出左边界，往右回退
                    self._platform_retreat_target_x = px + retreat_dist
                    self._platform_retreat_dir = 'right'
                else:
                    # 超出右边界，往左回退
                    self._platform_retreat_target_x = px - retreat_dist
                    self._platform_retreat_dir = 'left'
                self._platform_retreat_active = True
                self._release_combat_move()  # 释放当前移动键
                _debug_log("[平台边界] 触发回退 方向=%s 目标X=%.1f 回退距离=%.1f" % (
                    boundary_dir, self._platform_retreat_target_x, retreat_dist))
        # 回退过程中：按住方向键往回走，不攻击
        if getattr(self, '_platform_retreat_active', False) and self._player_map_pos:
            px = self._player_map_pos[0]
            target = self._platform_retreat_target_x
            rdir = self._platform_retreat_dir
            reached = (rdir == 'right' and px >= target) or (rdir == 'left' and px <= target)
            if reached:
                # 到达回退目标，恢复正常
                self._platform_retreat_active = False
                self._release_combat_move()
                _debug_log("[平台边界] 回退完成 到达X=%.1f" % px)
            else:
                # 继续回退：按住方向键
                self._set_combat_move(rdir)
                return  # 回退过程中不攻击，直接返回

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

        # === YOLO怪物检测 + 血条检测（每50ms一次，双检测合并）===
        if now - self._last_yolo_check > 50:
            self._last_yolo_check = now
            frame = self._capture_window()
            if frame is not None:
                yolo_monsters = self._detect_monsters(frame)
                self._player_screen_pos = self._get_player_screen_pos(frame)
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

                self._monster_hp_bars = self._detect_monster_hp_bars(
                    frame, _search if _search else None)

                # 血条位置转怪物坐标（血条正下方就是怪的位置）
                hp_monsters = []
                for (bx, by, bw, bh) in self._monster_hp_bars:
                    hp_monsters.append((bx, by+bh+5, bx+bw, by+bh+55, 0.4))

                # YOLO结果按置信度过滤（低置信度=城里建筑误检）
                conf_thresh = getattr(self, '_yolo_conf_thresh', 0.5)
                filtered_yolo = [m for m in yolo_monsters if m[4] >= conf_thresh]

                # 合并去重：YOLO结果 + 血条单独检测的怪
                merged = list(filtered_yolo)
                for hm in hp_monsters:
                    hcx = (hm[0] + hm[2]) // 2
                    hcy = (hm[1] + hm[3]) // 2
                    dup = False
                    for ym in filtered_yolo:
                        ycx = (ym[0] + ym[2]) // 2
                        ycy = (ym[1] + ym[3]) // 2
                        if abs(hcx - ycx) < 35 and abs(hcy - ycy) < 50:
                            dup = True
                            break
                    if not dup:
                        merged.append(hm)
                self._monsters = merged

                _mc = len(self._monsters)
                if _mc > 0 and _mc != getattr(self, "_last_logged_mc", -1):
                    self._rlog("发现怪物%d只(YOLO%d+血条%d,阈值%.1f)" % (
                        _mc, len(filtered_yolo), len(hp_monsters), conf_thresh), (0, 100, 200))
                    self._last_logged_mc = _mc
                elif _mc == 0:
                    self._last_logged_mc = 0

        # === 反应延迟 / 转身 锁定（后摇锁已去掉，连续攻击）===
        if now < self._combat_react_until:
            return
        if now < self._combat_turn_until:
            return
        if now < self._combat_busy_until:
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
            # 【模块A】无怪时重置所有战斗状态，恢复巡路
            self._combat_active = False          # 取消战斗活跃，巡路恢复移动
            self._combat_range_clear = False     # 退出范围清怪模式
            self._combat_target_lock_x = None    # 清除锁定X基准
            self._combat_target_alive = False    # 清除存活状态
            self._release_combat_move()
            return

        # === 有目标（当前平台上有怪）===
        px, py = self._player_screen_pos

        # 首次发现目标：反应延迟
        if not self._combat_had_target:
            self._combat_had_target = True
            self._combat_react_until = now + random.randint(80, 250)
            return

        # 计算怪物距离并排序（同平台优先，距离相近时左边先打）
        # 怪的Y用bbox底部（脚的位置），和人物点（手的位置）基准对齐
        # 【模块B】手动录制平台X范围过滤：有手动录制平台时只打X范围内的怪
        # 【模块B】平台选择过滤：只打选中平台上的怪（空列表=全部平台）
        has_manual_pf = self._get_current_manual_platform() is not None
        has_platform_select = len(self._selected_platforms) > 0
        monster_dists = []
        for (x1, y1, x2, y2, score) in self._monsters:
            cx = (x1 + x2) // 2
            cy = y2  # 脚的位置
            # 有手动录制平台时，只打X范围内的怪
            if has_manual_pf and not self._is_monster_in_manual_platform(cx, cy):
                continue
            # 平台选择过滤：只打选中平台上的怪
            if has_platform_select:
                monster_pf = self._get_monster_platform(cx, cy)
                if monster_pf:
                    pf_num = monster_pf.get('id', 0) + 1  # 编号从1开始
                    if pf_num not in self._selected_platforms:
                        continue
                else:
                    # 怪不在任何录制平台上，不打
                    continue
            dist = int(np.sqrt((cx - px) ** 2 + (cy - py) ** 2))
            same_platform = self._is_monster_on_platform(cx, cy)
            # 距离20px为一档，同档内按cx升序（左边先打），避免左右晃动
            dist_bucket = dist // 20
            monster_dists.append((0 if same_platform else 1, dist_bucket, cx, dist, cy))
        monster_dists.sort()
        # 同平台有怪才打，没有就释放移动等路线系统切换平台
        if monster_dists[0][0] != 0:
            self._release_combat_move()
            self._combat_locked_target = None
            # 【模块A】同平台无怪，重置战斗状态
            self._combat_active = False
            self._combat_range_clear = False
            return
        monster_dists = [(d, cx, cy) for (prio, db, cx, d, cy) in monster_dists if prio == 0]

        # === 【模块A】技能范围内清怪模式（纯增量：范围内有怪优先打，不改变远处移动逻辑）===
        # 原理：技能攻击距离(默认150px)内的怪优先全部打完，打完一只接下一只，全部清完才走
        atk_dist = fight_cfg.get("atk1_distance", 150)  # 读取配置的攻击距离
        in_range = [(d, cx, cy) for d, cx, cy in monster_dists if d <= atk_dist]  # 筛选范围内的怪
        if in_range:
            # 范围内有怪：进入清怪模式，只考虑范围内的怪
            if not self._combat_range_clear:
                self._combat_range_clear = True  # 标记进入范围清怪模式
                _debug_log("[打怪] 进入技能范围清怪模式，范围内%d只怪" % len(in_range))
            self._combat_active = True  # 战斗活跃，暂停巡路移动
            monster_dists = in_range  # 只打范围内的怪，打完一只自动选下一只
        else:
            # 范围内无怪：结束清怪模式，但不return，继续原有远处移动逻辑（纯增量不改变旧行为）
            if self._combat_range_clear:
                self._combat_range_clear = False
                _debug_log("[打怪] 技能范围内已清完，继续原有移动逻辑")
            self._combat_active = False  # 取消战斗活跃，巡路可移动

        # === 目标锁定规则：锁一只打死再换，不中途切换 ===
        target = None
        if self._combat_locked_target:
            lcx, lcy = self._combat_locked_target
            # 锁定目标还在检测列表中（位置接近）就继续打
            for d, cx, cy in monster_dists:
                if abs(cx - lcx) <= 40 and abs(cy - lcy) <= 50:
                    target = (d, cx, cy)
                    break
            if target is None:
                # 锁定目标消失了（怪死了），解锁选下一只
                self._combat_locked_target = None
                _debug_log("[打怪] 锁定目标已消失，选下一只")

        if target is None:
            # 选当前平台上最近的怪作为新锁定目标
            target = monster_dists[0]
            self._combat_locked_target = (target[1], target[2])
            self._combat_target_hp_confirmed = False  # 新目标重置血条确认状态
            # 【模块A-需求10】记录新目标的首次X和锁定时间，用于1秒无变化检测
            self._combat_target_lock_x = target[1]    # 记录锁定时目标的X坐标
            self._combat_target_lock_time = now         # 记录锁定时间(毫秒)
            self._combat_target_alive = False           # 新目标存活状态待确认
            _debug_log("[打怪] 锁定新目标: 距离%dpx 位置(%d,%d)" % (
                target[0], target[1], target[2]))

        t_dist, t_cx, t_cy = target
        # 更新锁定位置（怪会移动）
        self._combat_locked_target = (t_cx, t_cy)
        # 记录目标位置，用于下一轮血条搜索
        self._combat_last_target_pos = (t_cx, t_cy)

        # === 【模块A-需求10】1秒X无变化检测：怪1秒内X没变化→放弃锁定（可能是死怪/建筑误检）===
        # 原理：真怪会左右移动，建筑/石头不会动。锁定1秒后X变化<5px就判定为假目标
        if self._combat_target_lock_x is not None and now - self._combat_target_lock_time > 1000:
            x_change = abs(t_cx - self._combat_target_lock_x)  # 计算1秒内X变化量
            if x_change < 5:
                # X变化<5px，判定为假目标（建筑/死怪），放弃锁定选下一只
                _debug_log("[打怪] 目标1秒X无变化(变化%dpx<5)，放弃锁定" % x_change)
                self._combat_locked_target = None   # 清除锁定
                self._combat_target_lock_x = None    # 清除X基准
                self._combat_target_alive = False    # 清除存活状态
                return  # 直接返回，下一帧重新选目标
            else:
                # X有变化，更新基准时间和X，继续监测
                self._combat_target_lock_x = t_cx
                self._combat_target_lock_time = now

        # === 【模块A-需求4】怪物存活检测：血条 OR 伤害数字，出现一种就说明怪还在 ===
        # 原理：怪被攻击时头顶会出现绿色血条和红→黄渐变的伤害数字，任意一种出现=怪未死
        target_has_hp = False  # 标记是否检测到血条
        for (bx, by, bw, bh) in self._monster_hp_bars:
            bcx = bx + bw // 2  # 血条中心X
            bcy = by + bh // 2  # 血条中心Y
            if abs(bcx - t_cx) < 55 and abs(bcy - t_cy) < 65:
                target_has_hp = True  # 目标附近有血条
                break
        # 伤害数字检测：目标头顶上方有红→黄渐变像素聚集（攻击后短暂出现）
        target_has_dmg = self._detect_damage_number(t_cx, t_cy)
        # 血条 OR 伤害数字，任意一种=怪还活着
        self._combat_target_alive = target_has_hp or target_has_dmg
        # 攻击成功确认：首次检测到血条=攻击命中
        if target_has_hp and not getattr(self, '_combat_target_hp_confirmed', False):
            self._combat_target_hp_confirmed = True
            _debug_log("[打怪] 攻击成功确认：目标血条已出现 位置(%d,%d)" % (t_cx, t_cy))
            self._rlog("命中目标(血条确认)", (0, 200, 0))

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
            self._combat_turn_until = now + random.randint(100, 300)
            return

        # === 斜坡检测：目标Y差>25px判定为在斜坡上，需要边走边跳才能打到怪 ===
        y_diff = abs(t_cy - py)
        on_slope = y_diff > 25
        jump_key = fight_cfg.get("jump_key", "")

        # === 远处怪朝怪移动靠近 ===
        atk_dist = fight_cfg.get("atk1_distance", 150)
        aoe_dist = fight_cfg.get("aoe_distance", 200)
        effective_range = max(atk_dist, aoe_dist)
        if t_dist > effective_range:
            move_dir = "right" if t_cx > px else "left"
            # 平台边界：到边缘停止
            current_pf = self._get_current_platform()
            if current_pf and self._player_map_pos:
                ppx, _ = self._player_map_pos
                pf_xmin, pf_xmax = self._platform_x_range(current_pf)
                if move_dir == "right" and ppx >= pf_xmax - 2:
                    self._release_combat_move()
                    return
                if move_dir == "left" and ppx <= pf_xmin + 2:
                    self._release_combat_move()
                    return
            self._set_combat_move(move_dir)
            # 【模块C】跳跃触发：斜坡(怪Y差>25) OR 前方绿线有波动(断层/上坡/下坡)，都要跳着跑
            slope_ahead = self._check_platform_slope_ahead(move_dir)
            if (on_slope or slope_ahead) and jump_key and now - self._combat_last_jump > 400:
                self._press_game_key(jump_key, duration=80)
                self._combat_last_jump = now
            self._combat_last_move = now
            return

        # 进入攻击范围
        move_dir = "right" if t_cx > px else "left"
        # 【模块C】跳跃触发：斜坡(怪Y差>25) OR 前方绿线有波动(断层/上坡/下坡)，都要跳着跑+攻击
        slope_ahead = self._check_platform_slope_ahead(move_dir)
        if on_slope or slope_ahead:
            # 斜坡/波动攻击：保持朝目标X方向移动 + 周期性跳跃 + 攻击（站着打不到波动地形上的怪）
            self._set_combat_move(move_dir)
            if jump_key and now - self._combat_last_jump > 350:
                self._press_game_key(jump_key, duration=70)
                self._combat_last_jump = now
            _debug_log("[打怪] 斜坡/波动攻击 y_diff=%d 绿线波动=%s 方向=%s" % (y_diff, slope_ahead, move_dir))
        else:
            # 平地：站定攻击
            self._release_combat_move()

        skill_rand = fight_cfg.get("skill_random", 50)
        skill_cast = False

        # --- 群攻：范围内>=3只怪，80%概率放 ---
        aoe_key = fight_cfg.get("aoe_key", "")
        if not skill_cast and aoe_key:
            aoe_dist = fight_cfg.get("aoe_distance", 200)
            aoe_cd = fight_cfg.get("aoe_interval", 1000)
            in_range = sum(1 for d, _, _ in monster_dists if d <= aoe_dist)
            last = self._attack_last.get("aoe", 0)
            if in_range >= 3 and now - last > aoe_cd + random.randint(-skill_rand, skill_rand):
                if random.random() < 0.8:
                    self._press_game_key(aoe_key)
                    self._attack_last["aoe"] = now
                    skill_cast = True
                    self._rlog("群攻 %s 范围内%d只" % (aoe_key, in_range), (0, 165, 255))
                    print("[群攻] %s 释放 (范围内%d只怪)" % (aoe_key, in_range))

        # --- 主攻：目标在距离内，5%按错 ---
        atk_key = fight_cfg.get("atk1_key", "")
        if not skill_cast and atk_key:
            atk_dist = fight_cfg.get("atk1_distance", 150)
            atk_cd = fight_cfg.get("atk1_interval", 300)
            last = self._attack_last.get("atk1", 0)
            if t_dist <= atk_dist and now - last > atk_cd + random.randint(-skill_rand, skill_rand):
                if random.random() < 0.05 and aoe_key:
                    self._press_game_key(aoe_key)
                    self._rlog("主攻(按错) %s" % aoe_key, (0, 200, 0))
                else:
                    self._press_game_key(atk_key)
                    self._rlog("主攻 %s 距离%d" % (atk_key, t_dist), (0, 200, 0))
                self._attack_last["atk1"] = now
                skill_cast = True
                print("[主攻] %s 释放 (目标%dpx)" % (atk_key, t_dist))

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
            # 【模块B】独立检测人物屏幕位置（不依赖运行状态，脚本启动就工作，和加药一样）
            # 用于自动校准scale和记录左右端点；_combat_tick中不再重复检测
            if self.hwnd and (not getattr(self, '_player_screen_pos', None) or self.frame_count % 10 == 0):
                try:
                    _frame = self._capture_window()
                    if _frame is not None:
                        self._player_screen_pos = self._get_player_screen_pos(_frame)
                except Exception:
                    pass
            # 【模块B】自动校准scale比例（人物移动时记录屏幕和小地图变化，越跑越准）
            self._update_scale_calibration()
            # 【模块B】自动记录人物最左/最右端点（用于scale_x校准，每帧只做2次比较不卡）
            self._auto_calibrate_edges()

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

            # === 偏移视觉反馈（游戏画面中角色匹配点+偏移点）===
            try:
                self._show_offset_feedback()
            except Exception as e:
                print("[偏移反馈] 异常:", e)

            # === 透明蒙板（怪物/黄点/血条红点/蓝条蓝点统一显示）===
            # 检测结果由 _combat_tick 每350ms更新到 self._monsters / self._player_screen_pos
            # 蒙板只要窗口绑定成功就启动（不依赖_running），确保加药竖框始终可见
            if self.hwnd and not self._monster_overlay_running:
                self._start_monster_overlay()
            if self._running:
                try:
                    if self._monster_overlay_data is None:
                        self._monster_overlay_data = {}
                    # 同步怪物和人物位置到蒙板
                    self._monster_overlay_data["monsters"] = self._monsters
                    self._monster_overlay_data["monster_hp_bars"] = self._monster_hp_bars
                    if self._player_screen_pos:
                        self._monster_overlay_data["char_pos"] = self._player_screen_pos
                except Exception as e:
                    print("[蒙板] 同步异常:", e)

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
    # === 管理员权限检查 ===
    # 游戏(冒险岛怀旧服)以管理员权限运行，UIPI会阻止普通权限进程向管理员进程发送模拟输入
    # 必须以管理员权限启动bot，否则按键/加药全部无效
    import ctypes as _ctypes, sys as _sys
    def _is_admin():
        try:
            return _ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False
    if not _is_admin():
        print("[权限] 检测到非管理员权限，游戏以管理员运行时必须以管理员启动bot")
        print("[权限] 正在自动以管理员权限重启...")
        try:
            _params = " ".join(['"%s"' % a for a in _sys.argv[1:]]) if len(_sys.argv) > 1 else ""
            _ctypes.windll.shell32.ShellExecuteW(None, "runas", _sys.executable, _params, None, 1)
        except Exception as _e:
            print("[权限] 自动提升失败: %s" % _e)
            print("[权限] 请右键 MapleBot.exe 选择'以管理员身份运行'")
            try:
                input("按回车退出...")
            except:
                pass
        _sys.exit()
    print("[权限] 已以管理员权限运行，模拟输入可正常发送到游戏")
    MinimapRouteRecorder().run()
