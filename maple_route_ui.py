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
from PIL import Image, ImageDraw, ImageFont
import os
import json
import base64
import time
import sys
# 设置默认编码为UTF-8，解决Python 3.9中文乱码问题
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
import subprocess
import queue
import random
import threading
import pygame  # 用于创建透明置顶准星窗口，支持拖拽到屏幕任意位置
import win32gui  # Windows GUI API，用于设置窗口置顶和透明
import win32con  # Windows常量定义
import win32api  # Windows API，用于RGB颜色转换

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
WINDOW_KEYWORDS = ["冒险岛", "MapleStory Worlds"]  # 自动绑定匹配冒险岛和MapleStory Worlds，其他窗口用准星手动绑定
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
# 怪物特征按钮（盖住原来的X/Y偏移输入框，点击打开怪物特征管理弹窗）
BTN_MONSTER_FEATURE = (215, 624, 190, 60)  # 和UI图片大小一致(190x60)，直接用原图不缩放

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
# 【模块B】X倍率按钮（分开取样：只用绿圈取X分量；坐标对准背景图"X倍率"按钮 x227-284）
BTN_CALIB_AUTO = (227, 104, 57, 25)
# 【模块B】Y倍率按钮（分开取样：只用蓝圈取Y分量；坐标对准背景图"Y倍率"按钮 x294-351）
BTN_CALIB_Y = (294, 104, 57, 25)

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
YELLOW_H_LOW = 20  # 黄色H下限
YELLOW_H_HIGH = 35  # 黄色H上限（收紧，排除偏橙/偏绿的噪声）
YELLOW_S_LOW = 100  # 饱和度下限（从80提高到100，排除淡黄噪声）
YELLOW_V_LOW = 180  # 亮度下限（从150提高到180，人物光点很亮，排除偏暗黄色）

VK_F4 = 0x73
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
PLANS_FILE = os.path.join(DATA_DIR, "plans.json")  # 方案索引（地图分组+方案列表）
BLUE_BOX_FILE = os.path.join(DATA_DIR, "blue_box_config.json")  # 蓝色框(一屏范围在小地图上的对应尺寸)校准配置

# === 人物特征模板 ===
CHAR_TEMPLATE_DIR = os.path.join(DATA_DIR, "char_templates")
os.makedirs(CHAR_TEMPLATE_DIR, exist_ok=True)
CHAR_TEMPLATE_META = os.path.join(CHAR_TEMPLATE_DIR, "meta.json")
CHAR_MAX_TEMPLATES = 10
CHAR_MATCH_THRESHOLD = 0.70
# 人物特征颜色（暖色系，BGR格式，10种不重复）
CHAR_FEATURE_COLORS = [
    (0, 0, 255),      # 红
    (0, 165, 255),    # 橙
    (0, 255, 255),    # 黄
    (203, 192, 255),  # 粉
    (255, 0, 255),    # 紫
    (128, 0, 128),    # 洋红
    (0, 0, 139),      # 深红
    (0, 140, 255),    # 深橙
    (0, 215, 255),    # 金黄
    (180, 105, 255),  # 浅粉
]

# === 怪物特征模板（手动添加怪物特征，和YOLO合并显示小地图紫点） ===
MONSTER_TEMPLATE_DIR = os.path.join(DATA_DIR, "monster_templates")
os.makedirs(MONSTER_TEMPLATE_DIR, exist_ok=True)
MONSTER_TEMPLATE_META = os.path.join(MONSTER_TEMPLATE_DIR, "meta.json")
MONSTER_MAX_TEMPLATES = 10
MONSTER_MATCH_THRESHOLD = 0.70  # 阈值0.70（和人物一样），匹配更稳定减少闪烁，移动时跟手不延迟
# 怪物特征颜色（冷色系，BGR格式，10种不重复，和人物颜色分开）
MONSTER_FEATURE_COLORS = [
    (255, 0, 0),      # 蓝
    (0, 255, 0),      # 绿
    (255, 255, 0),    # 青
    (255, 255, 128),  # 浅蓝
    (128, 255, 128),  # 浅绿
    (139, 0, 0),      # 深蓝
    (0, 139, 0),      # 深绿
    (139, 139, 0),    # 深青
    (255, 128, 0),    # 湖蓝
    (0, 255, 128),    # 春绿
]

# === 人物定位框（蒙板绿色大框，以人物黄点为中心） ===
PLAYER_BOX_W = 150  # 人物定位框宽度（先用大尺寸框住，精准后再改小）
PLAYER_BOX_H = 190  # 人物定位框高度

# === 绿框钳制（限制小地图绿框整体移动范围，不重叠窗口边缘） ===
BOX_CLAMP_LEFT = 4    # 绿框左边距窗口左边缘最小px
BOX_CLAMP_RIGHT = 5   # 绿框右边距窗口右边缘最小px
BOX_CLAMP_TOP = 3     # 绿框上边距窗口上边缘最小px
BOX_CLAMP_BOTTOM = 3  # 绿框下边距窗口下边缘最小px

# === 镜头死区检测（三个背景框，帧差对比检测镜头是否在动） ===
# 三个默认检测点（整个窗口坐标，含标题栏+边框）：左下/左上/右中
BG_DETECT_DEFAULT_REGIONS = [
    {"x": 35, "y": 744, "w": 40, "h": 39},    # 左下
    {"x": 170, "y": 43, "w": 46, "h": 23},    # 左上
    {"x": 1320, "y": 409, "w": 43, "h": 28},  # 右中
]
BG_DIFF_THRESHOLD = 5.0       # 帧差均值阈值，超过此值判定该区域在动（调小更灵敏，镜头动了更容易检测到）
BG_MOTION_MIN_REGIONS = 3     # 至少几个区域在动才判定镜头在跟随
BG_STILL_FRAMES_TO_DEADZONE = 3  # 连续几帧不动才切到死区状态
BG_DETECT_REGIONS_FILE = os.path.join(DATA_DIR, "bg_detect_regions.json")  # 检测框位置持久化

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
    """返回指定方案的平台文件和梯子文件路径（route_id为数字1~100，文件名route_001格式）"""
    return (
        os.path.join(DATA_DIR, "route_%03d_platforms.json" % route_id),
        os.path.join(DATA_DIR, "route_%03d_ladders.json" % route_id)
    )

def route_files_by_id(plan_id):
    """通过plan_id字符串（如'route_001'）返回文件路径"""
    num = int(plan_id.split("_")[1])
    return route_files(num)

def plan_id_to_num(plan_id):
    """route_001 → 1"""
    return int(plan_id.split("_")[1])

def num_to_plan_id(num):
    """1 → route_001"""
    return "route_%03d" % num

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
        self.map_area_rect = None
        try:
            self.hwnd = _find_game_window()
            if self.hwnd:
                self._update_window_rect()
                self._detect_minimap()  # 恢复原来的自动检测，避免显示窗口变小
                self._save_target_window_size()
                print("[窗口绑定] 自动绑定成功")
                # 启动人物坐标跟踪线程（暂时注释，排查绑定问题）
                # self._start_player_track()
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
        # 方案系统：地图分组+多方案（最多100地图×每地图10方案）
        self.current_route = 1
        self.route_mode = "手动"
        self.plans_data = {"maps": [], "current_id": "route_001"}  # 方案索引数据
        self._dropdown = None  # 当前展开的下拉菜单: None/"save"/"route"/"mode"/"clear_route"
        # 独立窗口引用
        self._plan_window = None  # 方案管理窗口
        self._char_feature_window = None  # 人物特征管理弹窗
        self._save_window = None  # 保存方案窗口
        self._clear_window = None  # 删除方案窗口
        # 原地打怪归位相关
        self._idle_combat_start_pos = None  # 原地打怪起始屏幕坐标
        self._idle_combat_attack_start = 0  # 开始攻击时间戳
        self._idle_combat_no_damage_duration = 0  # 第一次无伤害时的攻击总时长(秒)
        self._idle_combat_last_turn = 0  # 上次转身时间
        self._idle_combat_turn_interval = 0  # 转身间隔(秒)，在无伤害时长±5秒内随机
        self._idle_combat_no_damage_logged = False  # 是否已提示未勾选方案
        self._route_reelect_time = 0  # 下次重新随机选路线的时间戳
        self._return_fail_count = 0  # 归位失败计数
        self._return_attempt_mode = None  # 当前归位尝试方式: 'jump'/'ladder'/'platform'
        # 【模块B】平台选择：选择在哪个平台上打怪（编号从1开始，空列表=全部平台）
        self._selected_platforms = []  # 选中的平台编号列表，空=全部平台
        self._show_platform_selector = False  # 是否显示平台选择面板
        # 平台选择按钮区域（小地图左上方）
        self._btn_platform_selector = None  # "台子选择"按钮
        self._btn_platform_selector_close = None  # 选择面板关闭按钮
        # 【倍率差弹窗】按照弹窗组件实现规范实现
        self._show_scale_dialog = False  # 是否显示倍率差弹窗
        self._scale_dialog_pos = [70, 230]  # 弹窗位置（可移动，拖拽标题栏移动）
        self._scale_dialog_dragging = False  # 是否正在拖拽弹窗
        self._scale_dialog_drag_offset = [0, 0]  # 拖拽时的偏移量
        self._scale_dialog_backup = {}  # 弹窗打开时备份原始值，取消/关闭时恢复（确认才保存）
        # 弹窗内控件位置（必须初始化，否则点击检测时None会崩溃）
        self._dlg_scale_x_input = (0, 0, 0, 0)  # X偏差输入框位置
        self._dlg_scale_y_input = (0, 0, 0, 0)  # Y偏差输入框位置
        self._dlg_scale_ok_btn = (0, 0, 0, 0)  # 确认按钮位置
        self._dlg_scale_cancel_btn = (0, 0, 0, 0)  # 取消按钮位置
        self._dlg_scale_close_btn = (0, 0, 0, 0)  # 右上角关闭按钮X位置
        # 倍率差按钮区域（右上角，对准新背景图上的倍率差按钮）
        self._btn_scale_dialog = (370, 96, 45, 30)  # 倍率差按钮位置
        # 【模块B】端点按钮按下特效状态
        self._calib_left_pressed = False
        self._calib_right_pressed = False
        self._calib_top_pressed = False
        self._calib_top_pt = None  # Y轴上端点：(屏幕Y, 小地图Y)
        # 可拖拽准星（窗口绑定用）
        self._crosshair_size = CROSSHAIR_SIZE
        self._crosshair_home = CROSSHAIR_POS
        self._crosshair_pos = self._crosshair_home
        self._drag_crosshair = False
        # pygame透明置顶准星窗口（拖拽时显示，可拖到屏幕任意位置）
        self._crosshair_pygame_window = None  # pygame窗口对象
        self._crosshair_pygame_screen = None  # pygame屏幕对象
        self._crosshair_pygame_hwnd = None  # 准星窗口句柄
        self._crosshair_pygame_inited = False  # pygame是否已初始化
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
        # 【模块B】自动校准按钮（同屏三点校准：基点+右800+上500）
        self._ui_calib_auto = load_png(resource_path(os.path.join("data", "ui_calib_auto.png")))
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
        # 蓝色框校准（一屏范围在小地图上的对应尺寸，光点在框内归一化=人物在屏幕内归一化）
        self._blue_box = None  # {"width":w, "height":h} 校准后大小，None=未校准(回退旧方案)
        # 镜头死区检测（三个背景框，帧差对比检测镜头是否在动）
        # === 镜头死区检测状态（31号版本实现：状态机+绿框冻结） ===
        self._bg_regions = [dict(r) for r in BG_DETECT_DEFAULT_REGIONS]  # 三个检测区域
        self._bg_last_frames = [None, None, None]  # 上一帧各区域ROI
        self._bg_diff_values = [0.0, 0.0, 0.0]  # 各区域帧差均值
        self._camera_state = "deadzone"  # 状态机：deadzone(镜头不动)/following(镜头在动)
        self._camera_still_count = 0  # 连续不动帧数
        self._blue_box_deadzone_pos = None  # 进入死区时冻结的绿框位置
        # 注意：蒙板覆盖整个游戏窗口（含标题栏），和lock_screen_from_dot坐标体系一致，不需要_char_box_offset偏移
        self._last_dot_pos = None  # 上一帧光点位置（用于判断光点是否在移动）
        self._bg_dragging = -1  # 右键移动模式：当前选中的检测框索引，-1=无
        self._bg_editing = False  # 检测框编辑状态：True=可拖动，False=正常
        self._bg_motion_count = 0  # 当前帧背景在动的区域数(0~3)，蒙板三框着色用：3=全动绿，否则红
        self._deadzone_delay = 0  # 死区切换延迟计数器：光点停了后等30帧确认镜头真停了再切死区（镜头惯性约0.5秒）
        self._feedforward_strength = 0.0  # 前馈强度系数：启动阶段0→2渐变(约60帧/1秒)，匀速保持2，停止后2→0渐变
        self._follow_frame_count = 0  # 跟随状态持续帧数，用于前馈启动渐变
        self._stop_frame_count = 0  # 人物停止后帧数，用于前馈衰减渐变和延迟切死区
        self._last_rbutton_down = False  # 上一帧右键是否按下（防抖）
        self._load_bg_regions()  # 从配置文件加载检测框位置
        self._calibrating_blue_box = False  # 是否在校准模式
        self._blue_box_corners = []  # 校准中四个角点坐标[(x,y),...]（小地图原始坐标）
        self._selected_corner = -1  # 当前选中的角点索引0-3，-1=未选中
        # 人物特征模板（最多10套）
        self._char_templates = []  # [{id, img(numpy), width, height, created_at}]
        self._load_char_templates()
        # 怪物特征模板（手动添加，和YOLO合并显示小地图紫点，最多10套）
        self._monster_templates = []  # [{id, img, width, height, offset_x, offset_y, direction, created_at}]
        self._last_monster_match_pos = None
        self._last_monster_match_time = 0
        self._load_monster_templates()
        # 打怪/药品输入框状态
        self._field_values = {}  # {field_id: value_string}
        self._focused_field = None  # 当前聚焦的字段id
        self._load_input_config()
        # YOLO模型路径（手动选择）
        self._yolo_model_path = None
        self._load_yolo_config()
        # 加载蓝色框校准配置
        self._load_blue_box()
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
        # 加载当前方案的左右端点（和平台梯子一起作为一套方案，永久保存）
        self._calib_left_pt = None
        self._calib_right_pt = None
        self._calib_top_pt = None
        calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % self.current_route)
        if os.path.exists(calib_file):
            try:
                with open(calib_file, "r", encoding="utf-8") as f:
                    cd = json.load(f)
                self._calib_left_pt = cd.get("calib_left")
                self._calib_right_pt = cd.get("calib_right")
                self._calib_top_pt = cd.get("calib_top")
                # 加载倍率数据（程序重启后自动恢复，不需要重新校准）
                saved_sx = cd.get("calibrated_scale_x", 0)
                saved_sy = cd.get("calibrated_scale_y", 0)
                if saved_sx > 0 and saved_sy > 0:
                    self._calibrated_scale_x = saved_sx
                    self._calibrated_scale_y = saved_sy
                    self._map_screen_scale = saved_sx
                    print("[初始化] 已加载方案%d倍率: X=%.4f Y=%.4f" % (self.current_route, saved_sx, saved_sy))
            except Exception:
                pass

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
        self._char_feature_matches = []     # 人物特征单独匹配结果 [(x, y, tpl_id, confidence), ...]
        self._monster_feature_matches = []  # 怪物特征单独匹配结果 [(x, y, tpl_id, confidence), ...]
        self._monster_overlay_thread = None
        # 人物坐标跟踪线程（单独线程，每帧截图+人物匹配，确保人物点死死咬住位置不跳变）
        self._player_track_thread = None
        self._player_track_stop = False
        self._player_track_lock = threading.Lock()
        # 【模块B】自动校准状态（同屏三点校准：基点+右800+上500）
        self._auto_calib_stage = 0  # 0=空闲, 1=蒙板出三点可拖动定特色位置, 2=已记录绿点小地图位置待记录蓝点, 3=完成
        self._auto_calib_base = None  # 基点：(屏幕X, 屏幕Y, 小地图X, 小地图Y)
        self._auto_calib_green_map = None  # 绿点小地图坐标（人物走到特色位置后记录光点位置）
        self._auto_calib_blue_map = None  # 蓝点小地图坐标（人物走到特色位置后记录光点位置）
        self._auto_calib_green_screen = None  # 绿点屏幕坐标（蒙板拖动定特色位置，stage>=2时固定）
        self._auto_calib_blue_screen = None  # 蓝点屏幕坐标（蒙板拖动定特色位置，stage>=2时固定）
        self._auto_calib_green_offset = (400, 0)  # 绿点相对基点的偏移（stage=1时拖动调整，跟着人物移动）
        self._auto_calib_blue_offset = (0, -400)  # 蓝点相对基点的偏移（stage=1时拖动调整，跟着人物移动）
        self._auto_calib_dragging = None  # 蒙板拖动状态：None/'green'/'blue'
        self._auto_calib_axis = 'X'  # 【倍率新方案】当前校准方向：'X'=绿圈只取X，'Y'=蓝圈只取Y（由点X倍率/Y倍率按钮决定）
        self._auto_calib_retry = 0  # 【倍率新方案】当前步骤连续失败次数，达到3次退出整个校准流程
        # 模板匹配跟踪（第二次点倍率后截图特色背景，模板匹配跟踪位置，画绿/蓝空心圆）
        self._calib_green_template = None  # 绿点位置的背景模板图（numpy数组）
        self._calib_blue_template = None   # 蓝点位置的背景模板图
        self._calib_green_match_pos = None  # 绿点模板匹配到的屏幕位置 (x, y)
        self._calib_blue_match_pos = None   # 蓝点模板匹配到的屏幕位置 (x, y)
        self._calib_template_size = 45       # 模板截图大小（45x45像素，圆45里面内容44，匹配更精准）
        self._calib_match_threshold = 0.65   # 模板匹配置信度阈值（降到0.65，远处绿/蓝圈也能识别到）
        # 热键跑马灯滚动偏移（从右到左流动）
        self._hotkey_scroll_x = 0
        # 热键跑马灯预加载字体（避免每帧加载导致卡顿）
        try:
            self._hotkey_font = ImageFont.truetype("simhei.ttf", 24)
        except Exception:
            self._hotkey_font = ImageFont.load_default()
        # 按钮点击特效
        self._pressed_btn = None       # 当前按下的按钮rect (x,y,w,h)
        self._btn_flashes = []         # [(rect, start_ms, color_bgr), ...]

        # 加载UI背景图（五个标签页）
        self._ui_bgs = {}
        for tab, fname in [("route", "ui_bg_blank.png"), ("fight", "ui_tab_fight.png"),
                           ("potion", "ui_tab_potion.png"), ("chat", "ui_tab_chat.png"),
                           ("lie", "ui_tab_lie.png")]:
            p = resource_path(os.path.join("data", fname))
            img = load_png(p)
            if img is not None:
                if img.ndim == 3 and img.shape[2] == 4:
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                self._ui_bgs[tab] = cv2.resize(img, (UI_W, UI_H))
                print("[UI背景] 加载成功:", fname, img.shape)
            else:
                print("[UI背景] 加载失败:", p)
                self._ui_bgs[tab] = np.ones((UI_H, UI_W, 3), dtype=np.uint8) * 200
        self._ui_bg = self._ui_bgs["route"]
        self._current_tab = "route"

        # 顶部标签页点击区域（高度收紧，避免和下方按钮重叠）
        self._tab_areas = {
            "route": (_s(5), _s(34), _s(75), _s(28)),
            "fight": (_s(82), _s(34), _s(60), _s(28)),
            "potion": (_s(145), _s(34), _s(60), _s(28)),
            "chat": (_s(207), _s(34), _s(58), _s(28)),
            "lie": (_s(266), _s(34), _s(58), _s(28)),
        }

        # 日志
        self._logs = []

        # map_area_rect 已在__init__开头初始化，此处不重置（会覆盖自动绑定的检测结果）

        if self.map_area_rect:
            print("Map area:", self.map_area_rect["width"], "x", self.map_area_rect["height"])
        else:
            print("Map area: 未检测到（请先绑定游戏窗口或F9校准）")
        print("方案 %d 已加载: %d 平台, %d 梯子 (模式: %s)" % (
            self.current_route, len(self.platforms), len(self.ladders), self.route_mode))
        print("UI: 左上角=刷新/手动/方案X  第一排=平台/梯子/保存▼/方案▼")
        print("    第二排=清除(绿=平台)/清除(蓝=梯子)/模式▼/清除(橙=方案)\n")

        # 自动备份线程：已永久关闭（2026-09-01用户要求），函数_auto_backup_loop保留但不启动
        # self._auto_backup_interval = 1800  # 30分钟
        # self._last_backup_time = 0
        # self._auto_backup_thread = threading.Thread(target=self._auto_backup_loop, daemon=True)
        # self._auto_backup_thread.start()
        # print("[自动备份] 已启动，每30分钟Git自动提交一次")

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

    def _update_scale_dialog_positions(self):
        """立即计算弹窗内所有控件的位置（解决第一次打开弹窗点击没反应的问题）"""
        dlg_x = self._scale_dialog_pos[0]  # 弹窗X坐标
        dlg_y = self._scale_dialog_pos[1]  # 弹窗Y坐标
        dlg_w, dlg_h = 320, 220  # 弹窗宽高
        # 右上角关闭按钮X
        self._dlg_scale_close_btn = (dlg_x+dlg_w-30, dlg_y+5, 25, 25)
        # X偏差输入框
        self._dlg_scale_x_input = (dlg_x+110, dlg_y+65, 160, 35)
        # Y偏差输入框
        self._dlg_scale_y_input = (dlg_x+110, dlg_y+125, 160, 35)
        # 确认按钮
        self._dlg_scale_ok_btn = (dlg_x+60, dlg_y+175, 80, 30)
        # 取消按钮
        self._dlg_scale_cancel_btn = (dlg_x+180, dlg_y+175, 80, 30)

    def _create_crosshair_window(self):
        """创建pygame透明置顶准星窗口，用于拖拽时显示准星，可拖到屏幕任意位置"""
        if not self._crosshair_pygame_inited:
            pygame.init()  # 初始化pygame
            self._crosshair_pygame_inited = True
        # 创建无边框窗口
        cs = self._crosshair_size * 2  # 窗口大小是准星大小的2倍，留出边距
        self._crosshair_pygame_window = pygame.display.set_mode((cs, cs), pygame.NOFRAME)
        self._crosshair_pygame_screen = self._crosshair_pygame_window
        # 获取窗口句柄
        self._crosshair_pygame_hwnd = pygame.display.get_wm_info()["window"]
        # 设置窗口置顶
        win32gui.SetWindowPos(self._crosshair_pygame_hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                               win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        # 设置窗口透明（白色透明）
        ex_style = win32gui.GetWindowLong(self._crosshair_pygame_hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(self._crosshair_pygame_hwnd, win32con.GWL_EXSTYLE,
                                ex_style | win32con.WS_EX_LAYERED)
        win32gui.SetLayeredWindowAttributes(self._crosshair_pygame_hwnd, win32api.RGB(255, 255, 255), 0, win32con.LWA_COLORKEY)
        print("[准星] pygame透明置顶窗口已创建")

    def _update_crosshair_window(self, screen_x, screen_y):
        """更新准星窗口位置到屏幕坐标
        Args:
            screen_x: 屏幕X坐标
            screen_y: 屏幕Y坐标
        """
        if self._crosshair_pygame_hwnd is None:
            return
        cs = self._crosshair_size * 2  # 窗口大小
        # 把窗口左上角移动到准星中心减去窗口半径的位置
        win_x = screen_x - cs // 2
        win_y = screen_y - cs // 2
        win32gui.SetWindowPos(self._crosshair_pygame_hwnd, 0, win_x, win_y, 0, 0,
                               win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
        # 绘制准星
        self._draw_crosshair_on_pygame()

    def _draw_crosshair_on_pygame(self):
        """在pygame窗口上绘制准星（红色）"""
        if self._crosshair_pygame_screen is None:
            return
        cs = self._crosshair_size * 2  # 窗口大小
        center = cs // 2  # 准星中心
        r = self._crosshair_size // 2  # 准星半径
        # 清屏（白色背景，会被透明化）
        self._crosshair_pygame_screen.fill((255, 255, 255))
        # 绘制准星（红色）
        pygame.draw.circle(self._crosshair_pygame_screen, (255, 0, 0), (center, center), r, 2)
        pygame.draw.line(self._crosshair_pygame_screen, (255, 0, 0), (center - r - 4, center), (center - r + 1, center), 2)
        pygame.draw.line(self._crosshair_pygame_screen, (255, 0, 0), (center + r - 1, center), (center + r + 4, center), 2)
        pygame.draw.line(self._crosshair_pygame_screen, (255, 0, 0), (center, center - r - 4), (center, center - r + 1), 2)
        pygame.draw.line(self._crosshair_pygame_screen, (255, 0, 0), (center, center + r - 1), (center, center + r + 4), 2)
        pygame.display.flip()  # 更新显示

    def _destroy_crosshair_window(self):
        """销毁pygame准星窗口（只隐藏窗口，不调用pygame.display.quit()，避免video system not initialized错误）"""
        if self._crosshair_pygame_hwnd is not None:
            # 只隐藏窗口，不退出pygame显示，避免下一帧调用pygame.event.pump()时报错
            win32gui.ShowWindow(self._crosshair_pygame_hwnd, win32con.SW_HIDE)
            self._crosshair_pygame_window = None
            self._crosshair_pygame_screen = None
            self._crosshair_pygame_hwnd = None
            print("[准星] pygame透明置顶窗口已隐藏")

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
                self._recalc_scale_from_region()
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
        # X范围固定100-400（不管地图多宽都能检测到，避免宽地图时超出范围）
        roi_b_x1 = 100
        roi_b_x2 = 400
        roi_b = frame[0:120, roi_b_x1:roi_b_x2]
        res_b = cv2.matchTemplate(roi_b, tpl_b, cv2.TM_CCOEFF_NORMED)
        _, val_b, _, loc_b = cv2.minMaxLoc(res_b)
        big_x = roi_b_x1 + loc_b[0]
        big_y = max(0, mini_y - 5) + loc_b[1]
        if debug:
            print("大地图: val=%.3f at (%d,%d)" % (val_b, big_x, big_y))

        # 3. 边界：左=小地图左，右=大地图右，上=小地图下
        # 白边偏移量：LEFT_OFFSET正数=向右移=左边增加白边；TOP_OFFSET正数=向下移=去掉上面白边；BOTTOM_OFFSET负数=向上移=去掉下面白边
        LEFT_OFFSET = -4  # 向左扩4像素（修复左边显示不全，-6多2px，-4刚好）
        TOP_OFFSET = 6  # 上面去掉6像素白边（和右边一样宽）
        BOTTOM_OFFSET = -6  # 下面去掉6像素白边（和右边一样宽）
        left = mini_x + LEFT_OFFSET  # 左边加偏移量
        right = big_x + bw
        top = mini_y + mh + TOP_OFFSET  # 上面加偏移量
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
                # 底部边界定在模板图片的上下正中间，加BOTTOM_OFFSET偏移量（负数=向上移=去掉下面白边）
                bottom = search_y1 + loc_btm[1] + btm_h // 2 + BOTTOM_OFFSET
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

        # 轻量模式：区域变化小于1px则不更新（防抖，确保小变化也能生效），不写文件不写图
        if not debug:
            old = self.map_area_rect
            if old is not None and (abs(old["left"] - new_map["left"]) <= 1 and
                abs(old["top"] - new_map["top"]) <= 1 and
                abs(old["width"] - new_map["width"]) <= 1 and
                abs(old["height"] - new_map["height"]) <= 1):
                return
            if old is not None:
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
        """加载方案配置：plans.json（地图+方案）+ route_config.json（运行方式），自动迁移旧数据"""
        # 先迁移旧数据（route_1/2/3 → plans.json）
        self._migrate_old_plans()
        # 加载plans.json
        if os.path.exists(PLANS_FILE):
            try:
                with open(PLANS_FILE, "r", encoding="utf-8") as f:
                    self.plans_data = json.load(f)
            except Exception:
                pass
        # 从plans_data恢复current_route
        cid = self.plans_data.get("current_id", "route_001")
        self.current_route = plan_id_to_num(cid)
        # 加载运行方式
        if os.path.exists(ROUTE_CONFIG_FILE):
            try:
                with open(ROUTE_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.route_mode = data.get("route_mode", "手动")
            except Exception:
                pass

    def _save_route_config(self):
        """保存运行方式（手动/随机）"""
        with open(ROUTE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"route_mode": self.route_mode}, f, indent=2)

    def _save_plans(self):
        """保存plans.json方案索引"""
        with open(PLANS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.plans_data, f, indent=2, ensure_ascii=False)

    def _migrate_old_plans(self):
        """旧数据迁移：route_1/2/3 → plans.json（只在plans.json不存在时执行）"""
        if os.path.exists(PLANS_FILE):
            return
        plans = []
        name_map = {1: "方案一", 2: "方案二", 3: "方案三"}
        for i in range(1, 4):
            old_pf = os.path.join(DATA_DIR, "route_%d_platforms.json" % i)
            new_pf = os.path.join(DATA_DIR, "route_%03d_platforms.json" % i)
            old_ld = os.path.join(DATA_DIR, "route_%d_ladders.json" % i)
            new_ld = os.path.join(DATA_DIR, "route_%03d_ladders.json" % i)
            old_cb = os.path.join(DATA_DIR, "route_%d_calib.json" % i)
            new_cb = os.path.join(DATA_DIR, "route_%03d_calib.json" % i)
            # 重命名文件
            for old, new in ((old_pf, new_pf), (old_ld, new_ld), (old_cb, new_cb)):
                if os.path.exists(old) and not os.path.exists(new):
                    try:
                        os.rename(old, new)
                    except Exception:
                        pass
            # 如果新文件存在，加入迁移列表
            if os.path.exists(new_pf):
                plans.append({"id": num_to_plan_id(i), "name": name_map[i], "selected": False})
        if plans:
            self.plans_data = {
                "maps": [{"name": "默认地图", "plans": plans}],
                "current_id": plans[0]["id"]
            }
            self._save_plans()
            print("[迁移] 旧方案数据已迁移到plans.json: %d个方案" % len(plans))

    # ===== 方案CRUD =====

    def _find_map(self, map_name):
        """查找地图dict，找不到返回None"""
        for m in self.plans_data["maps"]:
            if m["name"] == map_name:
                return m
        return None

    def _find_plan(self, plan_id):
        """查找方案dict和所属地图dict，返回(plan_dict, map_dict)"""
        for m in self.plans_data["maps"]:
            for p in m["plans"]:
                if p["id"] == plan_id:
                    return p, m
        return None, None

    def _next_plan_id(self):
        """获取下一个可用的方案ID（route_001~route_100）"""
        used = set()
        for m in self.plans_data["maps"]:
            for p in m["plans"]:
                used.add(p["id"])
        for i in range(1, 101):
            pid = num_to_plan_id(i)
            if pid not in used:
                return pid
        return None

    def _create_plan(self, map_name):
        """在指定地图下创建新方案，返回plan_dict或None（满了）"""
        mp = self._find_map(map_name)
        if mp is None:
            # 创建新地图
            if len(self.plans_data["maps"]) >= 100:
                return None
            mp = {"name": map_name, "plans": []}
            self.plans_data["maps"].append(mp)
        if len(mp["plans"]) >= 10:
            return None
        pid = self._next_plan_id()
        if pid is None:
            return None
        plan = {"id": pid, "name": "方案%d" % (len(mp["plans"]) + 1), "selected": False}
        mp["plans"].append(plan)
        self._save_plans()
        return plan

    def _delete_plan(self, plan_id):
        """删除方案（文件+索引）"""
        plan, mp = self._find_plan(plan_id)
        if plan is None:
            return
        num = plan_id_to_num(plan_id)
        pf_file, ld_file = route_files(num)
        calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % num)
        for f in (pf_file, ld_file, calib_file):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        mp["plans"].remove(plan)
        # 空地图也删除
        if not mp["plans"]:
            self.plans_data["maps"].remove(mp)
        self._save_plans()
        print("[删除] 方案 %s 已删除" % plan["name"])

    def _delete_map(self, map_name):
        """删除整个地图及其下所有方案"""
        mp = self._find_map(map_name)
        if mp is None:
            return
        for plan in mp["plans"]:
            num = plan_id_to_num(plan["id"])
            pf_file, ld_file = route_files(num)
            calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % num)
            for f in (pf_file, ld_file, calib_file):
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
        self.plans_data["maps"].remove(mp)
        self._save_plans()
        print("[删除] 地图 '%s' 及其下%d个方案已清空" % (map_name, len(mp["plans"])))

    def _rename_plan(self, plan_id, new_name):
        """重命名方案"""
        plan, _ = self._find_plan(plan_id)
        if plan:
            plan["name"] = new_name
            self._save_plans()

    def _rename_map(self, old_name, new_name):
        """重命名地图"""
        mp = self._find_map(old_name)
        if mp and not self._find_map(new_name):
            mp["name"] = new_name
            self._save_plans()

    def _set_plan_selected(self, plan_id, selected):
        """勾选/取消勾选方案（跨地图自动取消其他地图勾选）"""
        target_plan, target_map = self._find_plan(plan_id)
        if target_plan is None:
            return
        if selected:
            # 勾选：取消其他所有地图的勾选
            for m in self.plans_data["maps"]:
                if m is not target_map:
                    for p in m["plans"]:
                        p["selected"] = False
            target_plan["selected"] = True
        else:
            target_plan["selected"] = False
        self._save_plans()

    def _get_selected_plans(self):
        """获取当前勾选的方案列表（同一地图下）"""
        result = []
        for m in self.plans_data["maps"]:
            for p in m["plans"]:
                if p["selected"]:
                    result.append(p)
        return result

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
        """保存当前录制的平台+梯子+端点到指定方案文件（覆盖）"""
        pf_file, ld_file = route_files(route_id)
        with open(pf_file, "w", encoding="utf-8") as f:
            json.dump({"platforms": self.platforms, "count": len(self.platforms)}, f, indent=2)
        with open(ld_file, "w", encoding="utf-8") as f:
            json.dump({"ladders": self.ladders, "count": len(self.ladders)}, f, indent=2)
        # 同时保存端点（左/右/上）到方案文件
        self._save_calib()
        self.current_route = route_id
        self.plans_data["current_id"] = num_to_plan_id(route_id)
        self._save_plans()
        self._save_route_config()
        print("[保存] 方案%d: %d 平台, %d 梯子, 端点左=%s 右=%s 上=%s（已覆盖）" % (
            route_id, len(self.platforms), len(self.ladders),
            "有" if self._calib_left_pt else "无", "有" if self._calib_right_pt else "无",
            "有" if getattr(self, '_calib_top_pt', None) else "无"))

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
        self.plans_data["current_id"] = num_to_plan_id(route_id)
        pf_file, ld_file = route_files(route_id)
        self.platforms = self._load(pf_file, "platforms")
        self.ladders = self._load(ld_file, "ladders")
        # 切换方案时加载对应方案的左右端点
        self._calib_left_pt = None
        self._calib_right_pt = None
        self._calib_top_pt = None
        calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % route_id)
        if os.path.exists(calib_file):
            try:
                with open(calib_file, "r", encoding="utf-8") as f:
                    cd = json.load(f)
                self._calib_left_pt = cd.get("calib_left")
                self._calib_right_pt = cd.get("calib_right")
                self._calib_top_pt = cd.get("calib_top")
                # 加载倍率数据
                saved_sx = cd.get("calibrated_scale_x", 0)
                saved_sy = cd.get("calibrated_scale_y", 0)
                if saved_sx > 0 and saved_sy > 0:
                    self._calibrated_scale_x = saved_sx
                    self._calibrated_scale_y = saved_sy
                    self._map_screen_scale = saved_sx
                    print("[切换] 方案%d 已加载倍率: X=%.4f Y=%.4f" % (route_id, saved_sx, saved_sy))
                # 人物特征是全局数据（识别自己角色），不随方案切换；权威存储为磁盘 data/char_templates/char_<id>.png，由_load_char_templates加载
                # 此处不再从方案配置的char_template_b64读取并覆盖内存（旧机制会把10张覆盖成1张，记录005/v94已修复）
                # 加载YOLO模型路径
                yolo_path = cd.get("yolo_model_path")
                if yolo_path:
                    self._yolo_model_path = yolo_path
                    self._yolo_net = None
                    print("[切换] 方案%d 已加载YOLO路径: %s" % (route_id, os.path.basename(yolo_path)))
                # 加载绿框配置
                bb = cd.get("blue_box")
                if bb and bb.get("width", 0) > 0:
                    self._blue_box = bb
                    print("[切换] 方案%d 已加载绿框 %dx%d" % (route_id, bb["width"], bb["height"]))
                else:
                    self._blue_box = None
            except Exception as e:
                print("[切换] 方案配置加载失败:", e)
        self._save_plans()
        plan, mp = self._find_plan(num_to_plan_id(route_id))
        pname = plan["name"] if plan else str(route_id)
        mname = mp["name"] if mp else "?"
        print("[切换] %s/%s: %d 平台, %d 梯子" % (mname, pname, len(self.platforms), len(self.ladders)))

    def _clear_route_file(self, route_id):
        """清除指定方案：删除文件，若为当前方案则清空内存"""
        pf_file, ld_file = route_files(route_id)
        calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % route_id)
        for f in (pf_file, ld_file, calib_file):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
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
        """返回当前下拉菜单的菜单项列表（仅mode下拉保留）"""
        if self._dropdown == "mode":
            return ["手动", "随机"]
        return []

    # ===== 方案系统独立窗口 =====

    def _ensure_tk_root(self):
        import tkinter as tk
        if not hasattr(self, '_tk_root') or self._tk_root is None:
            try:
                self._tk_root = tk.Tk()
                self._tk_root.withdraw()
                _debug_log("[方案窗口] tk root创建成功")
            except Exception as e:
                _debug_log("[方案窗口] tk root创建失败: %s" % e)
                return False
        return True

    def _position_window(self, win, w, h):
        """把tk窗口定位在OpenCV窗口上方居中"""
        try:
            import win32gui
            hwnd = win32gui.FindWindow(None, "PLAY AND HAPPY")
            if hwnd:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                cx = left + (right - left) // 2
                cy = top + max(0, (bottom - top) // 2 - h // 2)
                win.geometry("%dx%d+%d+%d" % (w, h, cx - w // 2, cy))
                return
        except Exception:
            pass
        # 兜底：屏幕居中
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 2))

    def _show_msg(self, kind, title, message, parent=None):
        """固定位置确认框：无标题栏，锁定在脚本窗口中心，不能拖动"""
        import tkinter as tk
        dlg = tk.Toplevel(self._tk_root)
        dlg.overrideredirect(True)  # 去掉标题栏，不能拖动
        dlg.attributes("-topmost", True)
        dlg.grab_set()
        # 计算尺寸
        lines = message.split("\n")
        w = max(280, min(450, max(len(l) * 15 for l in lines) + 80))
        h = 110 + len(lines) * 22
        # 定位到脚本窗口中心
        try:
            import win32gui
            hwnd = win32gui.FindWindow(None, "PLAY AND HAPPY")
            if hwnd:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                cx = left + (right - left) // 2
                cy = top + (bottom - top) // 2
                dlg.geometry("%dx%d+%d+%d" % (w, h, cx - w // 2, cy - h // 2))
            else:
                dlg.geometry("%dx%d" % (w, h))
        except Exception:
            dlg.geometry("%dx%d" % (w, h))
        # 边框和背景
        dlg.configure(bg="#404040")
        outer = tk.Frame(dlg, bg="#606060", bd=1)
        outer.pack(fill="both", expand=True, padx=1, pady=1)
        inner = tk.Frame(outer, bg="#404040")
        inner.pack(fill="both", expand=True)
        # 标题
        tk.Label(inner, text=title, font=("微软雅黑", 10, "bold"), bg="#404040", fg="white").pack(pady=(10, 5))
        # 消息
        tk.Label(inner, text=message, font=("微软雅黑", 9), bg="#404040", fg="white", wraplength=w-60, justify="left").pack(pady=5, padx=20)
        # 按钮
        btn_frame = tk.Frame(inner, bg="#404040")
        btn_frame.pack(pady=10)
        result = {"val": None}
        def on_yes():
            result["val"] = True
            dlg.destroy()
        def on_no():
            result["val"] = False
            dlg.destroy()
        if kind == "yesno":
            tk.Button(btn_frame, text="是", width=8, command=on_yes, bg="#2E7D32", fg="white", relief="flat").pack(side="left", padx=15)
            tk.Button(btn_frame, text="否", width=8, command=on_no, bg="#757575", fg="white", relief="flat").pack(side="left", padx=15)
            dlg.bind("<Return>", lambda e: on_yes())
            dlg.bind("<Escape>", lambda e: on_no())
        else:
            tk.Button(btn_frame, text="确定", width=8, command=on_yes, bg="#2E7D32", fg="white", relief="flat").pack(side="left", padx=15)
            dlg.bind("<Return>", lambda e: on_yes())
            dlg.bind("<Escape>", lambda e: on_yes())
        dlg.wait_window()
        return result["val"]

    def _open_save_window(self):
        """打开保存方案窗口：有地图则列表选择，无地图则输入新地图名"""
        import tkinter as tk
        from tkinter import messagebox
        print('[怪物特征弹窗] 步骤1: 开始创建弹窗')
        if not self._ensure_tk_root():
            print('[怪物特征弹窗] 步骤1失败: tk_root创建失败')
            return
        print('[怪物特征弹窗] 步骤2: tk_root已就绪')
        if self._save_window is not None:
            try:
                self._save_window.destroy()
            except Exception:
                pass
            self._save_window = None
        try:
            win = tk.Toplevel(self._tk_root)
        except Exception as e:
            _debug_log("[方案窗口] Toplevel创建失败: %s" % e)
            return
        self._save_window = win
        _debug_log("[方案窗口] 保存窗口已创建")
        win.title("保存方案")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_window("_save_window"))

        maps = self.plans_data.get("maps", [])
        if not maps:
            win.geometry("280x200")
            self._position_window(win, 280, 200)
            # 没有地图：显示输入框
            tk.Label(win, text="请输入当前地图名", font=("微软雅黑", 12)).pack(pady=(20, 10))
            entry = tk.Entry(win, font=("微软雅黑", 12), width=20, bg="black", fg="white",
                             insertbackground="white", relief="solid", bd=1)
            entry.pack(pady=5)
            entry.focus_set()

            def do_save():
                name = entry.get().strip()
                if not name:
                    self._show_msg("warning", "提示", "请输入地图名")
                    return
                plan = self._create_plan(name)
                if plan is None:
                    self._show_msg("warning", "提示", "地图或方案数量已满")
                    return
                self._save_to_route(plan_id_to_num(plan["id"]))
                self._show_msg("info", "成功", "已保存到地图「%s」的「%s」" % (name, plan["name"]), parent=win)
                self._close_window("_save_window")

            btn_frame = tk.Frame(win)
            btn_frame.pack(pady=20)
            tk.Button(btn_frame, text="保存", width=8, command=do_save).pack(side="left", padx=10)
            tk.Button(btn_frame, text="取消", width=8, command=lambda: self._close_window("_save_window")).pack(side="left", padx=10)
            win.update()
        else:
            # 有地图：单击选中 + 保存按钮
            win.geometry("280x380")
            self._position_window(win, 280, 380)
            tk.Label(win, text="选择地图后点保存", font=("微软雅黑", 11)).pack(pady=(10, 5))
            list_frame = tk.Frame(win)
            list_frame.pack(fill="both", expand=True, padx=10, pady=5)
            scrollbar = tk.Scrollbar(list_frame)
            scrollbar.pack(side="right", fill="y")
            listbox = tk.Listbox(list_frame, font=("微软雅黑", 11), yscrollcommand=scrollbar.set,
                                 selectbackground="#FFD700", selectforeground="black", height=12,
                                 exportselection=False)
            for mp in maps:
                listbox.insert("end", "%s (%d个方案)" % (mp["name"], len(mp["plans"])))
            listbox.pack(side="left", fill="both", expand=True)
            scrollbar.config(command=listbox.yview)

            def do_save_to_map():
                sel = listbox.curselection()
                if not sel:
                    self._show_msg("warning", "提示", "请先选择一个地图")
                    return
                mp = maps[sel[0]]
                if len(mp["plans"]) >= 10:
                    self._show_msg("warning", "提示", "「%s」方案数量已满（10个）" % mp["name"])
                    return
                plan = self._create_plan(mp["name"])
                if plan is None:
                    self._show_msg("warning", "提示", "方案数量已满")
                    return
                self._save_to_route(plan_id_to_num(plan["id"]))
                self._show_msg("info", "成功", "已保存到「%s」的「%s」" % (mp["name"], plan["name"]), parent=win)
                self._close_window("_save_window")

            # 底部按钮：保存 | 新地图 | 关闭
            btn_frame = tk.Frame(win)
            btn_frame.pack(pady=8)
            tk.Button(btn_frame, text="保存", width=7, command=do_save_to_map).pack(side="left", padx=5)
            tk.Button(btn_frame, text="新地图", width=7,
                      command=lambda: (self._close_window("_save_window"), self._show_new_map_input())).pack(side="left", padx=5)
            tk.Button(btn_frame, text="关闭", width=7, command=lambda: self._close_window("_save_window")).pack(side="left", padx=5)
            win.update()

    def _show_new_map_input(self):
        """显示新地图输入窗口（从保存窗口点'新地图'进入）"""
        import tkinter as tk
        from tkinter import messagebox
        win = tk.Toplevel(self._tk_root)
        self._save_window = win
        win.title("新地图")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        self._position_window(win, 280, 160)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_window("_save_window"))
        tk.Label(win, text="请输入当前地图名", font=("微软雅黑", 12)).pack(pady=(20, 10))
        entry = tk.Entry(win, font=("微软雅黑", 12), width=20, bg="black", fg="white",
                         insertbackground="white", relief="solid", bd=1)
        entry.pack(pady=5)
        entry.focus_set()

        def do_save():
            name = entry.get().strip()
            if not name:
                self._show_msg("warning", "提示", "请输入地图名")
                return
            if self._find_map(name):
                self._show_msg("warning", "提示", "地图名已存在")
                return
            plan = self._create_plan(name)
            if plan is None:
                self._show_msg("warning", "提示", "数量已满")
                return
            self._save_to_route(plan_id_to_num(plan["id"]))
            self._show_msg("info", "成功", "已保存到地图「%s」" % name)
            self._close_window("_save_window")

        btn_frame = tk.Frame(win)
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="保存", width=8, command=do_save).pack(side="left", padx=10)
        tk.Button(btn_frame, text="取消", width=8, command=lambda: self._close_window("_save_window")).pack(side="left", padx=10)
        win.update()

    def _open_plan_window(self):
        """打开方案管理窗口：按地图分组，单击激活/双击改名/勾选多选"""
        import tkinter as tk
        from tkinter import messagebox
        if not self._ensure_tk_root():
            return
        if self._plan_window is not None:
            try:
                self._plan_window.destroy()
            except Exception:
                pass
            self._plan_window = None
        win = tk.Toplevel(self._tk_root)
        self._plan_window = win
        win.title("方案管理")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_window("_plan_window"))
        self._position_window(win, 320, 460)

        # 滚动区域
        canvas = tk.Canvas(win, highlightthickness=0)
        scrollbar = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        scrollbar.pack(side="right", fill="y")
        # 鼠标滚轮
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)

        current_id = self.plans_data.get("current_id", "")
        self._plan_check_vars = {}  # plan_id -> BooleanVar
        self._plan_row_widgets = {}  # plan_id -> (row, name_lbl, chk)

        for mp in self.plans_data.get("maps", []):
            # 地图名标题行（灰色底，双击改名）
            map_frame = tk.Frame(scroll_frame, bg="#C0C0C0")
            map_frame.pack(fill="x", pady=(8, 0))
            map_label = tk.Label(map_frame, text=mp["name"], font=("微软雅黑", 10, "bold"),
                                 bg="#C0C0C0", fg="black", anchor="w")
            map_label.pack(side="left", fill="x", expand=True, padx=5, pady=3)

            def make_map_rename(mname, lbl):
                def on_double(event):
                    entry = tk.Entry(lbl.master, font=("微软雅黑", 10), bg="black", fg="white",
                                     insertbackground="white")
                    entry.insert(0, mname)
                    entry.select_range(0, "end")
                    entry.focus_set()
                    lbl.pack_forget()
                    entry.pack(side="left", fill="x", expand=True, padx=5, pady=3)
                    def confirm(event=None):
                        new_name = entry.get().strip()
                        if new_name and new_name != mname and not self._find_map(new_name):
                            self._rename_map(mname, new_name)
                        entry.destroy()
                        lbl.config(text=new_name if new_name else mname)
                        lbl.pack(side="left", fill="x", expand=True, padx=5, pady=3)
                    entry.bind("<Return>", confirm)
                    entry.bind("<FocusOut>", confirm)
                return on_double
            map_label.bind("<Double-Button-1>", make_map_rename(mp["name"], map_label))

            # 方案列表
            for plan in mp["plans"]:
                pid = plan["id"]
                row = tk.Frame(scroll_frame)
                row.pack(fill="x")
                is_current = (pid == current_id)
                bg = "#FFD700" if is_current else "white"
                var = tk.BooleanVar(value=plan.get("selected", False))
                self._plan_check_vars[pid] = var

                def make_toggle(p):
                    def toggle():
                        self._set_plan_selected(p, self._plan_check_vars[p].get())
                    return toggle
                chk = tk.Checkbutton(row, variable=var, command=make_toggle(pid), bg=bg)
                chk.pack(side="left")

                name_lbl = tk.Label(row, text=plan["name"], font=("微软雅黑", 10),
                                    bg=bg, fg="black", anchor="w")
                name_lbl.pack(side="left", fill="x", expand=True, pady=2)
                self._plan_row_widgets[pid] = (row, name_lbl, chk)

                def make_activate(pid_):
                    def on_click(event):
                        self._switch_route(plan_id_to_num(pid_))
                        # 不关闭窗口，直接更新所有行颜色
                        for rid, (rrow, rlbl, rchk) in self._plan_row_widgets.items():
                            c = "#FFD700" if rid == pid_ else "white"
                            rrow.config(bg=c)
                            rlbl.config(bg=c)
                            rchk.config(bg=c)
                    return on_click
                for w in (name_lbl, row):
                    w.bind("<Button-1>", make_activate(pid))

                def make_rename(pid_, lbl):
                    def on_double(event):
                        entry = tk.Entry(lbl.master, font=("微软雅黑", 10), bg="black", fg="white",
                                         insertbackground="white")
                        old_name = lbl.cget("text")
                        entry.insert(0, old_name)
                        entry.select_range(0, "end")
                        entry.focus_set()
                        lbl.pack_forget()
                        entry.pack(side="left", fill="x", expand=True, pady=2)
                        def confirm(event=None):
                            new_name = entry.get().strip()
                            if new_name:
                                self._rename_plan(pid_, new_name)
                            entry.destroy()
                            lbl.config(text=new_name if new_name else old_name)
                            lbl.pack(side="left", fill="x", expand=True, pady=2)
                        entry.bind("<Return>", confirm)
                        entry.bind("<FocusOut>", confirm)
                    return on_double
                name_lbl.bind("<Double-Button-1>", make_rename(pid, name_lbl))


        # 关闭按钮
        tk.Button(win, text="关闭", width=10, command=lambda: self._close_window("_plan_window")).pack(pady=8)
        win.update()


    def _open_char_feature_window(self):
        """打开人物特征管理弹窗：左右分栏，左边特征列表(含偏移X/Y)，右边操作区"""
        import tkinter as tk
        from tkinter import messagebox
        if not self._ensure_tk_root():
            return
        if getattr(self, '_char_feature_window', None) is not None:
            try:
                self._char_feature_window.destroy()
            except Exception:
                pass
            self._char_feature_window = None
        win = tk.Toplevel(self._tk_root)
        self._char_feature_window = win
        win.title("人物特征管理")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        def _on_char_win_close():
            """X关闭：恢复原始偏移值，取消所有防抖定时器"""
            for _tid, _after_id in list(_char_offset_timers.items()):
                try:
                    win.after_cancel(_after_id)
                except Exception:
                    pass
            _char_offset_timers.clear()
            for _t in self._char_templates:
                if _t["id"] in _char_orig_offsets:
                    _ox, _oy = _char_orig_offsets[_t["id"]]
                    _t["offset_x"] = _ox
                    _t["offset_y"] = _oy
            self._close_window("_char_feature_window")
        win.protocol("WM_DELETE_WINDOW", _on_char_win_close)
        self._position_window(win, 520, 420)

        # === 左边：特征列表（滚动区域）===
        left_frame = tk.Frame(win, width=340, height=380)
        left_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        left_frame.pack_propagate(False)

        tk.Label(left_frame, text="特征列表（每个特征独立偏移到人物脚）", font=("微软雅黑", 9, "bold")).pack(anchor="w")

        # 滚动区域
        canvas = tk.Canvas(left_frame, highlightthickness=0)
        scrollbar = tk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # 保存输入框引用，关闭时读取
        self._char_offset_entries = {}  # tpl_id -> (entry_x, entry_y)
        _char_orig_offsets = {}  # 原始偏移值，X关闭时恢复 {tpl_id: (ox, oy)}
        _char_offset_timers = {}  # 防抖定时器 {tpl_id: after_id}
        for _t in self._char_templates:
            _char_orig_offsets[_t["id"]] = (_t.get("offset_x", 0), _t.get("offset_y", 0))

        def _apply_char_offset(tid):
            """防抖到期后应用偏移值"""
            if tid not in self._char_offset_entries:
                return
            ex, ey = self._char_offset_entries[tid]
            try:
                ox = int(ex.get() or "0")
                oy = int(ey.get() or "0")
            except ValueError:
                ox, oy = 0, 0
            for _t in self._char_templates:
                if _t["id"] == tid:
                    _t["offset_x"] = ox
                    _t["offset_y"] = oy
                    break
            _char_offset_timers.pop(tid, None)

        def _on_char_offset_key(tid):
            """偏移输入框按键事件：2秒防抖后生效"""
            if tid in _char_offset_timers:
                win.after_cancel(_char_offset_timers[tid])
            _char_offset_timers[tid] = win.after(2000, lambda: _apply_char_offset(tid))

        def refresh_list():
            """刷新特征列表"""
            for w in scroll_frame.winfo_children():
                w.destroy()
            self._char_offset_entries.clear()
            if not self._char_templates:
                tk.Label(scroll_frame, text="暂无特征，点击右边'添加特征'按钮",
                         font=("微软雅黑", 9), fg="gray").pack(pady=20)
                return
            for idx, tpl in enumerate(self._char_templates):
                row = tk.Frame(scroll_frame, relief="solid", borderwidth=1)
                row.pack(fill="x", pady=2, padx=2)

                # 特征ID + 方向
                dir_text = "左" if tpl.get("direction", "right") == "left" else "右"
                dir_color = "#FF9800" if tpl.get("direction", "right") == "left" else "#2196F3"
                tk.Label(row, text="#%d" % tpl["id"], font=("微软雅黑", 9, "bold"),
                         width=3).pack(side="left")
                tk.Label(row, text=dir_text, font=("微软雅黑", 8, "bold"),
                         fg="white", bg=dir_color, width=2).pack(side="left", padx=2)

                # 偏移X
                tk.Label(row, text="X:", font=("微软雅黑", 9)).pack(side="left")
                entry_x = tk.Entry(row, width=5, font=("微软雅黑", 9))
                entry_x.insert(0, str(tpl.get("offset_x", 0)))
                entry_x.pack(side="left", padx=2)
                entry_x.bind("<KeyRelease>", lambda e, tid=tpl["id"]: _on_char_offset_key(tid))

                # 偏移Y
                tk.Label(row, text="Y:", font=("微软雅黑", 9)).pack(side="left")
                entry_y = tk.Entry(row, width=5, font=("微软雅黑", 9))
                entry_y.insert(0, str(tpl.get("offset_y", 0)))
                entry_y.pack(side="left", padx=2)
                entry_y.bind("<KeyRelease>", lambda e, tid=tpl["id"]: _on_char_offset_key(tid))

                self._char_offset_entries[tpl["id"]] = (entry_x, entry_y)

                # 尺寸显示
                tk.Label(row, text="%dx%d" % (tpl["width"], tpl["height"]),
                         font=("微软雅黑", 8), fg="gray").pack(side="left", padx=5)

                # 删除按钮
                def make_delete(tid):
                    def on_delete():
                        if messagebox.askyesno("确认", "删除特征#%d？" % tid):
                            for i, t in enumerate(self._char_templates):
                                if t["id"] == tid:
                                    self._delete_char_template(i)
                                    break
                            refresh_list()
                    return on_delete
                tk.Button(row, text="删", width=3, command=make_delete(tpl["id"]),
                          bg="#FF6666", fg="white").pack(side="right", padx=2)

        refresh_list()

        # === 右边：操作区 ===
        right_frame = tk.Frame(win, width=160, height=380)
        right_frame.pack(side="right", fill="y", padx=5, pady=5)
        right_frame.pack_propagate(False)

        def on_add(direction):
            # 先关闭弹窗，避免cv2.selectROI和tkinter冲突导致闪退
            try:
                win.withdraw()
            except:
                pass
            self._capture_character_feature(direction=direction)
            try:
                win.deiconify()
                win.lift()
            except:
                pass
            refresh_list()

        tk.Button(right_frame, text="添加向左特征", width=14, height=1,
                  command=lambda: on_add("left"), bg="#FF9800", fg="white").pack(pady=2)
        tk.Button(right_frame, text="添加向右特征", width=14, height=1,
                  command=lambda: on_add("right"), bg="#2196F3", fg="white").pack(pady=2)

        def on_clear_all():
            if messagebox.askyesno("确认", "清除全部特征？"):
                self._clear_character_features()
                refresh_list()
        tk.Button(right_frame, text="全部删除", width=14, height=2,
                  command=on_clear_all, bg="#FF6666", fg="white").pack(pady=5)

        def on_save_and_close():
            """保存所有偏移和方向并关闭"""
            for tid, (ex, ey) in self._char_offset_entries.items():
                try:
                    ox = int(ex.get() or "0")
                    oy = int(ey.get() or "0")
                except ValueError:
                    ox, oy = 0, 0
                for t in self._char_templates:
                    if t["id"] == tid:
                        t["offset_x"] = ox
                        t["offset_y"] = oy
                        break
            self._save_char_meta()
            self._add_log("人物特征偏移已保存")
            self._close_window("_char_feature_window")
        tk.Button(right_frame, text="保存并关闭", width=14, height=2,
                  command=on_save_and_close, bg="#2196F3", fg="white").pack(pady=5)

        # 说明
        info = tk.Label(right_frame, text='说明：\n左=人物向左走\n右=人物向右走\n每方向最多5个\n偏移=特征中心到脚\n匹配时自动选朝向',
                        font=('微软雅黑', 8), fg='gray', justify='left', wraplength=140)
        info.pack(pady=10, anchor="n")

        win.update()

    def _open_monster_feature_window(self):
        """打开怪物特征管理弹窗：左右分栏，左边特征列表(含偏移X/Y)，右边操作区
        怪物特征和YOLO检测合并显示小地图紫点"""
        import tkinter as tk
        from tkinter import messagebox
        if not self._ensure_tk_root():
            return
        if getattr(self, '_monster_feature_window', None) is not None:
            try:
                self._monster_feature_window.destroy()
            except Exception:
                pass
            self._monster_feature_window = None
        print('[怪物特征弹窗] 步骤3: 创建Toplevel窗口')
        win = tk.Toplevel(self._tk_root)
        self._monster_feature_window = win
        win.title("怪物特征管理")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        print('[怪物特征弹窗] 步骤4: 设置X关闭按钮回调')
        def on_close_monster_win():
            """关闭怪物特征弹窗（确保X按钮有效）：恢复原始偏移值，取消所有防抖定时器"""
            for _tid, _after_id in list(_monster_offset_timers.items()):
                try:
                    win.after_cancel(_after_id)
                except Exception:
                    pass
            _monster_offset_timers.clear()
            for _t in self._monster_templates:
                if _t["id"] in _monster_orig_offsets:
                    _ox, _oy = _monster_orig_offsets[_t["id"]]
                    _t["offset_x"] = _ox
                    _t["offset_y"] = _oy
            try:
                win.destroy()
            except Exception:
                pass
            self._monster_feature_window = None
        win.protocol("WM_DELETE_WINDOW", on_close_monster_win)
        print('[怪物特征弹窗] 步骤5: 定位窗口')
        self._position_window(win, 520, 420)
        print('[怪物特征弹窗] 步骤6: 创建左边特征列表')

        # === 左边：特征列表（滚动区域）===
        left_frame = tk.Frame(win, width=340, height=380)
        left_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        left_frame.pack_propagate(False)
        tk.Label(left_frame, text="怪物特征列表（每个特征独立偏移到怪物中心）", font=("微软雅黑", 9, "bold")).pack(anchor="w")

        canvas = tk.Canvas(left_frame, highlightthickness=0)
        scrollbar = tk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._monster_offset_entries = {}
        _monster_orig_offsets = {}  # 原始偏移值，X关闭时恢复 {tpl_id: (ox, oy)}
        _monster_offset_timers = {}  # 防抖定时器 {tpl_id: after_id}
        for _t in self._monster_templates:
            _monster_orig_offsets[_t["id"]] = (_t.get("offset_x", 0), _t.get("offset_y", 0))

        def _apply_monster_offset(tid):
            """防抖到期后应用偏移值"""
            if tid not in self._monster_offset_entries:
                return
            ex, ey = self._monster_offset_entries[tid]
            try:
                ox = int(ex.get() or "0")
                oy = int(ey.get() or "0")
            except ValueError:
                ox, oy = 0, 0
            for _t in self._monster_templates:
                if _t["id"] == tid:
                    _t["offset_x"] = ox
                    _t["offset_y"] = oy
                    break
            _monster_offset_timers.pop(tid, None)

        def _on_monster_offset_key(tid):
            """偏移输入框按键事件：2秒防抖后生效"""
            if tid in _monster_offset_timers:
                win.after_cancel(_monster_offset_timers[tid])
            _monster_offset_timers[tid] = win.after(2000, lambda: _apply_monster_offset(tid))

        def refresh_list():
            """刷新特征列表"""
            for w in scroll_frame.winfo_children():
                w.destroy()
            self._monster_offset_entries.clear()
            if not self._monster_templates:
                tk.Label(scroll_frame, text="暂无怪物特征，点击右边按钮添加",
                         font=("微软雅黑", 9), fg="gray").pack(pady=20)
                return
            for idx, tpl in enumerate(self._monster_templates):
                row = tk.Frame(scroll_frame, relief="solid", borderwidth=1)
                row.pack(fill="x", pady=2, padx=2)
                dir_text = "左" if tpl.get("direction", "right") == "left" else "右"
                dir_color = "#FF9800" if tpl.get("direction", "right") == "left" else "#2196F3"
                tk.Label(row, text="#%d" % tpl["id"], font=("微软雅黑", 9, "bold"), width=3).pack(side="left")
                tk.Label(row, text=dir_text, font=("微软雅黑", 8, "bold"), fg="white", bg=dir_color, width=2).pack(side="left", padx=2)
                tk.Label(row, text="X:", font=("微软雅黑", 9)).pack(side="left")
                entry_x = tk.Entry(row, width=5, font=("微软雅黑", 9))
                entry_x.insert(0, str(tpl.get("offset_x", 0)))
                entry_x.pack(side="left", padx=2)
                entry_x.bind("<KeyRelease>", lambda e, tid=tpl["id"]: _on_monster_offset_key(tid))
                tk.Label(row, text="Y:", font=("微软雅黑", 9)).pack(side="left")
                entry_y = tk.Entry(row, width=5, font=("微软雅黑", 9))
                entry_y.insert(0, str(tpl.get("offset_y", 0)))
                entry_y.pack(side="left", padx=2)
                entry_y.bind("<KeyRelease>", lambda e, tid=tpl["id"]: _on_monster_offset_key(tid))
                self._monster_offset_entries[tpl["id"]] = (entry_x, entry_y)
                tk.Label(row, text="%dx%d" % (tpl["width"], tpl["height"]), font=("微软雅黑", 8), fg="gray").pack(side="left", padx=5)
                def make_delete(tid):
                    def on_delete():
                        if messagebox.askyesno("确认", "删除怪物特征#%d？" % tid):
                            for i, t in enumerate(self._monster_templates):
                                if t["id"] == tid:
                                    self._delete_monster_template(i)
                                    break
                            refresh_list()
                    return on_delete
                tk.Button(row, text="删", width=3, command=make_delete(tpl["id"]), bg="#FF6666", fg="white").pack(side="right", padx=2)

        refresh_list()

        # === 右边：操作区 ===
        right_frame = tk.Frame(win, width=160, height=380)
        right_frame.pack(side="right", fill="y", padx=5, pady=5)
        right_frame.pack_propagate(False)

        def on_add(direction):
            try:
                win.withdraw()
            except:
                pass
            self._capture_monster_feature(direction=direction)
            try:
                win.deiconify()
                win.lift()
            except:
                pass
            refresh_list()

        tk.Button(right_frame, text="添加向左特征", width=14, height=1, command=lambda: on_add("left"), bg="#FF9800", fg="white").pack(pady=2)
        tk.Button(right_frame, text="添加向右特征", width=14, height=1, command=lambda: on_add("right"), bg="#2196F3", fg="white").pack(pady=2)

        def on_clear_all():
            if messagebox.askyesno("确认", "清除全部怪物特征？"):
                self._clear_monster_features()
                refresh_list()
        tk.Button(right_frame, text="全部删除", width=14, height=2, command=on_clear_all, bg="#FF6666", fg="white").pack(pady=5)

        def on_save_and_close():
            for tid, (ex, ey) in self._monster_offset_entries.items():
                try:
                    ox = int(ex.get() or "0")
                    oy = int(ey.get() or "0")
                except ValueError:
                    ox, oy = 0, 0
                for t in self._monster_templates:
                    if t["id"] == tid:
                        t["offset_x"] = ox
                        t["offset_y"] = oy
                        break
            self._save_monster_meta()
            self._add_log("怪物特征偏移已保存")
            self._close_window("_monster_feature_window")
        tk.Button(right_frame, text="保存并关闭", width=14, height=2, command=on_save_and_close, bg="#2196F3", fg="white").pack(pady=5)

        info = tk.Label(right_frame, text='说明：\n左=怪物朝左\n右=怪物朝右\n每方向最多5个\n偏移=特征中心到怪心和YOLO合并显示紫点', font=('微软雅黑', 8), fg='gray', justify='left', wraplength=140)
        info.pack(pady=10, anchor="n")

        print('[怪物特征弹窗] 步骤7: 弹窗创建完成')
        win.update()

    def _open_clear_window(self):
        """打开删除方案窗口：双击方案删方案，双击地图删地图（Listbox布局）"""
        import tkinter as tk
        from tkinter import messagebox
        if not self._ensure_tk_root():
            return
        if self._clear_window is not None:
            try:
                self._clear_window.destroy()
            except Exception:
                pass
            self._clear_window = None
        try:
            win = tk.Toplevel(self._tk_root)
        except Exception as e:
            _debug_log("[方案窗口] 清除窗口Toplevel失败: %s" % e)
            return
        self._clear_window = win
        _debug_log("[方案窗口] 清除窗口已创建")
        win.title("删除方案")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_window("_clear_window"))
        self._position_window(win, 300, 400)

        tk.Label(win, text="双击地图名删地图，双击方案删方案", font=("微软雅黑", 10)).pack(pady=(8, 4))

        list_frame = tk.Frame(win)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        listbox = tk.Listbox(list_frame, font=("微软雅黑", 10), yscrollcommand=scrollbar.set,
                             selectbackground="#FFD700", selectforeground="black", height=14)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)

        # 构建扁平列表：(类型, 名称, id)  类型: map/plan
        items = []
        for mp in self.plans_data.get("maps", []):
            items.append(("map", "[地图] " + mp["name"], mp["name"]))
            for plan in mp["plans"]:
                items.append(("plan", "    " + plan["name"], plan["id"]))
        for it in items:
            listbox.insert("end", it[1])

        def on_double(event):
            sel = listbox.curselection()
            if not sel:
                return
            itype, iname, iid = items[sel[0]]
            if itype == "map":
                if self._show_msg("yesno", "确认", "您确定要删除当前地图吗？\n删除后所属地图下的方案也会清空，请慎重！", parent=win):
                    self._delete_map(iid)
                    self._close_window("_clear_window")
                    self._open_clear_window()
            else:
                if self._show_msg("yesno", "确认", "您确定要删除此方案吗？", parent=win):
                    self._delete_plan(iid)
                    self._close_window("_clear_window")
                    self._open_clear_window()

        listbox.bind("<Double-Button-1>", on_double)
        tk.Button(win, text="关闭", width=10, command=lambda: self._close_window("_clear_window")).pack(pady=8)
        win.update()

    def _close_window(self, attr):
        """关闭指定窗口"""
        win = getattr(self, attr, None)
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
            setattr(self, attr, None)

    def _handle_dropdown_item(self, menu, item_idx):
        """处理下拉菜单项点击（仅mode下拉保留，save/route/clear_route改为独立窗口）"""
        if menu == "mode":
            self.route_mode = "手动" if item_idx == 0 else "随机"
            self._save_route_config()
            if self.route_mode == "随机":
                self._start_random()
            else:
                self._stop_random()
            print("[模式] 切换为: %s" % self.route_mode)

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
        # 重置增强逻辑状态
        self._route_reelect_time = 0
        self._idle_combat_start_pos = None
        self._idle_combat_attack_start = 0
        self._idle_combat_no_damage_duration = 0
        self._idle_combat_no_damage_logged = False
        self._idle_combat_last_turn = 0
        self._idle_combat_turn_interval = 0
        self._return_fail_count = 0
        self._return_attempt_mode = None
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
        """从勾选的方案中随机选一个（排除上一个避免连续重复）；没勾选返回None"""
        selected = self._get_selected_plans()
        available = []
        for p in selected:
            num = plan_id_to_num(p["id"])
            if self._route_has_file(num):
                available.append(num)
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

    def _play_alert(self, count=5):
        """播放报警音count次"""
        import threading
        alert_path = resource_path(os.path.join("data", "alert.mp3"))
        def _play():
            try:
                import pygame
                pygame.mixer.init()
                snd = pygame.mixer.Sound(alert_path)
                for _ in range(count):
                    snd.play()
                    while pygame.mixer.get_busy():
                        time.sleep(0.1)
                    time.sleep(0.2)
            except Exception:
                try:
                    import winsound
                    for _ in range(count):
                        winsound.PlaySound(alert_path, winsound.SND_FILENAME)
                        time.sleep(0.2)
                except Exception:
                    for _ in range(count):
                        winsound.Beep(800, 300)
                        time.sleep(0.2)
        threading.Thread(target=_play, daemon=True).start()

    def _random_enhanced_tick(self, player_pos):
        """随机模式增强：2-3分钟重选路线 + 原地打怪转身 + 被撞归位"""
        now = time.time()

        # === 1. 每2-3分钟重新随机选路线（仅随机模式+有勾选方案）===
        if self.route_mode == "随机" and self._get_selected_plans():
            if self._route_reelect_time == 0:
                # 首次设置重选计时器
                self._route_reelect_time = now + random.uniform(120, 180)
            elif now >= self._route_reelect_time:
                new_route = self._random_pick_route()
                if new_route and new_route != self.current_route:
                    print("[随机] 定时重选路线：方案%d" % new_route)
                    self._switch_route(new_route)
                    self._random_route_id = new_route
                    self._add_log("定时切换路线：方案%d" % new_route)
                self._route_reelect_time = now + random.uniform(120, 180)
        else:
            self._route_reelect_time = 0

        # === 2. 原地打怪模式（没勾选方案时）===
        selected = self._get_selected_plans()
        if self.route_mode == "随机" and not selected:
            if not self._idle_combat_no_damage_logged:
                self._idle_combat_no_damage_logged = True
                print("[随机] 未勾选任何方案，原地打怪中")
                self._add_log("未勾选任何方案")

            # 记录起始位置
            if self._player_screen_pos and self._idle_combat_start_pos is None:
                self._idle_combat_start_pos = self._player_screen_pos
                self._idle_combat_attack_start = now

            # 2a. 防卡死转身：统计无伤害时长，T±5秒随机转身
            if self._combat_locked_target and self._idle_combat_attack_start > 0:
                tx, ty = self._combat_locked_target
                has_damage = self._detect_damage_number(tx, ty)
                if has_damage:
                    # 有伤害，重置攻击计时
                    self._idle_combat_attack_start = now
                    self._idle_combat_no_damage_duration = 0
                else:
                    # 无伤害，累计时长
                    attack_duration = now - self._idle_combat_attack_start
                    if self._idle_combat_no_damage_duration == 0 and attack_duration > 10:
                        # 第一次检测到持续10秒无伤害，记录T
                        self._idle_combat_no_damage_duration = attack_duration
                        self._idle_combat_turn_interval = random.uniform(
                            max(10, attack_duration - 5), attack_duration + 5)
                        self._idle_combat_last_turn = now
                        print("[转身] 首次无伤害T=%.0f秒，转身间隔=%.0f秒" % (
                            attack_duration, self._idle_combat_turn_interval))
                    elif self._idle_combat_no_damage_duration > 0:
                        # 已记录T，按间隔转身
                        if now - self._idle_combat_last_turn >= self._idle_combat_turn_interval:
                            self._do_human_turn()
                            self._idle_combat_last_turn = now
                            self._idle_combat_turn_interval = random.uniform(
                                max(10, self._idle_combat_no_damage_duration - 5),
                                self._idle_combat_no_damage_duration + 5)

            # 2b. 被怪碰撞归位（±150px）
            if self._player_screen_pos and self._idle_combat_start_pos:
                sx, sy = self._idle_combat_start_pos
                cx, cy = self._player_screen_pos
                dx = cx - sx
                dy = cy - sy
                if abs(dx) > 150 or abs(dy) > 150:
                    self._do_return_to_start(sx, sy)
        else:
            # 有方案时重置原地打怪状态
            self._idle_combat_start_pos = None
            self._idle_combat_attack_start = 0
            self._idle_combat_no_damage_duration = 0
            self._idle_combat_no_damage_logged = False
            self._return_fail_count = 0
            self._return_attempt_mode = None

    def _do_human_turn(self):
        """人性化转身：短按反方向键再转回来"""
        facing = getattr(self, '_combat_facing', 0)
        if facing == 0:
            # 朝向未知，随机转一下
            vk = random.choice([0x25, 0x27])
        else:
            # 按反方向
            vk = 0x25 if facing > 0 else 0x27
        scan = user32.MapVirtualKeyW(vk, 0)
        ext = 0x0001
        user32.keybd_event(vk, scan, ext, 0)
        time.sleep(random.uniform(0.08, 0.15))
        user32.keybd_event(vk, scan, ext | 0x0002, 0)
        # 等一下再按回原方向
        time.sleep(random.uniform(0.1, 0.2))
        back_vk = 0x27 if vk == 0x25 else 0x25
        scan2 = user32.MapVirtualKeyW(back_vk, 0)
        user32.keybd_event(back_vk, scan2, ext, 0)
        time.sleep(random.uniform(0.08, 0.15))
        user32.keybd_event(back_vk, scan2, ext | 0x0002, 0)
        print("[转身] 完成人性化转身")

    def _do_return_to_start(self, target_x, target_y):
        """归位到起始位置：跳3次→梯子→平台→暂停报警"""
        if not self._player_screen_pos:
            return
        cx, cy = self._player_screen_pos
        dx = target_x - cx
        dy = target_y - cy

        # 释放战斗移动
        self._release_combat_move()

        if self._return_attempt_mode is None:
            self._return_attempt_mode = 'jump'
            self._return_fail_count = 0
            print("[归位] 偏移(%.0f,%.0f)超150px，开始归位" % (dx, dy))

        if self._return_attempt_mode == 'jump':
            # 尝试跳3次，每次跳完检测X变化
            old_x = cx
            self._jump_once()
            time.sleep(0.5)
            if self._player_screen_pos:
                new_x = self._player_screen_pos[0]
                if abs(new_x - target_x) < 150:
                    print("[归位] 跳跃归位成功")
                    self._return_attempt_mode = None
                    self._return_fail_count = 0
                    return
                if abs(new_x - old_x) < 5:
                    self._return_fail_count += 1
                else:
                    self._return_fail_count = 0  # 有进展重置
            else:
                self._return_fail_count += 1
            if self._return_fail_count >= 3:
                self._return_attempt_mode = 'ladder'
                self._return_fail_count = 0
                print("[归位] 跳跃失败，尝试梯子")

        elif self._return_attempt_mode == 'ladder':
            # 检测身边是否有梯子
            ladder_found = self._try_ladder_return(target_x, target_y)
            if ladder_found:
                print("[归位] 梯子归位成功")
                self._return_attempt_mode = None
                self._return_fail_count = 0
                return
            self._return_fail_count += 1
            if self._return_fail_count >= 3:
                self._return_attempt_mode = 'platform'
                self._return_fail_count = 0
                print("[归位] 梯子失败，尝试平台路线")

        elif self._return_attempt_mode == 'platform':
            # 检测绿色平台线是否能直达
            platform_found = self._try_platform_return(target_x, target_y)
            if platform_found:
                print("[归位] 平台路线归位成功")
                self._return_attempt_mode = None
                self._return_fail_count = 0
                return
            self._return_fail_count += 1
            if self._return_fail_count >= 3:
                # 全部失败，暂停脚本+报警
                print("[归位] 归位失败，暂停脚本并报警")
                self._add_log("归位失败，脚本已暂停")
                self._stop_random()
                self._play_alert(5)
                self._return_attempt_mode = None
                self._return_fail_count = 0

    def _jump_once(self):
        """跳一次（短按跳跃键）"""
        # 尝试常见跳跃键：Alt
        vk = 0x12  # VK_MENU = Alt
        scan = user32.MapVirtualKeyW(vk, 0)
        ext = 0x0001
        user32.keybd_event(vk, scan, ext, 0)
        time.sleep(0.08)
        user32.keybd_event(vk, scan, ext | 0x0002, 0)

    def _try_ladder_return(self, target_x, target_y):
        """尝试通过梯子归位，返回True/False"""
        if not self.ladders or not self._player_screen_pos:
            return False
        cx, cy = self._player_screen_pos
        # 找身边最近的梯子（屏幕距离100px内）
        best = None
        best_dist = 100
        for ld in self.ladders:
            lx = ld.get("x", 0)
            dist = abs(lx - cx)
            if dist < best_dist:
                best_dist = dist
                best = ld
        if best is None:
            return False
        # 往梯子方向移动
        dir_key = 0x27 if best["x"] > cx else 0x25
        scan = user32.MapVirtualKeyW(dir_key, 0)
        ext = 0x0001
        user32.keybd_event(dir_key, scan, ext, 0)
        time.sleep(0.3)
        user32.keybd_event(dir_key, scan, ext | 0x0002, 0)
        # 检查是否靠近目标
        if self._player_screen_pos:
            if abs(self._player_screen_pos[0] - target_x) < 150:
                return True
        return False

    def _try_platform_return(self, target_x, target_y):
        """尝试通过绿色平台线归位，返回True/False"""
        if not self.platforms or not self._player_screen_pos:
            return False
        cx, cy = self._player_screen_pos
        # 找当前所在平台，沿平台方向移动
        current_pf = self._get_current_manual_platform()
        if current_pf:
            pts = self._platform_points(current_pf)
            if pts:
                # 往目标方向移动
                dir_key = 0x27 if target_x > cx else 0x25
                scan = user32.MapVirtualKeyW(dir_key, 0)
                ext = 0x0001
                user32.keybd_event(dir_key, scan, ext, 0)
                time.sleep(0.3)
                user32.keybd_event(dir_key, scan, ext | 0x0002, 0)
                if self._player_screen_pos:
                    if abs(self._player_screen_pos[0] - target_x) < 150:
                        return True
        return False

    def _random_step(self, player_pos):
        """随机模式每帧状态机"""
        if not self._random_running:
            return

        # ===== 新增强逻辑（新系统也执行）=====
        self._random_enhanced_tick(player_pos)

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
        """截取游戏整个窗口画面（包括标题栏，和自动吃药等功能坐标一致）"""
        if self.hwnd is None or not self.window_rect or self.window_rect.get("width", 0) <= 0:
            return np.zeros((MAP_H, FIXED_W, 3), dtype=np.uint8)
        r = self.window_rect
        return np.array(self.sct.grab(r))[:, :, :3]

    def _capture_map(self):
        if self.hwnd is None or not self.window_rect or self.window_rect.get("width", 0) <= 0:
            return np.zeros((MAP_H, FIXED_W, 3), dtype=np.uint8)
        r = self.map_area_rect
        # 未截取小地图时map_area_rect为None，返回全黑图，不抛异常（否则主循环卡死第0帧）
        if not r or r.get("width", 0) <= 0 or r.get("height", 0) <= 0:
            return np.zeros((MAP_H, FIXED_W, 3), dtype=np.uint8)
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
        """【模块B】检测小地图上人物黄色光点（纯色识别：只认中心色 ffff88，加偏色±5，在小地图块内找唯一中心，取中心点）
        原理：人物光点中心颜色 = ffff88 (BGR 136,255,255)，加一点偏色容差, 在map_area(整个小地图块)内找该色像素, 取质心作为光点中心。
        返回：(x, y) 光点中心坐标；找不到返回None"""
        bgr = map_area  # BGR原图(小地图块)
        # 中心色 ffff88 = BGR(136,255,255)；加偏色±5 -> B 131~141
        mask = cv2.inRange(bgr, np.array([131, 250, 250]), np.array([141, 255, 255]))
        ys, xs = np.where(mask > 0)
        if len(xs) > 0:
            cx = int(xs.mean())  # 中心X(该色像素质心)
            cy = int(ys.mean())  # 中心Y
            if getattr(self, 'frame_count', 0) % 10 == 0:
                _debug_log("[光点检测] ffff88纯色定位 center=(%d,%d) 像素数=%d" % (cx, cy, len(xs)))
            self.last_player_pos = (cx, cy)  # 更新上次位置
            return (cx, cy)  # 返回光点中心
        self.last_player_pos = None  # 没找到，清空上次位置
        return None  # 返回None

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

    def _effective_scale(self):
        """【模块B】返回最终倍率(总值) = 检测值 + 手动偏移值。
        检测值：三点检测/手动记录写入的 _calibrated_scale_x/y；未检测时用默认值(0.10)。
        手动偏移：倍率差弹窗里用户输入的 scale_x_offset/scale_y_offset。
        总值一旦定下来就被锁定(见 _update_scale_calibration)，不再随人物走动变化。
        注意：换算用的scale不能为0(否则怪物坐标全换算到人物/崩)，未校准用0.10兜底。"""
        base_x = getattr(self, '_calibrated_scale_x', 0.10)
        base_y = getattr(self, '_calibrated_scale_y', 0.10)
        try:
            off_x = float(self._field_values.get("scale_x_offset", "0") or "0")
        except (ValueError, TypeError):
            off_x = 0.0
        try:
            off_y = float(self._field_values.get("scale_y_offset", "0") or "0")
        except (ValueError, TypeError):
            off_y = 0.0
        return (base_x + off_x, base_y + off_y)

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
        # X和Y用各自的最终scale = 定完点锁定的倍率 + 手动偏移（最终值）
        effective_sx, effective_sy = self._effective_scale()
        # 以人物为参考点，计算怪相对于人物的偏移，再转成小地图偏移
        map_x = pmap_x + (screen_x - pscr_x) * effective_sx
        map_y = pmap_y + (screen_y - pscr_y) * effective_sy
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
        # ===== 用户需求：总值(检测值+偏移)定下后就固定，绝不自动变。 =====
        # 检测值 _calibrated_scale_x/y 只能由「三点检测 / 手动记录」写入，且可被下次检测覆盖；
        # 偏移值 scale_x_offset/y_offset 只能手动调。这里禁止任何自动校准改动检测值。
        # 否则人物一走动，检测值被滑动平均改动，总值就会一直漂移。
        return
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
        cur_scr_y = self._player_screen_pos[1]
        cur_map_x = self._player_map_pos[0]
        cur_map_y = self._player_map_pos[1]
        # 初始化左右端点记录
        left_pt = getattr(self, '_calib_left_pt', None)
        right_pt = getattr(self, '_calib_right_pt', None)
        old_left = left_pt
        old_right = right_pt
        # 自动更新最左点（当前屏幕X比记录的更左）
        if left_pt is None or cur_scr_x < left_pt[0]:
            # 记录完整坐标：(屏幕X, 屏幕Y, 小地图X, 小地图Y)
            self._calib_left_pt = (cur_scr_x, cur_scr_y, cur_map_x, cur_map_y)
            left_pt = self._calib_left_pt
        # 自动更新最右点（当前屏幕X比记录的更右）
        if right_pt is None or cur_scr_x > right_pt[0]:
            # 记录完整坐标：(屏幕X, 屏幕Y, 小地图X, 小地图Y)
            self._calib_right_pt = (cur_scr_x, cur_scr_y, cur_map_x, cur_map_y)
            right_pt = self._calib_right_pt
        # 自动更新最高点（当前屏幕Y比记录的更小=更高）
        top_pt = getattr(self, '_calib_top_pt', None)
        old_top = top_pt
        if top_pt is None or cur_scr_y < top_pt[0]:
            self._calib_top_pt = (cur_scr_y, cur_map_y)
            top_pt = self._calib_top_pt
        # 左右都记录到后，计算scale_x
        if left_pt and right_pt and right_pt[0] > left_pt[0] + 50:
            # 屏幕X差>50px才计算（避免范围太小不准）
            dx_scr = right_pt[0] - left_pt[0]
            # 兼容旧格式：新格式小地图X在索引2，旧格式在索引1
            lx_map = left_pt[2] if len(left_pt) >= 4 else left_pt[1]
            rx_map = right_pt[2] if len(right_pt) >= 4 else right_pt[1]
            dx_map = rx_map - lx_map
            if dx_map > 1:
                scale_x = dx_map / dx_scr
                # 自动校准的scale_x权重50%（因为可能不是真正的平台两端）
                old_scale = getattr(self, '_calibrated_scale_x', 0.10)
                self._calibrated_scale_x = old_scale * 0.5 + scale_x * 0.5
                self._map_screen_scale = self._calibrated_scale_x
        # 端点有更新就自动保存到文件（永久保存，重启不丢失）
        if (old_left != self._calib_left_pt) or (old_right != self._calib_right_pt) or (old_top != self._calib_top_pt):
            self._save_calib()
            # 上端点或左端点变化时重新计算scale_y
            if old_top != self._calib_top_pt or old_left != self._calib_left_pt:
                self._recalc_scale_from_edges()

    def _manual_calibrate_left(self):
        """【模块B】手动记录左端点（人物停在平台最左端后点按钮）
        用途：精确记录平台左端，同时作为Y轴下端点
        原理：记录当前人物的屏幕(X,Y)和小地图(X,Y)作为左端点
        副作用：手动记录后关闭自动记录（避免自动记录覆盖手动值）"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._add_log("手动校准失败：未检测到人物位置")
            return
        # 记录完整坐标：(屏幕X, 屏幕Y, 小地图X, 小地图Y)
        self._calib_left_pt = (self._player_screen_pos[0], self._player_screen_pos[1],
                               self._player_map_pos[0], self._player_map_pos[1])
        self._manual_calib_done = True  # 标记手动校准已执行，关闭自动记录
        self._add_log("已记录左端点：屏幕(%d,%d) 小地图(%d,%d)" % (
            self._player_screen_pos[0], self._player_screen_pos[1],
            self._player_map_pos[0], self._player_map_pos[1]))
        self._save_calib()
        self._recalc_scale_from_edges()

    def _manual_calibrate_right(self):
        """【模块B】手动记录右端点（人物停在平台最右端后点按钮）
        用途：精确记录平台右端
        原理：记录当前人物的屏幕(X,Y)和小地图(X,Y)作为右端点
        副作用：手动记录后关闭自动记录（避免自动记录覆盖手动值）"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._add_log("手动校准失败：未检测到人物位置")
            return
        # 记录完整坐标：(屏幕X, 屏幕Y, 小地图X, 小地图Y)
        self._calib_right_pt = (self._player_screen_pos[0], self._player_screen_pos[1],
                                self._player_map_pos[0], self._player_map_pos[1])
        self._manual_calib_done = True  # 标记手动校准已执行，关闭自动记录
        self._add_log("已记录右端点：屏幕(%d,%d) 小地图(%d,%d)" % (
            self._player_screen_pos[0], self._player_screen_pos[1],
            self._player_map_pos[0], self._player_map_pos[1]))
        self._save_calib()
        self._recalc_scale_from_edges()

    def _manual_calibrate_top(self):
        """【模块B】手动记录上端点（人物爬到最高处后点按钮）
        用途：Y轴校准，配合左端点（Y下端点）算出scale_y
        原理：记录当前人物的屏幕Y和小地图Y作为上端点
        记录格式：(屏幕Y, 小地图Y)"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._add_log("手动校准失败：未检测到人物位置")
            return
        self._calib_top_pt = (self._player_screen_pos[1], self._player_map_pos[1])
        self._add_log("已记录上端点：屏幕Y=%d 小地图Y=%d" % (
            self._player_screen_pos[1], self._player_map_pos[1]))
        self._save_calib()
        self._recalc_scale_from_edges()

    def _calib_fail(self, msg):
        """【倍率新方案】某步记录失败：提示重试，连续失败3次退出整个校准流程"""
        self._auto_calib_retry += 1  # 失败次数+1
        self._add_log("%s（第%d次，请重试）" % (msg, self._auto_calib_retry))
        if self._auto_calib_retry >= 3:  # 连续3次失败
            self._add_log("连续失败3次，退出倍率校准")
            self._reset_calib_state()  # 清空校准状态
            self._auto_calib_stage = 0  # 回到空闲
            self._auto_calib_retry = 0  # 重置失败计数

    def _reset_calib_state(self):
        """【倍率新方案】清空所有校准相关数据/点位（当前校准结束时或失败退出时调用）"""
        self._auto_calib_base = None  # 基点
        self._auto_calib_green_map = None  # 绿点(红圈X)小地图坐标
        self._auto_calib_blue_map = None  # 蓝点(蓝圈Y)小地图坐标
        self._auto_calib_green_screen = None  # 绿点屏幕坐标
        self._auto_calib_blue_screen = None  # 蓝点屏幕坐标
        self._auto_calib_dragging = None  # 拖动状态
        self._calib_green_template = None  # 绿点背景模板
        self._calib_blue_template = None   # 蓝点背景模板
        self._calib_green_match_pos = None  # 绿点模板匹配位置
        self._calib_blue_match_pos = None   # 蓝点模板匹配位置
        self._auto_calib_green_offset = (400, 0)  # 复位X光圈在基点右方400（水平，可拖动调）
        self._auto_calib_blue_offset = (0, -400)  # 复位Y光圈在基点上方400（可拖动调）

    def _calib_finish_keep_dot(self):
        """【倍率新方案】完成时：清光圈(基点屏幕/光圈屏幕位置/模板/拖动)，同时清小地图红点(基点)/绿点/蓝点"""
        self._auto_calib_green_screen = None   # 清绿圈屏幕位置(光圈)
        self._auto_calib_blue_screen = None    # 清蓝圈屏幕位置(光圈)
        self._auto_calib_dragging = None       # 清拖动状态
        self._calib_green_template = None      # 清绿点模板(光圈识别用)
        self._calib_blue_template = None       # 清蓝点模板
        self._calib_green_match_pos = None     # 清绿点匹配位置(光圈)
        self._calib_blue_match_pos = None      # 清蓝点匹配位置
        # 【需求】第3次点完成后小地图红/绿/蓝点也全部消失，不留任何标记
        self._auto_calib_base = None           # 清基点(红点)
        self._auto_calib_green_map = None      # 清绿点
        self._auto_calib_blue_map = None       # 清蓝点

    def _start_auto_calibration(self, axis='X'):
        """【倍率新方案】分开取样：axis='X' 用绿圈只取X分量，axis='Y' 用蓝圈只取Y分量
        光圈流程：记基点→出光圈(绿/蓝)拖到独特位置→人物走到光圈→记录→算倍率
        每步引导文字(窗口最顶白区红字)；某步失败提示重试，连续失败3次退出整个流程"""
        if axis not in ('X', 'Y'):  # 非法方向直接忽略
            return
        self._auto_calib_axis = axis  # 当前校准方向
        _ax_label = "X" if axis == 'X' else "Y"  # 显示用方向名
        _ring = "绿" if axis == 'X' else "蓝"      # 光圈颜色名

        # 3次点击流程：第3次点直接完成(算倍率+清光圈保留红/绿点)，无第4次

        # 每次点记录：强制重新截取小地图+检测人物光点，确保最新准确坐标（不用缓存）
        try:
            _map_frame = self._capture_map()
            if _map_frame is not None:
                _detected = self.find_player_dot(_map_frame)
                if _detected:
                    self._player_map_pos = _detected
        except Exception:
            pass

        cur_sx = cur_sy = cur_mx = cur_my = 0
        # 未加载人物特征(模板0套)时，X/Y倍率无法定位人物屏幕位置，提示先添加人物特征
        if not getattr(self, '_char_templates', None):
            self._calib_fail("%s倍率：未添加人物特征，请先添加人物特征" % _ax_label)
            self._add_log("请先添加人物特征（框选角色），再点%s倍率" % _ax_label)
            return
        if self._auto_calib_stage in (0, 1):  # 第1/2步需要屏幕+小地图坐标
            if not self._player_map_pos or not self._player_screen_pos:
                self._calib_fail("%s倍率：未检测到人物位置" % _ax_label)
                return
            cur_sx, cur_sy = self._player_screen_pos[0], self._player_screen_pos[1]
            cur_mx, cur_my = self._player_map_pos[0], self._player_map_pos[1]
        elif self._auto_calib_stage == 2:  # 第3步只需小地图坐标
            if not self._player_map_pos:
                self._calib_fail("记录失败请重试")
                return
            cur_mx, cur_my = self._player_map_pos[0], self._player_map_pos[1]

        # 第1步：记基点 + 出光圈（X=绿圈，Y=蓝圈），默认偏移400可拖动
        if self._auto_calib_stage == 0:
            self._auto_calib_base = (cur_sx, cur_sy, cur_mx, cur_my)  # 记录基点(人物位置)
            if axis == 'X':
                self._auto_calib_green_offset = (400, 0)  # X光圈默认在基点右方400（水平，提供X分量，可拖动调）
            else:
                self._auto_calib_blue_offset = (0, -400)  # Y光圈默认在基点上方400（可拖动调）
            self._auto_calib_green_map = None  # 清空旧绿点
            self._auto_calib_blue_map = None   # 清空旧蓝点
            self._auto_calib_green_screen = None
            self._auto_calib_blue_screen = None
            self._auto_calib_dragging = None
            self._calib_green_template = None
            self._calib_blue_template = None
            self._calib_green_match_pos = None
            self._calib_blue_match_pos = None
            self._auto_calib_stage = 1
            self._add_log("请移动光圈到角色能够到达的位置并且相对固定的背景上")
            return

        # 第2步：定光圈屏幕位置（截图45x45模板，记忆文件坑5）
        if self._auto_calib_stage == 1:
            if axis == 'X':
                goff = self._auto_calib_green_offset
                self._auto_calib_green_screen = (cur_sx + goff[0], cur_sy + goff[1])
            else:
                boff = self._auto_calib_blue_offset
                self._auto_calib_blue_screen = (cur_sx + boff[0], cur_sy + boff[1])
            if self._overlay_hwnd:
                user32.ShowWindow(self._overlay_hwnd, 0)  # 隐藏蒙板避免截到圈本身
                time.sleep(0.1)
            if axis == 'X':
                _ok = self._capture_calib_template(self._auto_calib_green_screen, 'green')
            else:
                _ok = self._capture_calib_template(self._auto_calib_blue_screen, 'blue')
            time.sleep(0.1)
            if self._overlay_hwnd:
                user32.ShowWindow(self._overlay_hwnd, 5)  # 恢复蒙板显示
                time.sleep(0.05)
            if not _ok:  # 截图保存失败：提示重试，连续3次退出整个流程
                self._calib_fail("图片保存失败请重试")
                return
            self._auto_calib_stage = 2
            self._add_log("请移动角色到光圈位置")
            return

        # 第3次点：人物走到光圈，记录位置 → 算倍率 + 小地图红/绿点(保留) + 光圈消失 + 完成(3次点击结束)
        if self._auto_calib_stage == 2:
            if axis == 'X':
                self._auto_calib_green_map = (cur_mx, cur_my)  # 只取X点小地图坐标(绿点)
            else:
                self._auto_calib_blue_map = (cur_mx, cur_my)   # 只取Y点小地图坐标(蓝点)
            self._finish_auto_calibration()   # 直接算倍率(取X/Y分量)
            self._calib_finish_keep_dot()     # 清光圈(游戏画面圈消失)，保留红/绿点(小地图继续显示)
            self._auto_calib_stage = 0        # 回到空闲
            if axis == 'X':
                self._add_log("X点记录完成 请按【Y倍率】进行下一步")
            else:
                self._add_log("Y点记录完成")
            return

    def _finish_auto_calibration(self):
        """【倍率新方案】按 _auto_calib_axis 只算对应轴倍率（X用绿圈=右，Y用蓝圈=上），沿用记忆文件除以2"""
        axis = self._auto_calib_axis  # 当前校准方向
        if not self._auto_calib_base:  # 无基点
            self._calib_fail("倍率：无基点")
            return
        base_sx, base_sy, base_mx, base_my = self._auto_calib_base
        if axis == 'X':  # X倍率：用绿圈(右)
            if not self._auto_calib_green_map or not self._auto_calib_green_screen:
                self._calib_fail("X倍率：数据不完整")
                return
            gsx, gsy = self._auto_calib_green_screen  # 绿圈屏幕坐标
            gmx, gmy = self._auto_calib_green_map      # 绿圈小地图坐标
            dx_screen = gsx - base_sx  # 屏幕X位移（绿圈在基点右方为正）
            dx_map = gmx - base_mx      # 小地图X位移
            if dx_screen <= 0:
                self._calib_fail("X倍率：绿圈应在基点右方")
                return
            self._calibrated_scale_x = (dx_map / 2.0) / float(dx_screen)  # 除以2（记忆文件坑4）
            # 【护栏】倍率超出(0.01~100)说明屏幕/小地图位移异常(人物没走到光圈/光点检测跳飞)，
            # 判失败，避免算出 36555 这种垃圾值污染打怪逻辑
            if not (0.01 <= self._calibrated_scale_x <= 100.0):
                self._calib_fail("X倍率异常(%.4f)，请重试" % self._calibrated_scale_x)
                self._calibrated_scale_x = 0.10  # 回退默认，避免残留垃圾值
                return
            self._map_screen_scale = self._calibrated_scale_x  # 主scale兼容旧代码
            self._add_log("X倍率=%.4f (小地图%dpx/屏幕%dpx)" % (self._calibrated_scale_x, dx_map, dx_screen))
        elif axis == 'Y':  # Y倍率：用蓝圈(上)
            if not self._auto_calib_blue_map or not self._auto_calib_blue_screen:
                self._calib_fail("Y倍率：数据不完整")
                return
            bsx, bsy = self._auto_calib_blue_screen  # 蓝圈屏幕坐标
            bmx, bmy = self._auto_calib_blue_map      # 蓝圈小地图坐标
            dy_screen = base_sy - bsy  # 屏幕Y位移（蓝圈在基点上方为正）
            dy_map = base_my - bmy      # 小地图Y位移
            if dy_screen <= 0:
                self._calib_fail("Y倍率：蓝圈应在基点上方")
                return
            self._calibrated_scale_y = (dy_map / 2.0) / float(dy_screen)  # 除以2
            # 【护栏】Y倍率超出(0.01~100)判失败，避免垃圾值，与X一致
            if not (0.01 <= self._calibrated_scale_y <= 100.0):
                self._calib_fail("Y倍率异常(%.4f)，请重试" % self._calibrated_scale_y)
                self._calibrated_scale_y = 0.10  # 回退默认，避免残留垃圾值
                return
            self._add_log("Y倍率=%.4f (小地图%dpx/屏幕%dpx)" % (self._calibrated_scale_y, dy_map, dy_screen))
        else:
            return
        self._manual_calib_done = True  # 三点校准成功：锁定倍率，避免游戏中自动校准覆盖
        self._save_calib()  # 保存倍率到文件

    def _recalc_auto_calib_scale(self):
        """【模块B】蒙板拖动绿点蓝点后重新计算屏幕距离（仅更新屏幕坐标，倍率等人物走完再算）"""
        # 蒙板拖动只改变屏幕位置，小地图位置还没记录，所以这里不计算倍率
        pass

    def _capture_calib_template(self, screen_pos, color_tag):
        """【模块B】截取指定屏幕位置周围的背景图作为模板（用于模板匹配跟踪特色位置）
        参数：screen_pos=(屏幕X,屏幕Y)，color_tag='green'/'blue'
        返回：True成功，False失败"""
        try:
            frame = self._capture_window()
            if frame is None:
                return False
            h, w = frame.shape[:2]
            sx, sy = screen_pos
            half = self._calib_template_size // 2
            odd_offset = 1 if self._calib_template_size % 2 else 0  # 奇数尺寸+1确保完整（45→45x45，不是44x44）
            # 确保模板完整，靠近边缘自动内移（避免边界截断导致匹配失败）
            sx = max(half, min(w - half - odd_offset - 1, sx))
            sy = max(half, min(h - half - odd_offset - 1, sy))
            x1 = sx - half
            y1 = sy - half
            x2 = sx + half + odd_offset  # 奇数尺寸+1确保完整
            y2 = sy + half + odd_offset
            template = frame[y1:y2, x1:x2].copy()
            if color_tag == 'green':
                self._calib_green_template = template
            else:
                self._calib_blue_template = template
            _debug_log("[校准模板] %s截图成功 %dx%d at (%d,%d)" % (color_tag, template.shape[1], template.shape[0], sx, sy))
            return True
        except Exception as e:
            _debug_log("[校准模板] 截图失败: %s" % e)
            return False

    def _match_calib_templates(self):
        """【模块B】模板匹配：在当前游戏画面中搜索绿蓝模板的位置，更新匹配坐标
        仅在校准stage>=2时调用，每帧或每几帧调用一次"""
        if self._auto_calib_stage < 2:
            return
        if self._calib_green_template is None and self._calib_blue_template is None:
            return
        try:
            frame = self._capture_window()
            if frame is None:
                return
            # 匹配绿点模板
            if self._calib_green_template is not None:
                res = cv2.matchTemplate(frame, self._calib_green_template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= self._calib_match_threshold:
                    th, tw = self._calib_green_template.shape[:2]
                    self._calib_green_match_pos = (max_loc[0] + tw // 2, max_loc[1] + th // 2)
                else:
                    self._calib_green_match_pos = None
            # 匹配蓝点模板
            if self._calib_blue_template is not None:
                res = cv2.matchTemplate(frame, self._calib_blue_template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= self._calib_match_threshold:
                    th, tw = self._calib_blue_template.shape[:2]
                    self._calib_blue_match_pos = (max_loc[0] + tw // 2, max_loc[1] + th // 2)
                else:
                    self._calib_blue_match_pos = None
        except Exception as e:
            _debug_log("[校准模板匹配] 异常: %s" % e)

    def _save_calib(self):
        """保存端点数据和倍率到文件（左/右/上端点 + 校准倍率 + 人物特征 + YOLO路径 + 绿框）"""
        try:
            calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % self.current_route)
            # 人物特征转base64（只保留最后一次）
            char_b64 = None
            if self._char_templates:
                tpl = self._char_templates[-1]  # 取最后一张模板存base64(兼容旧方案文件)
                ok, buf = cv2.imencode(".png", tpl["img"])
                if ok:
                    char_b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            with open(calib_file, "w", encoding="utf-8") as f:
                json.dump({
                    "calib_left": self._calib_left_pt,
                    "calib_right": self._calib_right_pt,
                    "calib_top": getattr(self, '_calib_top_pt', None),
                    "calibrated_scale_x": getattr(self, '_calibrated_scale_x', 0),
                    "calibrated_scale_y": getattr(self, '_calibrated_scale_y', 0),
                    "char_template_b64": char_b64,
                    "yolo_model_path": getattr(self, '_yolo_model_path', None),
                    "blue_box": self._blue_box,
                }, f, indent=2)
        except Exception as e:
            print("[保存] 方案配置保存失败:", e)

    def _recalc_scale_from_region(self):
        """【模块B】根据小地图区域尺寸计算X/Y scale初始值（仅当从未检测/手动记录过时使用）
        原理：scale_x=FIXED_W/小地图宽度，scale_y=MAP_H/小地图高度
        X和Y缩放比率不同，必须分开算，不能默认相等
        用户需求：检测值定下后固定(总值=检测值+偏移)，可被再次检测/手动记录覆盖，但区域初始化只在无检测值时生效"""
        r = getattr(self, 'map_area_rect', None)
        # 已有检测值(非0) → 保留用户检测/手动记录值，不让区域初始化覆盖（否则总值会变）
        if getattr(self, '_calibrated_scale_x', 0) or getattr(self, '_calibrated_scale_y', 0):
            return
        if r and r["width"] > 0 and r["height"] > 0:
            self._calibrated_scale_x = FIXED_W / r["width"]
            self._calibrated_scale_y = MAP_H / r["height"]
            self._map_screen_scale = self._calibrated_scale_x
            print("[scale] 初始值: X=%.4f Y=%.4f (区域%dx%d)" % (
                self._calibrated_scale_x, self._calibrated_scale_y, r["width"], r["height"]))

    def _recalc_scale_from_edges(self):
        """【模块B】根据端点重新计算scale_x和scale_y（手动记录后调用）
        原理：scale_x = (右小地图X - 左小地图X) / (右屏幕X - 左屏幕X)
              scale_y = (上端点小地图Y - 左端点小地图Y) / (左端点屏幕Y - 上端点屏幕Y)
        记录格式：左/右端点=(屏幕X, 屏幕Y, 小地图X, 小地图Y)，上端点=(屏幕Y, 小地图Y)
        兼容旧格式：(屏幕X, 小地图X, 小地图Y)没有屏幕Y时跳过Y校准
        手动记录直接覆盖（100%权重）"""
        left_pt = getattr(self, '_calib_left_pt', None)
        right_pt = getattr(self, '_calib_right_pt', None)
        top_pt = getattr(self, '_calib_top_pt', None)
        # scale_x校准
        if left_pt and right_pt and right_pt[0] > left_pt[0]:
            dx_scr = right_pt[0] - left_pt[0]   # 屏幕X距离
            dx_map = right_pt[2] - left_pt[2] if len(left_pt) >= 4 else right_pt[1] - left_pt[1]  # 小地图X距离
            if dx_map > 0 and dx_scr > 0:
                scale_x = dx_map / dx_scr
                self._calibrated_scale_x = scale_x  # 手动记录直接覆盖（100%权重）
                self._map_screen_scale = scale_x
                # 清晰显示：屏幕距离、小地图距离、倍率
                self._add_log("X校准: 屏幕距离=%dpx, 小地图距离=%dpx, 倍率=%.4f" % (dx_scr, dx_map, scale_x))
        # scale_y校准：上端点 + 左端点（Y下端点）
        if top_pt and left_pt and len(left_pt) >= 4:
            dy_scr = left_pt[1] - top_pt[0]   # 屏幕Y距离（下端屏幕Y - 上端屏幕Y）
            dy_map = left_pt[3] - top_pt[1]   # 小地图Y距离（下端小地图Y - 上端小地图Y）
            if dy_scr > 10 and dy_map > 1:
                scale_y = dy_map / dy_scr
                self._calibrated_scale_y = scale_y
                # 清晰显示：屏幕距离、小地图距离、倍率
                self._add_log("Y校准: 屏幕距离=%dpx, 小地图距离=%dpx, 倍率=%.4f" % (dy_scr, dy_map, scale_y))

    def _get_monster_map_pos_verified(self, screen_x, screen_y):
        """【模块B】怪物屏幕坐标转小地图坐标（人物锚点+相对偏移，Y用同平台绿线校准）
        原理：
          X = 人物小地图X + (怪屏幕X - 人物屏幕X) * scale_x
          Y = 人物小地图Y + (怪屏幕Y - 人物屏幕Y) * scale_y
          绿线校准：只在怪物Y和人物Y相差<30px（同平台范围）时，才找X最接近的绿线点修正Y
          - 高处/低处平台的怪（Y差>30px）不强制拉到绿线上，保留线性转换Y
        参数：screen_x, screen_y = 怪物屏幕坐标（YOLO检测框的中心点X，底部Y）
        返回：(map_x, map_y) 小地图坐标；人物位置未知时返回None"""
        # 方法A：以人物为参考点线性转换
        pos_a = self._screen_to_map(screen_x, screen_y)
        if pos_a is None:
            return None
        map_x, map_y = pos_a
        # 绿线Y校准：只校准和人物Y相差<30px的怪（同平台），避免高处怪被拉到低层
        player_map_y = self._player_map_pos[1] if self._player_map_pos else None
        if player_map_y is not None and abs(map_y - player_map_y) < 30:
            best_y = None
            best_dx = 999
            for p in self.platforms:
                pts = self._platform_points(p)
                for (px, py) in pts:
                    dx = abs(px - map_x)
                    dy = abs(py - map_y)
                    # X最接近且Y偏差<15px（怪站在这个平台上）
                    if dx < best_dx and dy < 15:
                        best_dx = dx
                        best_y = py
            if best_y is not None:
                map_y = best_y
        return (map_x, map_y)

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
        for vk in [VK_F4, VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10, VK_F11, VK_F12]:
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
                _debug_log("[录制B] extract结果=%s 原始点数=%d platforms总数将=%d" % (str(np_), len(self.platform_points), len(self.platforms) + len(np_)))  # 调试日志：验证extract_platform是否返回非空结果
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
        elif vk == VK_F11:
            print("[热键] 倍率校准 (F11)")
            self._start_auto_calibration()
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

        # === 倍率差弹窗点击检测（优先检测，因为弹窗在最上层）===
        if self._show_scale_dialog and event == cv2.EVENT_LBUTTONDOWN:
            # 1. 优先检测右上角关闭按钮X（避免被标题栏拖拽覆盖）
            cx, cy, cw, ch = self._dlg_scale_close_btn
            if cx <= x < cx+cw and cy <= y < cy+ch:
                self._show_scale_dialog = False
                # 关闭时恢复原始值（不保存）
                if "scale_x_offset" in self._scale_dialog_backup:
                    self._field_values["scale_x_offset"] = self._scale_dialog_backup["scale_x_offset"]
                if "scale_y_offset" in self._scale_dialog_backup:
                    self._field_values["scale_y_offset"] = self._scale_dialog_backup["scale_y_offset"]
                self._focused_field = None
                print("[倍率差弹窗] 关闭（不保存）")
                return
            # 2. 检测标题栏拖拽（顶部50像素区域）
            dlg_x = self._scale_dialog_pos[0]
            dlg_y = self._scale_dialog_pos[1]
            dlg_w, dlg_h = 320, 220
            if dlg_x <= x < dlg_x+dlg_w and dlg_y <= y < dlg_y+50:
                self._scale_dialog_dragging = True
                self._scale_dialog_drag_offset = [x - dlg_x, y - dlg_y]
                print("[倍率差弹窗] 开始拖拽")
                return
            # 3. 检测X偏差输入框（点击整个输入框都能聚焦，不只是边框）
            sx_x, sx_y, sx_w, sx_h = self._dlg_scale_x_input
            if sx_x <= x < sx_x+sx_w and sx_y <= y < sx_y+sx_h:
                self._focused_field = "scale_x_offset"
                self._prev_num_states = set()  # 重置按键状态，避免旧状态残留导致新键被忽略
                self._num_field_replace = True
                self._last_input_change = time.time() * 1000  # 点击聚焦也算操作，重置5秒失焦计时器
                print("[倍率差弹窗] 聚焦X偏差输入框")
                return
            # 4. 检测Y偏差输入框
            sy_x, sy_y, sy_w, sy_h = self._dlg_scale_y_input
            if sy_x <= x < sy_x+sy_w and sy_y <= y < sy_y+sy_h:
                self._focused_field = "scale_y_offset"
                self._prev_num_states = set()  # 重置按键状态，避免旧状态残留导致新键被忽略
                self._num_field_replace = True
                self._last_input_change = time.time() * 1000  # 点击聚焦也算操作，重置5秒失焦计时器
                print("[倍率差弹窗] 聚焦Y偏差输入框")
                return
            # 5. 检测确认按钮
            ok_x, ok_y, ok_w, ok_h = self._dlg_scale_ok_btn
            if ok_x <= x < ok_x+ok_w and ok_y <= y < ok_y+ok_h:
                # 确认保存
                self._save_input_config()
                self._show_scale_dialog = False
                self._focused_field = None
                print("[倍率差弹窗] 确认保存")
                return
            # 6. 检测取消按钮
            cancel_x, cancel_y, cancel_w, cancel_h = self._dlg_scale_cancel_btn
            if cancel_x <= x < cancel_x+cancel_w and cancel_y <= y < cancel_y+cancel_h:
                # 取消，恢复原始值
                if "scale_x_offset" in self._scale_dialog_backup:
                    self._field_values["scale_x_offset"] = self._scale_dialog_backup["scale_x_offset"]
                if "scale_y_offset" in self._scale_dialog_backup:
                    self._field_values["scale_y_offset"] = self._scale_dialog_backup["scale_y_offset"]
                self._show_scale_dialog = False
                self._focused_field = None
                print("[倍率差弹窗] 取消（不保存）")
                return
            # 7. 点击弹窗外部，关闭弹窗（不保存）
            if not (dlg_x <= x < dlg_x+dlg_w and dlg_y <= y < dlg_y+dlg_h):
                if "scale_x_offset" in self._scale_dialog_backup:
                    self._field_values["scale_x_offset"] = self._scale_dialog_backup["scale_x_offset"]
                if "scale_y_offset" in self._scale_dialog_backup:
                    self._field_values["scale_y_offset"] = self._scale_dialog_backup["scale_y_offset"]
                self._show_scale_dialog = False
                self._focused_field = None
                print("[倍率差弹窗] 点击外部关闭（不保存）")
                return
        # 弹窗拖拽中（鼠标移动时更新位置）
        if self._show_scale_dialog and self._scale_dialog_dragging and event == cv2.EVENT_MOUSEMOVE:
            self._scale_dialog_pos[0] = x - self._scale_dialog_drag_offset[0]
            self._scale_dialog_pos[1] = y - self._scale_dialog_drag_offset[1]
            # 边界保护，不让弹窗拖出屏幕
            self._scale_dialog_pos[0] = max(0, min(UI_W - 320, self._scale_dialog_pos[0]))
            self._scale_dialog_pos[1] = max(0, min(UI_H - 220, self._scale_dialog_pos[1]))
            return
        # 松开鼠标时停止拖拽
        if self._scale_dialog_dragging and event == cv2.EVENT_LBUTTONUP:
            self._scale_dialog_dragging = False
            print("[倍率差弹窗] 停止拖拽")
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

        # 日志滚动条：拖拽+滚轮
        sb_x = UI_LOG_X + UI_LOG_W - 10
        sb_y = UI_LOG_Y + 22
        sb_w = 8
        sb_h = UI_LOG_H - 24
        line_h = 16
        max_lines = max(1, sb_h // line_h)
        total = len(self._runtime_logs)
        max_scroll = max(0, total - max_lines)

        def _clamp_scroll(v):
            return max(0, min(max_scroll, v))

        # 鼠标滚轮（在日志区域内滚动3行）
        if event == cv2.EVENT_MOUSEWHEEL:
            if UI_LOG_X <= x < UI_LOG_X + UI_LOG_W and UI_LOG_Y <= y < UI_LOG_Y + UI_LOG_H:
                if flags > 0:  # 向上滚
                    self._log_scroll = _clamp_scroll(self._log_scroll - 3)
                else:  # 向下滚
                    self._log_scroll = _clamp_scroll(self._log_scroll + 3)
                return

        # 点击滚动条：开始拖拽
        if event == cv2.EVENT_LBUTTONDOWN:
            if sb_x <= x < sb_x + sb_w and sb_y <= y < sb_y + sb_h:
                self._dragging_log_scroll = True
                # 直接跳到点击位置
                if max_scroll > 0 and sb_h > 0:
                    rel = (y - sb_y) / sb_h
                    self._log_scroll = _clamp_scroll(int(rel * max_scroll))
                return

        # 拖拽滚动条
        if event == cv2.EVENT_MOUSEMOVE and getattr(self, '_dragging_log_scroll', False):
            if max_scroll > 0 and sb_h > 0:
                rel = max(0.0, min(1.0, (y - sb_y) / sb_h))
                self._log_scroll = _clamp_scroll(int(rel * max_scroll))
            return

        # 松开拖拽
        if event == cv2.EVENT_LBUTTONUP and getattr(self, '_dragging_log_scroll', False):
            self._dragging_log_scroll = False
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
            dd_btn_map = {"mode": BTN_MODE}
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
                        BTN_RUN, BTN_STOP, BTN_CHAR, BTN_MONSTER, BTN_MONSTER_FEATURE,
                        BTN_CALIB_AUTO, BTN_CALIB_Y]  # X/Y倍率按钮也用统一圆角按压特效
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
        # 【模块B】自动校准按钮点击（同屏三点校准：基点+右800+上500）
        if _in(BTN_CALIB_AUTO, x, y):
            print("[鼠标] X倍率校准")
            self._calib_auto_pressed = 3  # 按下特效：显示3帧阴影
            self._start_auto_calibration('X')
            return
        if _in(BTN_CALIB_Y, x, y):
            print("[鼠标] Y倍率校准")
            self._calib_y_pressed = 3  # 按下特效：显示3帧阴影（与X倍率一致）
            self._start_auto_calibration('Y')
            return
        # 【倍率差弹窗】点击倍率差按钮打开弹窗
        if self._btn_scale_dialog and _in(self._btn_scale_dialog, x, y):
            print("[鼠标] 倍率差调整")
            self._show_scale_dialog = True
            # 打开弹窗时备份原始值（取消/关闭时恢复，确认才保存）
            self._scale_dialog_backup = {
                "scale_x_offset": self._field_values.get("scale_x_offset", "0"),
                "scale_y_offset": self._field_values.get("scale_y_offset", "0")
            }
            # 打开弹窗时立即计算所有控件位置（解决第一次打开弹窗点击没反应的问题）
            self._update_scale_dialog_positions()
            self._focused_field = None
            return

        # 5. 小地图区域内点击
        if UI_MAP_X <= x < UI_MAP_X + UI_MAP_W and UI_MAP_Y <= y < UI_MAP_Y + UI_MAP_H:
            # UI坐标转小地图原始分辨率坐标
            map_w = getattr(self, '_last_map_w', FIXED_W)
            map_h = getattr(self, '_last_map_h', MAP_H)
            map_x = int((x - UI_MAP_X) / UI_MAP_W * map_w)
            map_y = int((y - UI_MAP_Y) / UI_MAP_H * map_h)
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
            return
        if _in(BTN_PLATFORM, x, y):
            print("[鼠标] 平台"); self._handle_hotkey(VK_F5); return
        if _in(BTN_LADDER, x, y):
            print("[鼠标] 梯子"); self._handle_hotkey(VK_F6); return
        if _in(BTN_SAVE, x, y):
            self._dropdown = None
            _debug_log("[鼠标] 点击保存按钮")
            try:
                self._open_save_window()
            except Exception as e:
                _debug_log("[方案窗口] 保存窗口异常: %s" % e)
            return
        if _in(BTN_PLAN, x, y):
            self._dropdown = None
            _debug_log("[鼠标] 点击方案按钮")
            try:
                self._open_plan_window()
            except Exception as e:
                _debug_log("[方案窗口] 方案窗口异常: %s" % e)
            return

        # 6. 第二排按钮（清除平台/清除梯子/模式▼/清除方案▼）
        if _in(BTN_PLATFORM_CLR, x, y):
            self._pop_platform(); return
        if _in(BTN_LADDER_CLR, x, y):
            self._pop_ladder(); return
        if _in(BTN_MODE, x, y):
            self._dropdown = "mode" if self._dropdown != "mode" else None; return
        if _in(BTN_PLAN_CLR, x, y):
            self._dropdown = None
            _debug_log("[鼠标] 点击清除按钮")
            try:
                self._open_clear_window()
            except Exception as e:
                _debug_log("[方案窗口] 清除窗口异常: %s" % e)
            return

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

        # 8. 子标签页（人物特征弹窗/怪物数据）
        if _in(BTN_CHAR, x, y):
            self._open_char_feature_window()
            print("[鼠标] 打开人物特征管理弹窗")
            return
        if _in(BTN_MONSTER, x, y):
            _debug_log("[鼠标] 点击怪物数据按钮")
            print("[鼠标] 怪物数据 - 选择YOLO模型"); self._select_yolo_model(); return

        # 怪物特征按钮（打开怪物特征管理弹窗）
        if _in(BTN_MONSTER_FEATURE, x, y):
            _debug_log("[鼠标] 点击怪物特征按钮")
            print("[鼠标] 怪物特征管理")
            self._open_monster_feature_window()
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
        # 存储当前小地图原始尺寸，供鼠标拖动时坐标转换用
        self._last_map_w = w
        self._last_map_h = h
        # 【模块B】在小地图上画自动校准点（红点=基点小地图坐标，绿点=记录的绿点位置，蓝点=记录的蓝点位置）
        auto_base = getattr(self, '_auto_calib_base', None)
        auto_stage = getattr(self, '_auto_calib_stage', 0)
        auto_green = getattr(self, '_auto_calib_green_map', None)
        auto_blue = getattr(self, '_auto_calib_blue_map', None)
        # 圆点半径：按人物光点大小（原始小地图坐标下半径3，缩放后约7px，和游戏自带黄点差不多）
        CALIB_DOT_R = 1
        # 红点：基点的小地图坐标（第1次记录后显示，完成也保留）
        if auto_base and len(auto_base) >= 4:
            rx, ry = int(auto_base[2]), int(auto_base[3])
            if 0 <= rx < w and 0 <= ry < h:
                cv2.circle(display, (rx, ry), CALIB_DOT_R, (0, 0, 255), -1)  # 红色实心圆，基点位置
        # 绿点：记录绿点后显示（小地图绿点，完成也保留）
        if auto_green:
            gx, gy = int(auto_green[0]), int(auto_green[1])
            if 0 <= gx < w and 0 <= gy < h:
                cv2.circle(display, (gx, gy), CALIB_DOT_R, (0, 255, 0), -1)  # 绿色实心圆
        # 蓝点：记录蓝点后显示（小地图蓝点，完成也保留）
        if auto_blue:
            blx, bly = int(auto_blue[0]), int(auto_blue[1])
            if 0 <= blx < w and 0 <= bly < h:
                cv2.circle(display, (blx, bly), CALIB_DOT_R, (255, 0, 0), -1)  # 蓝色实心圆
        # 录制中的平台/梯子（红色）
        if self.recording_platform and len(self.platform_points) > 1:
            cv2.polylines(display, [np.array(self.platform_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        if self.recording_ladder and len(self.ladder_points) > 1:
            cv2.polylines(display, [np.array(self.ladder_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        # 动态计算放大倍数，确保每个地图都能完整显示在UI窗口中，最大2倍
        max_scale_x = (UI_W - 40) / float(w) if w > 0 else 2.0  # 左右各留20像素边距
        max_scale_y = (UI_H - 200) / float(h) if h > 0 else 2.0  # 上下留足够空间给按钮和底部
        MAP_SCALE = min(2.0, max_scale_x, max_scale_y)  # 最大2倍，确保完整显示
        render_w = int(w * MAP_SCALE)  # 渲染宽度=原始宽度×动态放大倍数
        render_h = int(h * MAP_SCALE)  # 渲染高度=原始高度×动态放大倍数
        map_display = cv2.resize(display, (render_w, render_h), interpolation=cv2.INTER_NEAREST)  # 按原始比率动态放大，确保完整显示

        # 【模块B】在缩放后的map_display上画怪物紫色点（半径6，清晰可见）
        scale_x = render_w / w if w > 0 else 1.0  # X缩放比例=渲染宽度/原始宽度
        scale_y = render_h / h if h > 0 else 1.0  # Y缩放比例=渲染高度/原始高度
        if self._monsters and self._player_map_pos and self._player_screen_pos:
            COLOR_MONSTER_MAP = (255, 0, 255)  # 紫色BGR
            for (x1, y1, x2, y2, score) in self._monsters:
                mcx = (x1 + x2) // 2
                mcy = y2
                mpos = self._get_monster_map_pos_verified(mcx, mcy)
                if mpos:
                    dx_s = int(mpos[0] * scale_x)
                    dy_s = int(mpos[1] * scale_y)
                    if 0 <= dx_s < render_w and 0 <= dy_s < render_h:  # 边界检查用实际渲染尺寸
                        cv2.circle(map_display, (dx_s, dy_s), 6, COLOR_MONSTER_MAP, -1)

        # 平台编号（缩放后画，红色白描边）
        for p in self.platforms:
            pts = self._platform_points(p)
            if len(pts) >= 2:
                pf_id = p.get('id', 0) + 1
                xs = [pt[0] for pt in pts]
                ys = [pt[1] for pt in pts]
                cx = int(sum(xs) / len(xs) * scale_x)
                cy_top = int(min(ys) * scale_y) - 8
                if 0 <= cx < render_w and 0 <= cy_top < render_h:  # 边界检查用实际渲染尺寸
                    cv2.putText(map_display, str(pf_id), (cx, cy_top),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 3, cv2.LINE_AA)
                    cv2.putText(map_display, str(pf_id), (cx, cy_top),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1, cv2.LINE_AA)

        # 梯子蓝线（在编号上方，缩放后画，线宽2）
        for l in self.ladders:
            lx = int(l["x"] * scale_x)
            ly1 = int(l["y_top"] * scale_y)
            ly2 = int(l["y_bottom"] * scale_y)
            lx = max(0, min(lx, render_w - 1))  # X边界检查用实际渲染宽度
            ly1 = max(0, min(ly1, render_h - 1))  # Y1边界检查用实际渲染高度
            ly2 = max(0, min(ly2, render_h - 1))  # Y2边界检查用实际渲染高度
            cv2.line(map_display, (lx, ly1), (lx, ly2), COLOR_LADDER, 2)

        # 平台绿线（最后画，始终在最上层，缩放后画，线宽1）
        if self.frame_count % 30 == 0:
            for _idx, _p in enumerate(self.platforms):
                _pts = self._platform_points(_p)
                _scaled = [(int(pt[0] * scale_x), int(pt[1] * scale_y)) for pt in _pts] if len(_pts) >= 2 else []
                _debug_log("[绘制C] 平台%d keys=%s pts=%s scaled=%s scale_x=%.3f scale_y=%.3f" % (_idx, list(_p.keys()), str(_pts), str(_scaled), scale_x, scale_y))  # 调试日志：每30帧输出平台坐标和缩放结果
        for p in self.platforms:
            pts = self._platform_points(p)
            if len(pts) >= 2:
                scaled_pts = [(int(pt[0] * scale_x), int(pt[1] * scale_y)) for pt in pts]
                cv2.polylines(map_display, [np.array(scaled_pts, np.int32).reshape(-1, 1, 2)],
                              False, COLOR_PLATFORM, 2)


        # 人物光点：只保留游戏自带的原始光点，不自己画（find_player_dot负责检测光点位置）

        # 光点锁定可视化框已移除（与校准/正常模式绿框重复，保留后者即可）
        # 随机模式运行状态（已被倍率显示替代）
        # if self._random_running:
        #     state_text = {"idle": "选方案中", "moving": "移动中", "attacking": "攻击中", "returning": "返回起点"}.get(self._random_state, self._random_state)
        #     progress = "%d/%d" % (min(self._random_platform_idx + 1, len(self.platforms)), len(self.platforms)) if self.platforms else "0/0"
        #     status = "随机: %s 平台%s" % (state_text, progress)
        #     cv2.rectangle(map_display, (0, MAP_H - 20), (FIXED_W, MAP_H), (25, 25, 25), -1)
        #     cv2.putText(map_display, status, (6, MAP_H - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1)

        # 【模块B】自动校准倍率显示（红字 + 浅灰圆角底条，直接显示在小地图底部）始终显示
        # 各轴单独显示：X设好后先显示X，Y设好后追加显示Y；都不显示"待设置中..."
        eff_sx, eff_sy = self._effective_scale()
        if eff_sx <= 0 and eff_sy <= 0:
            scale_text = "待设置中..."
        else:
            _parts = []
            _parts.append("X %.4f" % eff_sx if eff_sx > 0 else "X 未校准")
            _parts.append("Y %.4f" % eff_sy if eff_sy > 0 else "Y 未校准")
            scale_text = "  ".join(_parts)
        _fs = 0.5   # 字体约为原来的2/3
        _txt_size = cv2.getTextSize(scale_text, cv2.FONT_HERSHEY_SIMPLEX, _fs, 1)[0]  # 用和绘制一致厚度，宽度更准
        _left = max(0, (render_w - _txt_size[0]) // 2 + 35)  # 小地图中间再向右35PX（左移15）
        _baseline = render_h - 3  # y轴不动
        _txt_org = (_left, _baseline)
        # 浅灰底条：左右各留1px，刚好包住文字，不突出来
        _pad = 1
        _bx1 = _txt_org[0] - _pad
        _bx2 = _txt_org[0] + _txt_size[0] + _pad
        _by1 = _baseline - _txt_size[1] - 2
        _by2 = _baseline + 2
        cv2.rectangle(map_display, (_bx1, _by1), (_bx2, _by2), (210, 210, 210), -1)  # 浅灰底条
        cv2.rectangle(map_display, (_bx1, _by1), (_bx2, _by2), (170, 170, 170), 1)   # 细边框，更精致
        # 红色主体 + 一条细黑边(粗细1)做对比，干净利落
        cv2.putText(map_display, scale_text, _txt_org, cv2.FONT_HERSHEY_SIMPLEX, _fs, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(map_display, scale_text, _txt_org, cv2.FONT_HERSHEY_SIMPLEX, _fs, (0, 0, 255), 1, cv2.LINE_AA)  # 红色主体

        # 手动框选拖拽矩形
        if self._selecting and self._select_rect and self._select_dragging:
            x1, y1, x2, y2 = self._select_rect
            cv2.rectangle(map_display, (x1, y1), (x2, y2), (0, 255, 255), 1)

        # === 工具栏（小地图上方）=== 【已去掉UI绘制，用背景图自带按钮】
        # draw_asset(frame, self._ui_refresh, *BTN_REFRESH)
        # draw_asset(frame, self._ui_manual, *BTN_MANUAL)
        # draw_asset(frame, self._ui_plan_toolbar, *BTN_PLAN_TOOLBAR)
        # 【模块B】自动校准按钮（同屏三点校准）
        # draw_asset(frame, self._ui_calib_auto, *BTN_CALIB_AUTO)
        # X/Y倍率按钮：按压特效改用统一的 _pressed_btn 圆角变暗(与平台/梯子一致)，见下方"按钮点击特效"
        # 第三个框显示当前方案名或"随机"
        plan_label = "随机" if self.route_mode == "随机" else "方案%d" % self.current_route
        (plw, plh), _ = cv2.getTextSize(plan_label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        plx = BTN_PLAN_TOOLBAR[0] + (BTN_PLAN_TOOLBAR[2] - plw) // 2
        ply = BTN_PLAN_TOOLBAR[1] + (BTN_PLAN_TOOLBAR[3] + plh) // 2 - 2
        cv2.putText(frame, plan_label, (plx, ply), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)

        # === 按原始大小合成到背景（不拉伸，保持原始比率，显示在顶部按钮下方）===
        map_h, map_w = map_display.shape[:2]  # 获取map_display实际尺寸
        map_display_x = (UI_W - map_w) // 2  # 水平居中
        map_display_y = 143  # 垂直位置：从162再向上移19像素
        # 保存小地图显示位置和缩放比例（供鼠标点击坐标转换用）
        self._map_disp_x = map_display_x
        self._map_disp_y = map_display_y
        self._map_disp_w = map_w
        self._map_disp_h = map_h
        self._map_scale_x = scale_x
        self._map_scale_y = scale_y
        frame[map_display_y:map_display_y+map_h, map_display_x:map_display_x+map_w] = map_display  # 显示在顶部按钮下方

        # === 【模块B】台子选择按钮（小地图左上方）===
        # 点击弹出选择面板，可多选平台，选完关闭
        btn_sel_x, btn_sel_y, btn_sel_w, btn_sel_h = map_display_x + 5, map_display_y + 5, 60, 20
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

        # === 热键跑马灯展示区域（小地图下方、平台按钮上方，从右到左流动，绿色黑体大字）===
        _hk_x = UI_MAP_X          # 红框左X=29
        _hk_y = 412                # 红框顶Y
        _hk_w = UI_MAP_W           # 红框宽=403
        _hk_h = 36                 # 红框高=36
        _hk_text = "小提示：F5平台录制，F6梯子录制，F7方案清除，F8方案保存，F9手动截取小地图，F10开始运行，F12停止运行"
        # 滚动偏移每帧递减8像素（从右到左流动，速度再加大一倍），文字完全移出左边界后重置到右边缘
        self._hotkey_scroll_x -= 8
        try:
            _roi = frame[_hk_y:_hk_y+_hk_h, _hk_x:_hk_x+_hk_w].copy()
            _pil = Image.fromarray(cv2.cvtColor(_roi, cv2.COLOR_BGR2RGB))
            _draw = ImageDraw.Draw(_pil)
            _font = self._hotkey_font  # 复用预加载字体，避免每帧加载卡顿
            _bbox = _draw.textbbox((0, 0), _hk_text, font=_font)
            _tw = _bbox[2] - _bbox[0]
            _th = _bbox[3] - _bbox[1]
            _ty = (_hk_h - _th) // 2  # 垂直居中
            # 文字移出左边界后重置
            if self._hotkey_scroll_x < -_tw:
                self._hotkey_scroll_x = _hk_w
            _dx = self._hotkey_scroll_x
            _draw.text((_dx, _ty), _hk_text, font=_font, fill=(0, 128, 0))  # 深绿色
            # 无缝循环：文字尾部进入红框后，在右边补一份
            if _dx + _tw < _hk_w:
                _draw.text((_dx + _tw + 60, _ty), _hk_text, font=_font, fill=(0, 128, 0))
            _roi_out = cv2.cvtColor(np.array(_pil), cv2.COLOR_RGB2BGR)
            frame[_hk_y:_hk_y+_hk_h, _hk_x:_hk_x+_hk_w] = _roi_out
        except Exception:
            pass

        # === 路线页按钮素材（参考图精确坐标，支持透明）=== 【已去掉UI绘制，用背景图自带按钮】
        # draw_asset(frame, self._ui_platform, *BTN_PLATFORM)
        # draw_asset(frame, self._ui_ladder, *BTN_LADDER)
        # draw_asset(frame, self._ui_save, *BTN_SAVE)
        # draw_asset(frame, self._ui_plan, *BTN_PLAN)
        # draw_asset(frame, self._ui_platform_clear, *BTN_PLATFORM_CLR)
        # draw_asset(frame, self._ui_ladder_clear, *BTN_LADDER_CLR)
        # draw_asset(frame, self._ui_mode, *BTN_MODE)
        # draw_asset(frame, self._ui_plan_clear, *BTN_PLAN_CLR)
        # draw_asset(frame, self._ui_run, *BTN_RUN)
        # draw_asset(frame, self._ui_stop, *BTN_STOP)
        # draw_asset(frame, self._ui_char_btn, *BTN_CHAR)
        # draw_asset(frame, self._ui_offset_label, *BTN_OFFSET)
        # draw_asset(frame, self._ui_monster_data, *BTN_MONSTER)
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
            dd_btn_map = {"mode": BTN_MODE}
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
                is_current = (self._dropdown == "mode" and text == self.route_mode)
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
        # 拖拽时不绘制UI窗口上的准星，只显示pygame透明置顶窗口的准星（避免两个准星同时动）
        if not self._drag_crosshair:
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

        # === 怪物特征按钮（用UI图片，盖住原来的X/Y偏移输入框，点击打开怪物特征管理弹窗）===
        _mbfx, _mbfy, _mbfw, _mbfh = BTN_MONSTER_FEATURE
        # 加载怪物特征按钮UI图片（懒加载，只加载一次，用IMREAD_UNCHANGED保留alpha通道做透明混合）
        if not hasattr(self, '_monster_btn_img') or self._monster_btn_img is None:
            _btn_img_path = os.path.join(DATA_DIR, "monster_feature_btn.png")
            if os.path.exists(_btn_img_path):
                self._monster_btn_img = cv2.imdecode(np.fromfile(_btn_img_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            else:
                self._monster_btn_img = None
        if self._monster_btn_img is not None:
            # 直接用原图大小绘制，不缩放（图片尺寸190x60，和按钮尺寸一致）
            _img_h, _img_w = self._monster_btn_img.shape[:2]
            _draw_w = min(_img_w, _mbfw)
            _draw_h = min(_img_h, _mbfh)
            _roi = frame[_mbfy:_mbfy+_draw_h, _mbfx:_mbfx+_draw_w]
            _btn_roi = self._monster_btn_img[:_draw_h, :_draw_w]
            # 透明混合：如果有alpha通道（4通道），按alpha值混合；否则直接覆盖
            if _btn_roi.shape[2] == 4:
                _alpha = _btn_roi[:, :, 3:4].astype(np.float32) / 255.0
                _bg = _roi.astype(np.float32)
                _fg = _btn_roi[:, :, :3].astype(np.float32)
                frame[_mbfy:_mbfy+_draw_h, _mbfx:_mbfx+_draw_w] = (_fg * _alpha + _bg * (1 - _alpha)).astype(np.uint8)
            else:
                frame[_mbfy:_mbfy+_draw_h, _mbfx:_mbfx+_draw_w] = _btn_roi
        else:
            # 图片加载失败，用代码绘制兜底
            draw_rounded_rect(frame, _mbfx, _mbfy, _mbfw, _mbfh, 8, (46, 125, 50), -1)
            draw_rounded_rect(frame, _mbfx, _mbfy, _mbfw, _mbfh, 8, (76, 175, 80), 2)
            _mbtn_text = "怪物特征"
            (_mtw, _mth), _ = cv2.getTextSize(_mbtn_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            _mtx = _mbfx + (_mbfw - _mtw) // 2
            _mty = _mbfy + (_mbfh + _mth) // 2
            cv2.putText(frame, _mbtn_text, (_mtx, _mty), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        # 右上角显示特征数量
        _mcount = len(self._monster_templates)
        if _mcount > 0:
            cv2.putText(frame, "%d套" % _mcount, (_mbfx + _mbfw - 35, _mbfy + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 255, 200), 1)

        # === 按钮点击特效（仅按下变暗，圆角）===
        now_ms = time.time() * 1000
        if self._pressed_btn is not None:
            bx, by, bw, bh = self._pressed_btn
            overlay = frame.copy()
            draw_rounded_rect(overlay, bx, by, bw, bh, 10, (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
        self._btn_flashes.clear()

        # === 倍率差弹窗（按照弹窗组件实现规范，灰底白字，右上角X关闭，可拖拽，最上层）===
        if self._show_scale_dialog:
            self._update_scale_dialog_positions()  # 每次绘制都更新位置，确保拖拽后位置正确
            dlg_x = self._scale_dialog_pos[0]
            dlg_y = self._scale_dialog_pos[1]
            dlg_w, dlg_h = 320, 220
            # 弹窗背景（灰底）
            cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+dlg_h-1), (60, 60, 60), -1)
            cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+dlg_h-1), (100, 100, 100), 1)
            # 标题栏（顶部50像素区域，可拖拽）
            cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+50), (80, 80, 80), -1)
            cv2.putText(frame, "倍率差调整", (dlg_x+15, dlg_y+32), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            # 右上角关闭按钮X
            cx, cy, cw, ch = self._dlg_scale_close_btn
            cv2.rectangle(frame, (cx, cy), (cx+cw-1, cy+ch-1), (80, 80, 80), -1)
            cv2.putText(frame, "X", (cx+7, cy+18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            # X偏差标签和输入框
            cv2.putText(frame, "X偏差:", (dlg_x+20, dlg_y+88), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            sx_x, sx_y, sx_w, sx_h = self._dlg_scale_x_input
            cv2.rectangle(frame, (sx_x, sx_y), (sx_x+sx_w-1, sx_y+sx_h-1), (0, 0, 0), -1)  # 黑底
            border_color = (0, 165, 255) if self._focused_field == "scale_x_offset" else (255, 255, 255)  # 聚焦时橙色边框，否则白色
            border_thick = 2 if self._focused_field == "scale_x_offset" else 1
            cv2.rectangle(frame, (sx_x, sx_y), (sx_x+sx_w-1, sx_y+sx_h-1), border_color, border_thick)
            x_offset_val = self._field_values.get("scale_x_offset", "0")
            cv2.putText(frame, x_offset_val, (sx_x+8, sx_y+24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            # Y偏差标签和输入框
            cv2.putText(frame, "Y偏差:", (dlg_x+20, dlg_y+148), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            sy_x, sy_y, sy_w, sy_h = self._dlg_scale_y_input
            cv2.rectangle(frame, (sy_x, sy_y), (sy_x+sy_w-1, sy_y+sy_h-1), (0, 0, 0), -1)  # 黑底
            border_color = (0, 165, 255) if self._focused_field == "scale_y_offset" else (255, 255, 255)  # 聚焦时橙色边框，否则白色
            border_thick = 2 if self._focused_field == "scale_y_offset" else 1
            cv2.rectangle(frame, (sy_x, sy_y), (sy_x+sy_w-1, sy_y+sy_h-1), border_color, border_thick)
            y_offset_val = self._field_values.get("scale_y_offset", "0")
            cv2.putText(frame, y_offset_val, (sy_x+8, sy_y+24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            # 确认按钮
            ok_x, ok_y, ok_w, ok_h = self._dlg_scale_ok_btn
            cv2.rectangle(frame, (ok_x, ok_y), (ok_x+ok_w-1, ok_y+ok_h-1), (0, 128, 0), -1)
            cv2.putText(frame, "确认", (ok_x+20, ok_y+20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            # 取消按钮
            cancel_x, cancel_y, cancel_w, cancel_h = self._dlg_scale_cancel_btn
            cv2.rectangle(frame, (cancel_x, cancel_y), (cancel_x+cancel_w-1, cancel_y+cancel_h-1), (128, 0, 0), -1)
            cv2.putText(frame, "取消", (cancel_x+20, cancel_y+20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

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
        # OpenCV窗口对齐游戏窗口位置，避免偏移
        if self.window_rect:
            cv2.moveWindow(sel_win, self.window_rect["left"], self.window_rect["top"])
        else:
            cv2.moveWindow(sel_win, 0, 0)
        # 置顶：避免被游戏窗口挡住
        cv2.setWindowProperty(sel_win, cv2.WND_PROP_TOPMOST, 1)

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
        # F9结束后强制重新定位和置顶怪物蒙板（避免OpenCV窗口影响蒙板置顶和位置）
        if getattr(self, '_overlay_hwnd', None) and self.hwnd and self.window_rect:
            try:
                wr = self.window_rect
                user32.SetWindowPos(self._overlay_hwnd, -1, wr['left'], wr['top'],
                                    wr['width'], wr['height'], 0x0050)
                _debug_log("[F9] 蒙板已重新定位置顶: %dx%d +%d+%d" % (wr['width'], wr['height'], wr['left'], wr['top']))
            except Exception as _e:
                _debug_log("[F9] 蒙板重新定位失败: %s" % _e)
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
        self._recalc_scale_from_region()
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
        """从磁盘加载已保存的人物特征模板（优先运行时目录app_dir/data，打包后也能加载用户保存的模板）"""
        self._char_templates = []
        # 优先从运行时目录加载（用户保存的模板，打包后也在app_dir/data/char_templates）
        tpl_dir = CHAR_TEMPLATE_DIR
        has_runtime = False
        if os.path.exists(tpl_dir):
            has_runtime = any(f.startswith("char_") and f.endswith(".png") for f in os.listdir(tpl_dir))
        # 打包环境下运行时目录没有模板，则从内置_MEIPASS加载默认模板（记录003：修复保存后重启丢失）
        if not has_runtime and getattr(sys, 'frozen', False):
            tpl_dir = os.path.join(sys._MEIPASS, "data", "char_templates")
        if not os.path.exists(tpl_dir):
            print("[人物特征] 无保存的特征模板，为空")
            return
        # 先加载元数据（含偏移）
        meta_list = []
        try:
            if os.path.exists(CHAR_TEMPLATE_META):
                with open(CHAR_TEMPLATE_META, "r", encoding="utf-8") as _mf:
                    meta_list = json.load(_mf)
        except Exception:
            meta_list = []
        try:
            # 扫描 char_<id>.png，按文件名排序加载（ID小的在前）
            for fname in sorted(os.listdir(tpl_dir)):
                if fname.startswith("char_") and fname.endswith(".png"):
                    try:
                        tid = int(fname.replace("char_", "").replace(".png", ""))
                    except ValueError:
                        continue  # 非标准命名的文件跳过，不影响其他模板加载
                    img_path = os.path.join(tpl_dir, fname)
                    # 用imdecode+fromfile兼容中文路径（cv2.imread中文路径静默失败）
                    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        h, w = img.shape[:2]  # 3通道图shape=(h,w,3)，取前2维避免解包失败
                        # 从元数据加载偏移（默认0，兼容旧模板）
                        _off_x = 0
                        _off_y = 0
                        _direction = "right"  # 默认向右，兼容旧模板
                        for _m in meta_list:
                            if _m.get("id") == tid:
                                _off_x = int(_m.get("offset_x", 0))
                                _off_y = int(_m.get("offset_y", 0))
                                _direction = _m.get("direction", "right")
                                break
                        self._char_templates.append({
                            "id": tid,
                            "img": img,
                            "width": w,
                            "height": h,
                            "offset_x": _off_x,   # 特征匹配点→人物脚的X偏移
                            "offset_y": _off_y,   # 特征匹配点→人物脚的Y偏移
                            "direction": _direction,  # 朝向: left/right
                            "created_at": ""
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
                "offset_x": t.get("offset_x", 0),
                "offset_y": t.get("offset_y", 0),
                "direction": t.get("direction", "right"),
                "color": t.get("color", CHAR_FEATURE_COLORS[t["id"] % len(CHAR_FEATURE_COLORS)]),
                "created_at": t["created_at"]
            })
        try:
            with open(CHAR_TEMPLATE_META, "w", encoding="utf-8") as f:
                json.dump(meta_list, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[人物特征] 保存元数据失败:", e)

    def _capture_character_feature(self, direction="right"):
        """人物特征截图：在游戏窗口框选人物身体，保存为特征模板（最多10套）
        direction: "left"=向左的特征, "right"=向右的特征
        使用 cv2.selectROI 内置框选，坐标可靠，无最小尺寸限制（越小越精确）"""
        if self.hwnd is None:
            self._add_log("请先绑定游戏窗口")
            print("[人物特征] 未绑定窗口")
            return

        # 超过上限则先替换最早的一套（框选前删除最旧，保证磁盘和内存都不超10）
        if len(self._char_templates) >= CHAR_MAX_TEMPLATES:
            oldest = self._char_templates.pop(0)
            old_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % oldest["id"])
            if os.path.exists(old_path):
                os.remove(old_path)
            self._add_log("模板已满，替换最早一套")

        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]  # 兼容3通道图shape=(h,w,3)
        if fh <= 0 or fw <= 0:
            self._add_log("截图失败")
            return

        print("[人物特征] 弹出框选窗口，拖拽框选人物身体，回车确认，ESC取消")
        # 设置窗口位置和游戏窗口对齐（避免OpenCV默认位置错开）
        cv2.namedWindow("Select Character", cv2.WINDOW_NORMAL)
        cv2.moveWindow("Select Character", self.window_rect["left"], self.window_rect["top"])
        cv2.resizeWindow("Select Character", fw, fh)  # 显式设置窗口大小为截图大小，避免OpenCV记住上次变小的尺寸
        # cv2.selectROI 返回 (x, y, w, h)，取消返回全0
        roi = cv2.selectROI("Select Character", frame, showCrosshair=False, fromCenter=False)
        cv2.destroyWindow("Select Character")

        x, y, w, h = roi
        if w <= 0 or h <= 0:
            print("[人物特征] 取消框选")
            return

        captured = frame[y:y + h, x:x + w].copy()

        # 分配新ID（取最大ID+1，空列表从0开始）
        existing_ids = [t["id"] for t in self._char_templates]
        new_id = (max(existing_ids) + 1) if existing_ids else 0
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")

        # 保存到磁盘（用imencode+tofile兼容中文路径，cv2.imwrite中文路径静默失败）
        img_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % new_id)
        ok, buf = cv2.imencode(".png", captured)
        if ok:
            buf.tofile(img_path)
            print("[人物特征] 模板已保存:", img_path)
        else:
            self._add_log("人物特征保存失败")
            print("[人物特征] 保存失败: cv2.imencode返回False")

        ch, cw = captured.shape[:2]  # 兼容3通道图shape=(h,w,3)
        # 自动分配颜色（按ID取色，保证不重复）
        feat_color = CHAR_FEATURE_COLORS[new_id % len(CHAR_FEATURE_COLORS)]
        self._char_templates.append({
            "id": new_id,
            "img": captured,
            "width": cw,
            "height": ch,
            "offset_x": 0,   # 默认偏移0，用户在弹窗中校准到人物脚
            "offset_y": 0,
            "color": feat_color,  # 特征颜色，用于蒙板上显示匹配点
            "direction": direction,  # 朝向: left/right
            "created_at": created_at
        })
        self._save_char_meta()

        dir_name = "向左" if direction == "left" else "向右"
        msg = "人物特征#%d已保存(%s) (%dx%d) 共%d套" % (new_id, dir_name, cw, ch, len(self._char_templates))
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

    # ==================== 怪物特征模板（手动添加，和YOLO合并显示小地图紫点） ====================
    def _load_monster_templates(self):
        """从磁盘加载已保存的怪物特征模板"""
        self._monster_templates = []
        tpl_dir = MONSTER_TEMPLATE_DIR
        if not os.path.exists(tpl_dir):
            print("[怪物特征] 无保存的特征模板，为空")
            return
        # 加载元数据（含偏移、方向）
        meta_list = []
        try:
            if os.path.exists(MONSTER_TEMPLATE_META):
                with open(MONSTER_TEMPLATE_META, "r", encoding="utf-8") as _mf:
                    meta_list = json.load(_mf)
        except Exception:
            meta_list = []
        try:
            for fname in sorted(os.listdir(tpl_dir)):
                if fname.startswith("monster_") and fname.endswith(".png"):
                    try:
                        tid = int(fname.replace("monster_", "").replace(".png", ""))
                    except ValueError:
                        continue
                    img_path = os.path.join(tpl_dir, fname)
                    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        h, w = img.shape[:2]
                        _off_x = 0
                        _off_y = 0
                        _direction = "right"
                        for _m in meta_list:
                            if _m.get("id") == tid:
                                _off_x = int(_m.get("offset_x", 0))
                                _off_y = int(_m.get("offset_y", 0))
                                _direction = _m.get("direction", "right")
                                break
                        self._monster_templates.append({
                            "id": tid, "img": img, "width": w, "height": h,
                            "offset_x": _off_x, "offset_y": _off_y,
                            "direction": _direction, "created_at": ""
                        })
            print("[怪物特征] 已加载 %d 套模板" % len(self._monster_templates))
        except Exception as e:
            print("[怪物特征] 加载模板失败:", e)

    def _save_monster_meta(self):
        """保存怪物特征模板元数据到磁盘"""
        meta_list = []
        for t in self._monster_templates:
            meta_list.append({
                "id": t["id"], "width": t["width"], "height": t["height"],
                "offset_x": t.get("offset_x", 0), "offset_y": t.get("offset_y", 0),
                "direction": t.get("direction", "right"), "created_at": t["created_at"]
            })
        try:
            with open(MONSTER_TEMPLATE_META, "w", encoding="utf-8") as f:
                json.dump(meta_list, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[怪物特征] 保存元数据失败:", e)

    def _capture_monster_feature(self, direction="right"):
        """怪物特征截图：在游戏窗口框选怪物身体，保存为特征模板（最多10套）"""
        if self.hwnd is None:
            self._add_log("请先绑定游戏窗口")
            print("[怪物特征] 未绑定窗口")
            return
        if len(self._monster_templates) >= MONSTER_MAX_TEMPLATES:
            oldest = self._monster_templates.pop(0)
            old_path = os.path.join(MONSTER_TEMPLATE_DIR, "monster_%d.png" % oldest["id"])
            if os.path.exists(old_path):
                os.remove(old_path)
            self._add_log("怪物模板已满，替换最早一套")
        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]
        if fh <= 0 or fw <= 0:
            self._add_log("截图失败")
            return
        print("[怪物特征] 弹出框选窗口，拖拽框选怪物身体，回车确认，ESC取消")
        cv2.namedWindow("Select Monster", cv2.WINDOW_NORMAL)
        cv2.moveWindow("Select Monster", self.window_rect["left"], self.window_rect["top"])
        cv2.resizeWindow("Select Monster", fw, fh)  # 显式设置窗口大小为截图大小，避免OpenCV记住上次变小的尺寸
        roi = cv2.selectROI("Select Monster", frame, showCrosshair=False, fromCenter=False)
        cv2.destroyWindow("Select Monster")
        x, y, w, h = roi
        if w <= 0 or h <= 0:
            print("[怪物特征] 取消框选")
            return
        captured = frame[y:y + h, x:x + w].copy()
        existing_ids = [t["id"] for t in self._monster_templates]
        new_id = (max(existing_ids) + 1) if existing_ids else 0
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        img_path = os.path.join(MONSTER_TEMPLATE_DIR, "monster_%d.png" % new_id)
        ok, buf = cv2.imencode(".png", captured)
        if ok:
            buf.tofile(img_path)
            print("[怪物特征] 模板已保存:", img_path)
        else:
            self._add_log("怪物特征保存失败")
        ch, cw = captured.shape[:2]
        self._monster_templates.append({
            "id": new_id, "img": captured, "width": cw, "height": ch,
            "offset_x": 0, "offset_y": 0, "direction": direction, "created_at": created_at
        })
        self._save_monster_meta()
        dir_name = "向左" if direction == "left" else "向右"
        msg = "怪物特征#%d已保存(%s) (%dx%d) 共%d套" % (new_id, dir_name, cw, ch, len(self._monster_templates))
        self._add_log(msg)
        print("[怪物特征]", msg)

    def _clear_monster_features(self):
        """清除所有怪物特征模板"""
        count = len(self._monster_templates)
        if count == 0:
            self._add_log("没有可清除的怪物特征")
            return
        for t in self._monster_templates:
            img_path = os.path.join(MONSTER_TEMPLATE_DIR, "monster_%d.png" % t["id"])
            if os.path.exists(img_path):
                os.remove(img_path)
        self._monster_templates = []
        if os.path.exists(MONSTER_TEMPLATE_META):
            os.remove(MONSTER_TEMPLATE_META)
        self._add_log("已清除 %d 套怪物特征" % count)
        print("[怪物特征] 已清除 %d 套" % count)

    def _delete_monster_template(self, index):
        """删除指定索引的怪物特征模板"""
        if index < 0 or index >= len(self._monster_templates):
            return
        t = self._monster_templates.pop(index)
        img_path = os.path.join(MONSTER_TEMPLATE_DIR, "monster_%d.png" % t["id"])
        if os.path.exists(img_path):
            os.remove(img_path)
        self._save_monster_meta()
        self._monster_feature_matches = []  # 删除特征后清空匹配结果，避免旧点继续显示
        self._monsters = []  # 删除特征后也清空小地图怪物点，避免旧点继续显示
        self._add_log("已删除怪物特征#%d" % t["id"])
        print("[怪物特征] 已删除 #%d")

    def _player_track_loop(self):
        """人物坐标跟踪线程（单独线程，每帧截图+人物匹配，确保人物点死死咬住位置不跳变）
        不阻塞主循环，YOLO检测和战斗逻辑继续正常运行
        """
        print("[人物跟踪] 线程已启动，每帧截图+匹配")
        last_log = 0
        _debug_saved = False  # 调试：保存第一张截图，看看线程里截到的图是不是正常的
        while not self._player_track_stop:
            try:
                # 检查窗口是否绑定
                if not self.hwnd or not win32gui.IsWindow(self.hwnd):
                    time.sleep(0.01)
                    continue
                # 每帧截图
                frame = self._capture_window()
                if frame is None:
                    time.sleep(0.005)
                    continue
                # 调试：保存第一张截图
                if not _debug_saved:
                    _debug_saved = True
                    try:
                        cv2.imwrite("debug_thread_capture.png", frame)
                        print(f"[人物跟踪] 调试：已保存第一张截图，尺寸={frame.shape}, 特征模板数={len(self._char_templates) if self._char_templates else 0}")
                    except Exception as e:
                        print(f"[人物跟踪] 调试：保存截图失败: {e}")
                # 人物特征匹配（每帧一次）
                pos = self._get_player_screen_pos(frame)
                # 用锁保护，更新人物位置
                with self._player_track_lock:
                    self._player_screen_pos = pos
                # 每秒打印一次状态
                now = time.time()
                if now - last_log >= 1.0:
                    last_log = now
                    if pos:
                        print(f"[人物跟踪] 线程正常 位置=({pos[0]},{pos[1]}) 置信度={pos[2]:.2f}" if len(pos) > 2 else f"[人物跟踪] 线程正常 位置=({pos[0]},{pos[1]})")
                    else:
                        print("[人物跟踪] 线程正常 未匹配到人物")
            except Exception as e:
                print(f"[人物跟踪] 线程异常: {e}")
                time.sleep(0.01)
            # 短暂休眠，避免CPU占用过高
            time.sleep(0.001)
        print("[人物跟踪] 线程已停止")

    def _start_player_track(self):
        """启动人物坐标跟踪线程"""
        if self._player_track_thread and self._player_track_thread.is_alive():
            print("[人物跟踪] 线程已在运行")
            return
        self._player_track_stop = False
        self._player_track_thread = threading.Thread(target=self._player_track_loop, daemon=True)
        self._player_track_thread.start()
        print("[人物跟踪] 线程启动命令已发送")

    def _stop_player_track(self):
        """停止人物坐标跟踪线程"""
        self._player_track_stop = True
        if self._player_track_thread:
            self._player_track_thread.join(timeout=2.0)
            self._player_track_thread = None
        print("[人物跟踪] 线程停止命令已发送")

    def _match_character(self, frame):
        """【多特征融合】在游戏画面中用多个特征模板匹配查找人物脚位置
        1. 遍历所有特征，每个特征匹配到位置后 + 该特征offset → 人物脚位置预测
        2. 有效预测>=2个：一致性校验（排除距中心点>50px的异常值）→ 按置信度加权平均
        3. 只有1个有效预测：置信度>=0.75才返回（提高门槛，减少误判）
        4. 全图失败 → ROI回退（上次位置附近，阈值0.55）
        Returns:
            (foot_x, foot_y, confidence) 或 None
        """
        if not self._char_templates or frame is None:
            if not self._char_templates:
                _now = time.time()
                if not hasattr(self, '_last_no_tpl_log') or _now - self._last_no_tpl_log > 5:
                    self._last_no_tpl_log = _now
                    print("[人物匹配] 没有人物特征模板，请先在人物特征弹窗中添加")
            return None
        fh, fw = frame.shape[:2]

        # === 第一步：全图匹配所有特征，收集预测 ===
        predictions = []  # [(foot_x, foot_y, confidence, tpl_id), ...]
        for tpl in self._char_templates:
            timg = tpl["img"]
            th, tw = timg.shape[:2]
            if th > fh or tw > fw:
                continue
            result = cv2.matchTemplate(frame, timg, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val >= CHAR_MATCH_THRESHOLD:
                # 特征中心点 + 该特征offset → 人物脚位置
                feat_cx = max_loc[0] + tw // 2
                feat_cy = max_loc[1] + th // 2
                foot_x = feat_cx + int(tpl.get("offset_x", 0))
                foot_y = feat_cy + int(tpl.get("offset_y", 0))
                predictions.append((foot_x, foot_y, max_val, tpl["id"], tpl.get("direction", "right")))

        # 记录每个特征的单独匹配结果（用于蒙板上显示每个特征的匹配点+数字，方便发现哪个特征误判）
        self._char_feature_matches = [(p[0], p[1], p[3], p[2]) for p in predictions]

        # === 第二步：多特征融合（不区分方向，直接融合所有特征预测，只要位置） ===
        if len(predictions) >= 2:
            # 计算所有预测的中心点
            avg_x = sum(p[0] for p in predictions) / len(predictions)
            avg_y = sum(p[1] for p in predictions) / len(predictions)
            # 一致性校验：排除距离中心点>50px的异常值（误判）
            valid = []
            for px, py, conf, tid, _dir in predictions:
                dist = ((px - avg_x)**2 + (py - avg_y)**2) ** 0.5
                if dist <= 50:
                    valid.append((px, py, conf, tid))
                else:
                    _debug_log("[人物匹配] 排除异常预测 特征#%d 位置(%d,%d) 距中心%.0fpx" % (tid, px, py, dist))
            # 有效预测>=2个：按置信度加权平均
            if len(valid) >= 2:
                total_conf = sum(p[2] for p in valid)
                if total_conf > 0:
                    final_x = int(sum(p[0] * p[2] for p in valid) / total_conf)
                    final_y = int(sum(p[1] * p[2] for p in valid) / total_conf)
                    avg_conf = total_conf / len(valid)
                    self._last_char_match_pos = (final_x, final_y)
                    self._last_char_match_time = time.time() * 1000
                    _debug_log("[人物匹配] 多特征融合成功 %d/%d特征 置信度%.2f 位置(%d,%d)" % (
                        len(valid), len(predictions), avg_conf, final_x, final_y))
                    return (final_x, final_y, avg_conf)
            # 有效预测只剩1个：用这个（去掉0.75门槛，只要>=0.70就返回，避免光点间歇性消失）
            elif len(valid) == 1 and valid[0][2] >= CHAR_MATCH_THRESHOLD:
                final_x, final_y, conf, _ = valid[0]
                self._last_char_match_pos = (final_x, final_y)
                self._last_char_match_time = time.time() * 1000
                _debug_log("[人物匹配] 单特征(融合后剩1个) 置信度%.2f 位置(%d,%d)" % (conf, final_x, final_y))
                return (final_x, final_y, conf)
        elif len(predictions) == 1 and predictions[0][2] >= CHAR_MATCH_THRESHOLD:
            # 只有1个特征匹配成功（去掉0.75门槛，只要>=0.70就返回，避免光点间歇性消失）
            final_x, final_y, conf, _, _ = predictions[0]
            self._last_char_match_pos = (final_x, final_y)
            self._last_char_match_time = time.time() * 1000
            _debug_log("[人物匹配] 单特征 置信度%.2f 位置(%d,%d)" % (conf, final_x, final_y))
            return (final_x, final_y, conf)

        # === 第三步：ROI回退（已注释掉，用户要求恢复原始全图匹配，人一动就准）===
        # 用户要求：把限制的功能先注释掉，恢复到原始样子，直接检测和跟随
        # last_pos = getattr(self, '_last_char_match_pos', None)
        # if last_pos:
        #     ... (ROI回退逻辑已注释，全图匹配失败直接返回None)

        # 全图匹配失败（ROI回退已注释）
        _now = time.time()
        if not hasattr(self, '_last_lowscore_log') or _now - self._last_lowscore_log > 5:
            self._last_lowscore_log = _now
            _debug_log("[人物匹配] 全图+ROI都失败，特征%d套" % len(self._char_templates))
        return None

    def _match_monster(self, frame):
        """【怪物特征多目标匹配】在游戏画面中用怪物特征模板匹配查找所有怪物
        1. 全图匹配所有特征，收集所有超过阈值的匹配位置
        2. 非极大值抑制（距离太近的合并，保留置信度最高的）
        3. 返回怪物框列表 [(x1, y1, x2, y2, score), ...]
        优化：方向过滤（只匹配当前朝向的特征），ROI优先（在上次位置附近匹配）
        """
        if not self._monster_templates or frame is None:
            return []
        fh, fw = frame.shape[:2]
        all_matches = []  # [(cx, cy, score, tpl_w, tpl_h), ...]

        # === 全图匹配所有特征，收集所有超过阈值的位置 ===
        feature_best = {}  # 每个特征的最佳匹配 {tpl_id: (cx, cy, score)}
        for tpl in self._monster_templates:
            timg = tpl["img"]
            th, tw = timg.shape[:2]
            if th > fh or tw > fw:
                continue
            result = cv2.matchTemplate(frame, timg, cv2.TM_CCOEFF_NORMED)
            # 找所有超过阈值的位置
            locs = np.where(result >= MONSTER_MATCH_THRESHOLD)
            for pt in zip(*locs[::-1]):  # pt = (x, y)
                score = result[pt[1], pt[0]]
                cx = pt[0] + tw // 2 + int(tpl.get("offset_x", 0))
                cy = pt[1] + th // 2 + int(tpl.get("offset_y", 0))
                all_matches.append((cx, cy, score, tw, th))
                # 记录每个特征的最佳匹配位置（用于蒙板显示特征点+数字）
                tid = tpl["id"]
                if tid not in feature_best or score > feature_best[tid][2]:
                    feature_best[tid] = (cx, cy, score)
        # 记录每个特征的最佳匹配结果到蒙板（显示紫色点+数字编号，方便发现哪个特征误判）
        self._monster_feature_matches = [(v[0], v[1], k, v[2]) for k, v in feature_best.items()]
        # 调试日志：查看怪物特征匹配结果
        _now_dbg = time.time()
        if not hasattr(self, '_last_monster_dbg_log') or _now_dbg - self._last_monster_dbg_log > 2:
            self._last_monster_dbg_log = _now_dbg
            _debug_log("[怪物特征匹配] 模板%d套 匹配到%d个特征点: %s" % (
                len(self._monster_templates), len(self._monster_feature_matches),
                str([(f[0], f[1], f[2], round(f[3], 2)) for f in self._monster_feature_matches[:5]])))

        # === 非极大值抑制（距离太近的合并，保留置信度最高的） ===
        all_matches.sort(key=lambda x: x[2], reverse=True)  # 按置信度降序
        monsters = []
        used = [False] * len(all_matches)
        for i, (cx, cy, score, tw, th) in enumerate(all_matches):
            if used[i]:
                continue
            # 找所有距离这个匹配太近的，合并
            cluster = [(cx, cy, score, tw, th)]
            used[i] = True
            for j in range(i + 1, len(all_matches)):
                if used[j]:
                    continue
                cx2, cy2, _, _, _ = all_matches[j]
                dist = ((cx - cx2)**2 + (cy - cy2)**2) ** 0.5
                if dist < max(tw, th) * 0.8:  # 距离小于模板尺寸的80%，合并
                    cluster.append(all_matches[j])
                    used[j] = True
            # 取聚类中置信度最高的作为代表
            best = max(cluster, key=lambda x: x[2])
            bcx, bcy, bscore, btw, bth = best
            # 转换成怪物框格式 (x1, y1, x2, y2, score)
            x1 = max(0, bcx - btw // 2)
            y1 = max(0, bcy - bth // 2)
            x2 = min(fw, bcx + btw // 2)
            y2 = min(fh, bcy + bth // 2)
            monsters.append((x1, y1, x2, y2, bscore))

        if monsters:
            _debug_log("[怪物特征匹配] 检测到 %d 个怪物" % len(monsters))
        return monsters

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
                # === 自动校准蒙板拖动（仅stage=1时，拖动绿点蓝点定特色位置）===
                elif msg == 0x0201:  # WM_LBUTTONDOWN
                    if getattr(self, '_auto_calib_stage', 0) == 1:
                        # 用GetCursorPos取屏幕坐标（最准，不依赖窗口客户区）
                        cursor = wintypes.POINT()
                        user32.GetCursorPos(ctypes.byref(cursor))
                        mx, my = cursor.x, cursor.y
                        green_scr = getattr(self, '_auto_calib_green_screen', None)
                        blue_scr = getattr(self, '_auto_calib_blue_screen', None)
                        # 检测是否点中绿点或蓝点（±10px范围，方便点击）
                        if green_scr and abs(mx - green_scr[0]) <= 10 and abs(my - green_scr[1]) <= 10:
                            self._auto_calib_dragging = 'green'
                            return 0
                        if blue_scr and abs(mx - blue_scr[0]) <= 10 and abs(my - blue_scr[1]) <= 10:
                            self._auto_calib_dragging = 'blue'
                            return 0
                elif msg == 0x0200:  # WM_MOUSEMOVE
                    if getattr(self, '_auto_calib_dragging', None):
                        cursor = wintypes.POINT()
                        user32.GetCursorPos(ctypes.byref(cursor))
                        mx, my = cursor.x, cursor.y
                        base = getattr(self, '_auto_calib_base', None)
                        if base:
                            bx, by = base[0], base[1]
                            if self._auto_calib_dragging == 'green':
                                # 绿点只能水平拖动，Y保持基点Y（水平）
                                self._auto_calib_green_screen = (mx, by)
                            elif self._auto_calib_dragging == 'blue':
                                # 蓝点只能垂直拖动，X保持基点X（垂直）
                                self._auto_calib_blue_screen = (bx, my)
                        return 0
                elif msg == 0x0202:  # WM_LBUTTONUP
                    if getattr(self, '_auto_calib_dragging', None):
                        self._auto_calib_dragging = None
                elif msg == 0x0204:  # WM_RBUTTONDOWN：右键点击检测框内弹出对话框（编辑/保存）
                    _rx = ctypes.c_short(lParam & 0xFFFF).value
                    _ry = ctypes.c_short((lParam >> 16) & 0xFFFF).value
                    for _di, _db in enumerate(self._bg_regions):
                        if _db["x"] <= _rx <= _db["x"] + _db["w"] and _db["y"] <= _ry <= _db["y"] + _db["h"]:
                            # 点击在检测框内：弹出对话框，是=进入编辑，否=保存并退出编辑
                            _ret = user32.MessageBoxW(hwnd, "是=进入编辑（可拖动检测框）\n否=保存位置", "检测框操作", 4)  # MB_YESNO
                            if _ret == 6:  # IDYES = 进入编辑状态
                                self._bg_editing = True
                                self._bg_dragging = _di
                                print("[检测框] 进入编辑状态，框%d可拖动" % _di)
                            elif _ret == 7:  # IDNO = 保存
                                self._bg_editing = False
                                self._bg_dragging = -1
                                self._save_bg_regions()
                                print("[检测框] 已保存检测框位置")
                            return 0
                elif msg == 0x0200:  # WM_MOUSEMOVE：编辑状态下拖动死区检测框
                    if getattr(self, '_bg_editing', False) and self._bg_dragging >= 0:
                        _mx = ctypes.c_short(lParam & 0xFFFF).value
                        _my = ctypes.c_short((lParam >> 16) & 0xFFFF).value
                        _db = self._bg_regions[self._bg_dragging]
                        _db["x"] = max(0, _mx - _db["w"] // 2)
                        _db["y"] = max(0, _my - _db["h"] // 2)
                        return 0
                elif msg == 0x0205:  # WM_RBUTTONUP：编辑状态下右键松开不处理（对话框已在按下时弹出）
                    return 0
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
                        # === 自动校准点标记（仅stage=1时显示红绿蓝三点+连线，截图后隐藏，只留绿/蓝跟踪圆）===
                        auto_base = getattr(self, '_auto_calib_base', None)
                        auto_stage = getattr(self, '_auto_calib_stage', 0)
                        if auto_base and len(auto_base) >= 4 and auto_stage == 1:
                            bx, by = auto_base[0], auto_base[1]  # 基点屏幕坐标（stage=1时实时跟随人物）
                            _axis = getattr(self, '_auto_calib_axis', 'X')  # 当前校准方向（X绿圈/Y蓝圈）
                            goff = getattr(self, '_auto_calib_green_offset', (400, 0))  # 绿点偏移
                            boff = getattr(self, '_auto_calib_blue_offset', (0, -400))   # 蓝点偏移
                            # 画基点（红色实心圆）
                            brush_calib = gdi32.CreateSolidBrush(0x0000FF)
                            if brush_calib:
                                gdi_objs.append(brush_calib)
                            old_brush_calib = gdi32.SelectObject(hdc, brush_calib)
                            gdi32.Ellipse(hdc, bx - 6, by - 6, bx + 7, by + 7)
                            gdi32.SelectObject(hdc, old_brush_calib)
                            gdi32.SetTextColor(hdc, 0x0000FF)
                            gdi32.SetBkMode(hdc, 1)
                            gdi32.TextOutW(hdc, bx + 8, by - 8, "基", 1)
                            if _axis == 'X':
                                # 只画绿圈（X方向）
                                rx, ry = bx + goff[0], by + goff[1]  # 绿点屏幕位置
                                brush_g = gdi32.CreateSolidBrush(0x00FF00)
                                if brush_g:
                                    gdi_objs.append(brush_g)
                                old_brush_g = gdi32.SelectObject(hdc, brush_g)
                                gdi32.Ellipse(hdc, rx - 6, ry - 6, rx + 7, ry + 7)
                                gdi32.SelectObject(hdc, old_brush_g)
                                gdi32.SetTextColor(hdc, 0x00FF00)
                                gdi32.TextOutW(hdc, rx + 8, ry - 8, "X", 1)
                                pen = gdi32.CreatePen(0, 2, 0x0000FF)
                                if pen:
                                    gdi_objs.append(pen)
                                old_pen = gdi32.SelectObject(hdc, pen)
                                gdi32.MoveToEx(hdc, bx, by, None)
                                gdi32.LineTo(hdc, rx, ry)
                                gdi32.SelectObject(hdc, old_pen)
                                gdi32.SetTextColor(hdc, 0x00FFFF)
                                txt = "X:%d" % (rx - bx)
                                gdi32.TextOutW(hdc, (bx + rx) // 2 - 20, (by + ry) // 2 - 10, txt, len(txt))
                            else:
                                # 只画蓝圈（Y方向）
                                tx, ty = bx + boff[0], by + boff[1]  # 蓝点屏幕位置
                                brush_b = gdi32.CreateSolidBrush(0xFF0000)
                                if brush_b:
                                    gdi_objs.append(brush_b)
                                old_brush_b = gdi32.SelectObject(hdc, brush_b)
                                gdi32.Ellipse(hdc, tx - 6, ty - 6, tx + 7, ty + 7)
                                gdi32.SelectObject(hdc, old_brush_b)
                                gdi32.SetTextColor(hdc, 0xFF0000)
                                gdi32.TextOutW(hdc, tx + 8, ty - 8, "Y", 1)
                                pen_b = gdi32.CreatePen(0, 2, 0xFF0000)
                                if pen_b:
                                    gdi_objs.append(pen_b)
                                old_pen_b = gdi32.SelectObject(hdc, pen_b)
                                gdi32.MoveToEx(hdc, bx, by, None)
                                gdi32.LineTo(hdc, tx, ty)
                                gdi32.SelectObject(hdc, old_pen_b)
                                gdi32.SetTextColor(hdc, 0x00FFFF)
                                txt_y = "Y:%d" % (by - ty)
                                gdi32.TextOutW(hdc, (bx + tx) // 2 + 5, (by + ty) // 2, txt_y, len(txt_y))
                        # === 模板匹配空心圆（stage>=2时，在匹配位置画空心圆，标记特色位置）===
                        if auto_stage >= 2:
                            # 绿色特色位置绿光圈（半径20，线宽4）
                            gmatch = getattr(self, '_calib_green_match_pos', None)
                            if gmatch:
                                green_pen = gdi32.CreatePen(0, 4, 0x00FF00)  # 绿色BGR
                                if green_pen:
                                    gdi_objs.append(green_pen)
                                old_pen_g = gdi32.SelectObject(hdc, green_pen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷
                                gx, gy = gmatch
                                gdi32.Ellipse(hdc, gx - 20, gy - 20, gx + 21, gy + 21)
                                gdi32.SelectObject(hdc, old_pen_g)
                            # 蓝色特色位置蓝光圈（半径20，线宽4）
                            bmatch = getattr(self, '_calib_blue_match_pos', None)
                            if bmatch:
                                blue_pen = gdi32.CreatePen(0, 4, 0xFF0000)  # 蓝色BGR
                                if blue_pen:
                                    gdi_objs.append(blue_pen)
                                old_pen_b = gdi32.SelectObject(hdc, blue_pen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷
                                blx, bly = bmatch
                                gdi32.Ellipse(hdc, blx - 20, bly - 20, blx + 21, bly + 21)
                                gdi32.SelectObject(hdc, old_pen_b)
                        # === 校准步骤文字提示（窗口最上方白边，红色大字，明显提示当前第几步）===
                        if auto_stage >= 1:
                            _cal_axis = getattr(self, '_auto_calib_axis', 'X')  # 当前校准方向(第3步引导按X/Y区分)
                            step_texts = {
                                1: "请移动光圈到角色能够到达的位置并且相对固定的背景上",
                                2: "请移动角色到光圈位置",
                                3: ("X点记录完成 请按【Y倍率】进行下一步" if _cal_axis == 'X' else "Y点记录完成"),
                            }
                            step_txt = step_texts.get(auto_stage, "")
                            if step_txt:
                                gdi32.SetTextColor(hdc, 0x0000FF)  # 红色文字（BGR格式）
                                gdi32.SetBkMode(hdc, 1)  # 透明背景
                                # 文字显示在窗口最上方白边（水平居中，垂直靠上）
                                txt_x = max(10, rect.right // 2 - 280)
                                txt_y = 15  # 窗口最上方白边
                                gdi32.TextOutW(hdc, txt_x, txt_y, step_txt, len(step_txt))
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
                            # 人物特征单独匹配点（黄色小点+数字编号，方便发现哪个特征误判）
                            # 注：已去掉大的常驻黄点（半径6），只用带编号的小光点显示每个特征的匹配情况
                            for (fx, fy, fid, fconf) in data.get('char_feature_matches', []):
                                r = 4  # 半径4（原3加大20%）
                                fpen = gdi32.CreatePen(0, 1, 0x0080FF)  # 橙色边框
                                if fpen:
                                    gdi_objs.append(fpen)
                                fbrush = gdi32.CreateSolidBrush(0x00FFFF)  # 黄色填充
                                if fbrush:
                                    gdi_objs.append(fbrush)
                                old_fpen = gdi32.SelectObject(hdc, fpen)
                                old_fbrush = gdi32.SelectObject(hdc, fbrush)
                                gdi32.Ellipse(hdc, fx - r, fy - r, fx + r + 1, fy + r + 1)
                                gdi32.SelectObject(hdc, old_fpen)
                                gdi32.SelectObject(hdc, old_fbrush)
                                # 数字编号（在点的右边，17号字体，原14加大20%）
                                txt = str(fid)
                                ffont = gdi32.CreateFontW(17, 0, 0, 0, 400, 0, 0, 0, 134, 3, 2, 1, 49, "微软雅黑")
                                if ffont:
                                    gdi_objs.append(ffont)
                                old_ffont = gdi32.SelectObject(hdc, ffont)
                                gdi32.SetTextColor(hdc, 0x00FFFF)  # 黄色文字
                                gdi32.SetBkMode(hdc, 1)  # 透明背景
                                gdi32.TextOutW(hdc, fx + 7, fy - 11, txt, len(txt))
                                gdi32.SelectObject(hdc, old_ffont)

                            # 怪物特征单独匹配点（紫色小点+数字编号，方便发现哪个特征误判）
                            # 注：和人物特征点写法完全一样，不用self（wnd_proc回调中self会导致异常）
                            for (fx, fy, fid, fconf) in data.get('monster_feature_matches', []):
                                r = 4  # 半径4（和人物特征点一样）
                                # 怪物特征点：紫蓝色 0x8000FF（测试是不是只有0xFF00FF有问题）
                                fpen = gdi32.CreatePen(0, 1, 0x800080)  # 深紫色边框
                                if fpen:
                                    gdi_objs.append(fpen)
                                fbrush = gdi32.CreateSolidBrush(0x8000FF)  # 紫蓝色填充（测试）
                                if fbrush:
                                    gdi_objs.append(fbrush)
                                old_fpen = gdi32.SelectObject(hdc, fpen)
                                old_fbrush = gdi32.SelectObject(hdc, fbrush)
                                gdi32.Ellipse(hdc, fx - r, fy - r, fx + r + 1, fy + r + 1)
                                gdi32.SelectObject(hdc, old_fpen)
                                gdi32.SelectObject(hdc, old_fbrush)
                                # 数字编号（在点的右边，17号字体）
                                txt = str(fid)
                                ffont = gdi32.CreateFontW(17, 0, 0, 0, 400, 0, 0, 0, 134, 3, 2, 1, 49, "微软雅黑")
                                if ffont:
                                    gdi_objs.append(ffont)
                                old_ffont = gdi32.SelectObject(hdc, ffont)
                                gdi32.SetTextColor(hdc, 0x8000FF)  # 紫蓝色文字
                                gdi32.SetBkMode(hdc, 1)  # 透明背景
                                gdi32.TextOutW(hdc, fx + 7, fy - 11, txt, len(txt))
                                gdi32.SelectObject(hdc, old_ffont)

                            if char_pos:
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

        # === 第二个蒙板：专门显示人物绿框（小地图光点映射内容），独立窗口过程 ===
        def wnd_proc_lock(hwnd, msg, wParam, lParam):
            try:
                if msg == WM_TIMER:
                    user32.InvalidateRect(hwnd, None, True)
                    return 0
                elif msg == WM_ERASEBKGND:
                    return 1
                elif msg == WM_PAINT:
                    ps2 = PAINTSTRUCT()
                    hdc2 = user32.BeginPaint(hwnd, ctypes.byref(ps2))
                    gdi_objs2 = []
                    try:
                        rect2 = wintypes.RECT()
                        user32.GetClientRect(hwnd, ctypes.byref(rect2))
                        brush2 = gdi32.CreateSolidBrush(COLOR_MAGENTA)
                        if brush2:
                            gdi_objs2.append(brush2)
                        user32.FillRect(hdc2, ctypes.byref(rect2), brush2)
                    finally:
                        user32.EndPaint(hwnd, ctypes.byref(ps2))
                        for _obj in gdi_objs2:
                            try:
                                gdi32.DeleteObject(_obj)
                            except Exception:
                                pass
                    return 0
                elif msg == WM_DESTROY:
                    user32.PostQuitMessage(0)
                    return 0
            except Exception as _e2:
                try:
                    _debug_log("[锁定蒙板] wnd_proc异常 msg=%d: %s" % (msg, _e2))
                except Exception:
                    pass
                return 0
            return user32.DefWindowProcW(hwnd, msg, wParam, lParam)

        wnd_proc_lock_ref = WNDPROC(wnd_proc_lock)
        self._overlay_wndprocs.append(wnd_proc_lock_ref)

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
        # 创建后立即定位到游戏窗口（整个窗口，包括标题栏，和_capture_window坐标系一致）
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

        # === 创建第二个蒙板（人物绿框映射蒙板）===
        className2 = "MapleBotLockOverlay_%d_%d" % (id(self), self._overlay_class_seq)
        wc2 = WNDCLASS()
        wc2.lpfnWndProc = wnd_proc_lock_ref
        wc2.hInstance = hinst
        wc2.hCursor = None
        wc2.hbrBackground = None
        wc2.lpszClassName = className2
        atom2 = user32.RegisterClassW(ctypes.byref(wc2))
        _debug_log("[锁定蒙板] RegisterClass atom=%s" % atom2)
        hwnd2 = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TRANSPARENT,
            className2, "LockOverlay", WS_POPUP | WS_VISIBLE,
            0, 0, 100, 100, None, None, hinst, None)
        _debug_log("[锁定蒙板] CreateWindow hwnd=%s" % hwnd2)
        self._lock_overlay_hwnd = hwnd2
        if hwnd2:
            user32.SetLayeredWindowAttributes(hwnd2, COLOR_MAGENTA, 0, LWA_COLORKEY)
            user32.ShowWindow(hwnd2, 5)
            if self.hwnd and self.window_rect:
                user32.SetWindowPos(hwnd2, -1, wr['left'], wr['top'],
                                    wr['width'], wr['height'], 0x0050)
            user32.UpdateWindow(hwnd2)
            user32.SetTimer(hwnd2, IDT_TIMER, 50, None)  # 20fps刷新，跟手
            _debug_log("[锁定蒙板] 已创建并定位")
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
                    # 同步更新第二个蒙板（人物绿框映射蒙板）位置
                    if getattr(self, '_lock_overlay_hwnd', None):
                        user32.SetWindowPos(self._lock_overlay_hwnd, -1, wr['left'], wr['top'],
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
        # 销毁第二个蒙板（人物绿框映射蒙板）
        if getattr(self, '_lock_overlay_hwnd', None):
            try:
                user32.DestroyWindow(self._lock_overlay_hwnd)
                _debug_log("[锁定蒙板] 已销毁")
            except Exception as e:
                _debug_log("[锁定蒙板] 销毁异常: %s" % e)
            self._lock_overlay_hwnd = None
        try:
            user32.UnregisterClassW(className, hinst)
        except Exception:
            pass
        try:
            user32.UnregisterClassW(className2, hinst)
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
        # 倍率差弹窗的字段也需要保存
        known_ids.add("scale_x_offset")
        known_ids.add("scale_y_offset")
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
            self._prev_num_states = set()  # 重置按键状态，避免旧状态残留导致新键被忽略
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
            _is_offset = fid in ("char_x_offset", "char_y_offset", "scale_x_offset", "scale_y_offset")
            _allow_decimal = fid in ("scale_x_offset", "scale_y_offset")  # 倍率差允许小数点
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
            elif _is_offset and key == 45:  # 负号（仅偏移字段和倍率差字段允许）
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
            elif _allow_decimal and key == 46:  # 小数点（仅倍率差字段允许）
                cur = self._field_values.get(fid, "")
                if getattr(self, '_num_field_replace', False):
                    new_val = "0."
                    self._num_field_replace = False
                elif "." not in cur:
                    new_val = cur + "."  # 没有小数点则添加
                else:
                    new_val = cur  # 已有小数点则不重复添加
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
        poll_vks = list(range(0x30, 0x3A)) + list(range(0x60, 0x6A)) + [0x08, 0x0D, 0x1B, 0xBD, 0x6D, 0xBE, 0x6E]
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
            # minus key - toggle negative sign for offset fields and scale fields
            if fid not in ("char_x_offset", "char_y_offset", "scale_x_offset", "scale_y_offset"):
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
                if fid in ("char_x_offset", "char_y_offset"):
                    self._offset_feedback_start = time.time() * 1000
                    self._offset_feedback_done = False
            return
        elif vk in (0xBE, 0x6E):
            # decimal point - only for scale fields
            if fid not in ("scale_x_offset", "scale_y_offset"):
                return
            cur = self._field_values.get(fid, "")
            if getattr(self, "_num_field_replace", False):
                new_val = "0."
                self._num_field_replace = False
            elif "." not in cur:
                new_val = cur + "."
            else:
                new_val = cur
            if len(new_val) <= 10:
                self._field_values[fid] = new_val
                self._last_input_change = time.time() * 1000
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

    def _load_blue_box(self):
        """加载蓝色框校准配置（一屏范围在小地图上的对应尺寸）"""
        if not os.path.exists(BLUE_BOX_FILE):
            self._blue_box = None
            return
        try:
            with open(BLUE_BOX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "width" in data and "height" in data:
                self._blue_box = {
                    "width": int(data["width"]),
                    "height": int(data["height"]),
                    "bl_ox": int(data.get("bl_ox", 0)),
                    "bl_oy": int(data.get("bl_oy", 0)),
                    "tr_ox": int(data.get("tr_ox", 0)),
                    "tr_oy": int(data.get("tr_oy", 0)),
                }
                print("[绿框] 加载成功: %dx%d 偏移(bl=%d,%d tr=%d,%d)" % (
                    self._blue_box["width"], self._blue_box["height"],
                    self._blue_box["bl_ox"], self._blue_box["bl_oy"],
                    self._blue_box["tr_ox"], self._blue_box["tr_oy"]))
            else:
                self._blue_box = None
        except Exception as e:
            print("[蓝色框] 加载失败:", e)
            self._blue_box = None

    def _save_blue_box(self):
        """保存蓝色框校准配置"""
        if not self._blue_box:
            return
        try:
            with open(BLUE_BOX_FILE, "w", encoding="utf-8") as f:
                json.dump(self._blue_box, f, indent=2)
            print("[绿框] 保存成功: %dx%d 偏移(bl=%d,%d tr=%d,%d)" % (
                self._blue_box["width"], self._blue_box["height"],
                self._blue_box["bl_ox"], self._blue_box["bl_oy"],
                self._blue_box["tr_ox"], self._blue_box["tr_oy"]))
        except Exception as e:
            print("[蓝色框] 保存失败:", e)

    def _start_blue_box_calibration(self):
        """开始绿框校准模式（两点定长方形）：点左下角+右上角，自动算另外两个角连成框。
        如有已保存配置，加载偏移量可直接微调。"""
        if not self.map_area_rect:
            self._add_log("请先绑定窗口检测小地图")
            return
        self._calibrating_blue_box = True
        self._selected_corner = None
        # 如有已保存配置，加载偏移量到角点，可直接微调
        if self._blue_box and "bl_ox" in self._blue_box:
            self._blue_box_corners = {
                "bl": (self._blue_box["bl_ox"], self._blue_box["bl_oy"]),
                "tr": (self._blue_box["tr_ox"], self._blue_box["tr_oy"]),
            }
            self._add_log("绿框校准：已加载保存的点，点击圆点选中后方向键微调，S保存")
            print("[绿框] 进入校准模式（已加载保存偏移量）")
        else:
            self._blue_box_corners = {"bl": None, "tr": None}
            self._add_log("绿框校准：请点击二个点")
            print("[绿框] 进入校准模式（新校准：左下+右上）")

    def _save_and_exit_blue_box_calibration(self):
        """保存绿框校准并退出（不管有没有改动点，有已保存配置就用已有的）"""
        bl = self._blue_box_corners.get("bl")
        tr = self._blue_box_corners.get("tr")
        if bl is not None and tr is not None:
            # 两个点都齐了：计算大小+偏移量，保存
            self._calc_blue_box_from_corners()
            if self._blue_box is not None:
                self._save_blue_box()
                self._add_log("绿框已保存: %dx%d" % (self._blue_box["width"], self._blue_box["height"]))
            else:
                self._add_log("绿框太小，保存失败")
        elif self._blue_box is not None:
            # 点没齐但有已保存配置：用已有的，不改动
            self._add_log("绿框保持原配置: %dx%d" % (self._blue_box["width"], self._blue_box["height"]))
        else:
            self._add_log("没有点也没有已保存配置，无法保存")
        self._calibrating_blue_box = False
        self._selected_corner = None
        print("[绿框] 保存并退出校准模式")

    def _handle_blue_box_click(self, map_x, map_y):
        """校准模式下处理小地图点击：两点定长方形（左下+右上），同方向覆盖，重叠区域无效"""
        if not self._calibrating_blue_box:
            return False
        if not self._player_map_pos:
            self._add_log("未检测到人物光点，无法记录偏移")
            return False
        px, py = self._player_map_pos
        offset_x = int(map_x - px)
        offset_y = int(map_y - py)
        # 点击已有角点附近=选中该方向（用显示位置判断，含自动计算的tl/br）
        for key, val in self._blue_box_corners.items():
            if val is not None:
                ox, oy = val
                cx, cy = px + ox, py + oy
                if abs(map_x - cx) < 8 and abs(map_y - cy) < 8:
                    self._selected_corner = key
                    self._add_log("选中%s角，方向键微调" % self._dir_name(key))
                    return True
        # 方向判断：左下象限直接左下，右上象限直接右上
        # 重叠区域（左上/右下）按主导方向判断（|x|和|y|谁大听谁的），避免第二个点被覆盖
        if offset_x < 0 and offset_y > 0:
            direction = "bl"
            dir_name = "左下"
        elif offset_x > 0 and offset_y < 0:
            direction = "tr"
            dir_name = "右上"
        elif offset_x < 0 and offset_y < 0:
            # 左上重叠区：更偏左→左下，更偏上→右上
            if abs(offset_x) >= abs(offset_y):
                direction = "bl"
                dir_name = "左下"
            else:
                direction = "tr"
                dir_name = "右上"
        elif offset_x > 0 and offset_y > 0:
            # 右下重叠区：更偏右→右上，更偏下→左下
            if abs(offset_x) >= abs(offset_y):
                direction = "tr"
                dir_name = "右上"
            else:
                direction = "bl"
                dir_name = "左下"
        else:
            # 正好在轴上（x=0或y=0）
            if offset_x < 0 or offset_y > 0:
                direction = "bl"
                dir_name = "左下"
            else:
                direction = "tr"
                dir_name = "右上"
        # 记录/覆盖该方向的偏移量
        is_override = self._blue_box_corners[direction] is not None
        self._blue_box_corners[direction] = (offset_x, offset_y)
        self._selected_corner = direction
        self._add_log("%s角: 偏移(%d, %d)%s" % (dir_name, offset_x, offset_y, "（覆盖）" if is_override else ""))
        # 两个点都齐了，计算蓝色框大小
        if all(v is not None for v in self._blue_box_corners.values()):
            self._calc_blue_box_from_corners()
        return True

    def _dir_name(self, key):
        """方向key转中文名（两点定长方形：只有左下/右上两个实点）"""
        return {"bl": "左下", "tr": "右上", "tl": "左上(算)", "br": "右下(算)"}.get(key, key)

    def _calc_blue_box_from_corners(self):
        """两个对角点（左下+右上）齐了，自动算左上角/右下角，得蓝色框宽高"""
        bl = self._blue_box_corners.get("bl")
        tr = self._blue_box_corners.get("tr")
        if bl is None or tr is None:
            return
        bl_ox, bl_oy = bl  # 左下：x<0, y>0
        tr_ox, tr_oy = tr  # 右上：x>0, y<0
        # 左上角=(左下x, 右上y)，右下角=(右上x, 左下y)
        width = tr_ox - bl_ox
        height = bl_oy - tr_oy
        if width > 10 and height > 10:
            self._blue_box = {
                "width": width, "height": height,
                "bl_ox": bl_ox, "bl_oy": bl_oy,
                "tr_ox": tr_ox, "tr_oy": tr_oy,
            }
            self._add_log("绿框大小: %dx%d，S保存" % (width, height))
            print("[绿框] 两点定框: %dx%d 偏移(bl=%d,%d tr=%d,%d)" % (width, height, bl_ox, bl_oy, tr_ox, tr_oy))
        else:
            self._add_log("绿框太小，请重新校准")

    def _handle_blue_box_key(self, key_code):
        """校准模式下键盘方向键微调选中方向的偏移量，S保存，Q退出"""
        if not self._calibrating_blue_box:
            return False
        if self._selected_corner is None or self._blue_box_corners.get(self._selected_corner) is None:
            return False
        ox, oy = self._blue_box_corners[self._selected_corner]
        step = 1
        if key_code == 0x25:  # 左
            ox -= step
        elif key_code == 0x27:  # 右
            ox += step
        elif key_code == 0x26:  # 上
            oy -= step
        elif key_code == 0x28:  # 下
            oy += step
        elif key_code == 0x53:  # S 保存
            self._calc_blue_box_from_corners()
            if self._blue_box is None:
                self._add_log("点没齐，无法保存（需要左下+右上两个点）")
                return True
            self._save_blue_box()
            self._calibrating_blue_box = False
            self._add_log("蓝色框已保存: %dx%d" % (self._blue_box["width"], self._blue_box["height"]))
            return True
        elif key_code == 0x51:  # Q 退出校准
            self._calibrating_blue_box = False
            self._add_log("退出蓝色框校准")
            return True
        else:
            return False
        self._blue_box_corners[self._selected_corner] = (ox, oy)
        if all(v is not None for v in self._blue_box_corners.values()):
            self._calc_blue_box_from_corners()
        return True

    def _calc_blue_box_pos(self, mx, my):
        """绿框(=镜头视野)在小地图上的位置：以光点为中心+边缘钳制(左4/右7/上5/下5)。
        lock_screen_from_dot(大屏幕人物框)与_draw_blue_box(小地图绿框)共用，保证两个框位置永远一致。
        返回(box_x,box_y)；绿框未校准或区域无效返回None。"""
        r = getattr(self, 'map_area_rect', None)
        if not self._blue_box or not r or r.get("width", 0) <= 0:
            return None
        bw, bh = self._blue_box["width"], self._blue_box["height"]
        mw, mh = r["width"], r["height"]
        box_x = int(mx - bw // 2)
        box_y = int(my - bh // 2)
        if box_x < 4:
            box_x = 4
        if box_x > mw - 7 - bw:
            box_x = mw - 7 - bw
        if box_y < 5:
            box_y = 5
        if box_y > mh - 5 - bh:
            box_y = mh - 5 - bh
        return box_x, box_y

    def _draw_blue_box(self, map_frame):
        """在小地图帧上绘制绿框（校准模式：半透明线+圆点；正常模式：实线+无圆点，用偏移量绘制）"""
        if self._calibrating_blue_box:
            if not self._player_map_pos:
                return
            px, py = self._player_map_pos
            h, w = map_frame.shape[:2]
            bl = self._blue_box_corners.get("bl")
            tr = self._blue_box_corners.get("tr")
            # 新校准（两个点都没有）：中间显示提示文字
            if bl is None and tr is None:
                tip = "请点击二个点"
                (tw, th), _ = cv2.getTextSize(tip, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.putText(map_frame, tip, (w // 2 - tw // 2, h // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            # 画两个圆点（左下/右上），选中的变黄
            for key, val in [("bl", bl), ("tr", tr)]:
                if val is None:
                    continue
                ox, oy = val
                cx, cy = int(px + ox), int(py + oy)
                cx = max(0, min(cx, w - 1))
                cy = max(0, min(cy, h - 1))
                color = (0, 255, 255) if key == self._selected_corner else (0, 255, 0)
                cv2.circle(map_frame, (cx, cy), 3, color, -1)
            # 两个点都齐了：画半透明绿线长方形
            if bl is not None and tr is not None:
                tl_pt = (max(0, min(int(px + bl[0]), w - 1)), max(0, min(int(py + tr[1]), h - 1)))
                br_pt = (max(0, min(int(px + tr[0]), w - 1)), max(0, min(int(py + bl[1]), h - 1)))
                bl_pt = (max(0, min(int(px + bl[0]), w - 1)), max(0, min(int(py + bl[1]), h - 1)))
                tr_pt = (max(0, min(int(px + tr[0]), w - 1)), max(0, min(int(py + tr[1]), h - 1)))
                pts = [tl_pt, tr_pt, br_pt, bl_pt]
                # 半透明绿线：先在overlay上画，再混合
                overlay = map_frame.copy()
                cv2.polylines(overlay, [np.array(pts, np.int32).reshape((-1, 1, 2))], True, (0, 255, 0), 1)
                cv2.addWeighted(overlay, 0.4, map_frame, 0.6, 0, map_frame)
        elif self._blue_box and self._player_map_pos:
            # 正常模式：跟随=以光点为中心+到边贴边；死区=冻结绿框(镜头不动)。与lock_screen共用算框方法，两框一致
            px, py = self._player_map_pos
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            follow_pos = self._calc_blue_box_pos(px, py)
            if follow_pos is not None:
                frozen_pos = self._blue_box_deadzone_pos
                if self._camera_state == "deadzone" and frozen_pos is not None:
                    box_x, box_y = frozen_pos
                else:
                    box_x, box_y = follow_pos
                cv2.rectangle(map_frame, (box_x, box_y), (box_x + bw, box_y + bh), (0, 255, 0), 1)


    def _load_bg_regions(self):
        """从配置文件加载检测框位置（data/bg_detect_regions.json），加载失败用默认值"""
        try:
            if os.path.exists(BG_DETECT_REGIONS_FILE):
                with open(BG_DETECT_REGIONS_FILE, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                if isinstance(data, list) and len(data) == 3:
                    self._bg_regions = [dict(r) for r in data]
                    return
        except Exception as e:
            print("[镜头检测] 加载配置失败:", e)
        self._bg_regions = [dict(r) for r in BG_DETECT_DEFAULT_REGIONS]

    def _save_bg_regions(self):
        """保存检测框位置到配置文件（data/bg_detect_regions.json）"""
        try:
            with open(BG_DETECT_REGIONS_FILE, "w", encoding="utf-8") as fp:
                json.dump(self._bg_regions, fp, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[镜头检测] 保存配置失败:", e)

    def _detect_camera_motion(self, frame=None):
        """镜头死区检测：三区域帧间差异对比。直接用主循环已截好的frame（不隐藏蒙板，不闪烁）。
        三个检测区域在屏幕边缘/角落，蒙板绘制内容在中间，不会干扰背景差异检测。
        状态机：deadzone(镜头不动)→following(镜头在动)，进入死区时冻结绿框位置。"""
        if not self._player_map_pos or not self.window_rect:
            return
        if frame is None:
            frame = self._capture_window()
        if frame is None:
            return
        fh, fw = frame.shape[:2]
        motion_count = 0
        for i, reg in enumerate(self._bg_regions):
            x1 = max(0, min(reg["x"], fw - 1))
            y1 = max(0, min(reg["y"], fh - 1))
            x2 = min(fw, x1 + reg["w"])
            y2 = min(fh, y1 + reg["h"])
            # 内缩3像素：排除蒙板自己画在ROI边缘的检测框线，否则框线红/绿变色会被帧差捕捉，形成自激振荡误判
            _PAD = 3
            cx1, cy1, cx2, cy2 = x1 + _PAD, y1 + _PAD, x2 - _PAD, y2 - _PAD
            if cx2 <= cx1 or cy2 <= cy1:
                self._bg_diff_values[i] = 0.0
                continue
            roi = frame[cy1:cy2, cx1:cx2]
            if self._bg_last_frames[i] is not None and self._bg_last_frames[i].shape == roi.shape:
                diff = cv2.absdiff(roi, self._bg_last_frames[i])
                self._bg_diff_values[i] = float(diff.mean())
                if self._bg_diff_values[i] > BG_DIFF_THRESHOLD:
                    motion_count += 1
            self._bg_last_frames[i] = roi.copy()
        # 判断光点是否在移动（光点不动=人物不动=镜头大概率不动）
        dot_moving = False
        if self._last_dot_pos is not None:
            dot_dx = self._player_map_pos[0] - self._last_dot_pos[0]
            dot_dy = self._player_map_pos[1] - self._last_dot_pos[1]
            if abs(dot_dx) > 0 or abs(dot_dy) > 0:
                dot_moving = True
        self._last_dot_pos = (self._player_map_pos[0], self._player_map_pos[1])
        self._bg_motion_count = motion_count  # 保存当前帧几处背景在动，供蒙板三框实时着色
        # 状态机切换（前馈渐变曲线匹配镜头物理：启动0→2约60帧/1秒，匀速保持2，停止2→0约30帧/0.5秒后切死区）
        if dot_moving and motion_count >= BG_MOTION_MIN_REGIONS:
            # 跟随状态：光点在动且3处背景都在动=镜头在动
            self._stop_frame_count = 0  # 重置停止计数器
            self._follow_frame_count += 1  # 跟随帧数递增
            # 前馈启动渐变：0→60帧从0线性增大到2（模拟镜头加速约1秒），60帧后保持2（匀速）
            if self._follow_frame_count <= 60:
                self._feedforward_strength = 2.0 * (self._follow_frame_count / 60.0)
            else:
                self._feedforward_strength = 2.0
            if self._camera_state != "following":
                self._camera_state = "following"
                self._follow_frame_count = 1  # 刚进入跟随，从第1帧开始渐变
                self._feedforward_strength = 2.0 / 60.0  # 第1帧前馈很小
                # 跟随状态：绿框每帧以光点为中心（_calc_blue_box_pos），不用增量更新
                self._blue_box_follow_pos = None
                self._blue_box_deadzone_pos = None
                self._last_follow_dot_pos = (self._player_map_pos[0], self._player_map_pos[1]) if self._player_map_pos else None
                print("[镜头检测] 切到跟随状态（前馈启动渐变0→2约60帧）")
            else:
                # 跟随状态前馈偏移：记录光点移动量，lock_screen_from_dot里用前馈强度系数乘
                if self._player_map_pos:
                    self._last_follow_dot_pos = (self._player_map_pos[0], self._player_map_pos[1])
        else:
            # 光点停了或背景不动：前馈衰减渐变（2→0约30帧/0.5秒，模拟镜头惯性减速），30帧后切死区
            self._follow_frame_count = 0  # 重置跟随计数器
            self._stop_frame_count += 1  # 停止帧数递增
            # 前馈衰减渐变：30帧内从2线性减到0（模拟镜头惯性减速约0.5秒）
            if self._stop_frame_count <= 30:
                self._feedforward_strength = 2.0 * (1.0 - self._stop_frame_count / 30.0)
            else:
                self._feedforward_strength = 0.0
            # 30帧后确认镜头真停了，切死区
            if self._stop_frame_count >= 30 and self._camera_state != "deadzone":
                self._camera_state = "deadzone"
                # 进入死区(镜头停止)：以光点为中心冻结绿框位置，之后绿框钉住、光点在固定框内移动
                _mp_freeze = self._player_map_pos
                if _mp_freeze and self._blue_box:
                    self._blue_box_deadzone_pos = self._calc_blue_box_pos(_mp_freeze[0], _mp_freeze[1])
                self._blue_box_follow_pos = None
                self._feedforward_strength = 0.0
                print("[镜头检测] 切到死区状态（前馈衰减30帧后确认）")

    def lock_screen_from_dot(self):
        """【光点锁定·不用倍率】小地图光点 → 归一化位置 → 游戏屏幕坐标(锁定人物真实坐标).
        原理: 小地图三特征定位裁剪(map_area_rect)映射到显示窗口; 光点在此窗口内归一化(0~1),
              归一化位置 × 游戏窗口尺寸 = 人物在游戏屏幕的坐标. 归一化尺度不变, 任何地图一套通用.
        返回: (screen_x, screen_y) 或 None"""
        r = getattr(self, 'map_area_rect', None)
        if not r or r.get("width", 0) <= 0 or r.get("height", 0) <= 0:
            return None
        if not self._player_map_pos:
            return None
        mx, my = self._player_map_pos  # 修复: 解包元组, 不是重复赋值
        win_w, win_h = getattr(self, '_target_window_size', None) or (0, 0)
        if win_w <= 0 or win_h <= 0:
            # _target_window_size未记录时，用当前window_rect的宽高（窗口实际大小，与蒙板同一坐标系）
            _wr = getattr(self, 'window_rect', None)
            if _wr and _wr.get("width", 0) > 0 and _wr.get("height", 0) > 0:
                win_w, win_h = _wr["width"], _wr["height"]
            else:
                if getattr(self, 'frame_count', 0) % 30 == 0:
                    print("[光点锁定] 失败: 窗口大小无效 target=(%d,%d) rect=%s" % (win_w, win_h, _wr))
                return None
        if self._blue_box:
            # 跟随(following)：绿框以光点为中心+到边贴边；死区(deadzone,镜头不动)：绿框冻结，光点在固定框内归一化
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            follow_pos = self._calc_blue_box_pos(mx, my)
            if follow_pos is None:
                return None
            frozen_pos = self._blue_box_deadzone_pos
            if self._camera_state == "deadzone" and frozen_pos is not None:
                box_x, box_y = frozen_pos  # 镜头不动：绿框钉在进入死区那一刻的位置
            else:
                box_x, box_y = follow_pos  # 跟随/兜底：以光点为中心
                # 跟随状态前馈偏移：绿框沿光点移动方向提前2倍光点移动量，补偿镜头缓冲延迟
                _last_dot = getattr(self, '_last_follow_dot_pos', None)
                if _last_dot and self._player_map_pos:
                    _fdx = self._player_map_pos[0] - _last_dot[0]
                    _fdy = self._player_map_pos[1] - _last_dot[1]
                    if _fdx != 0 or _fdy != 0:
                        _ff = getattr(self, '_feedforward_strength', 2.0)
                        if _ff > 0:
                            box_x += int(_fdx * _ff)  # 前馈渐变：人物在动时强度=2，停了后逐渐减到0
                            box_y += int(_fdy * _ff)
                        # 边缘钳制
                        _r = getattr(self, 'map_area_rect', None)
                        if _r and self._blue_box:
                            _bw, _bh = self._blue_box["width"], self._blue_box["height"]
                            _mw, _mh = _r["width"], _r["height"]
                            box_x = max(4, min(box_x, _mw - 7 - _bw))
                            box_y = max(5, min(box_y, _mh - 5 - _bh))
            # 方案B·直接映射：光点在绿框中的偏移 × 缩放比例(窗口/绿框) = 游戏窗口坐标，不用先算比例再乘窗口
            offset_x = mx - box_x
            offset_y = my - box_y
            offset_x = max(0, min(bw, offset_x))  # 钳制偏移在绿框范围内（等价于比例0~1）
            offset_y = max(0, min(bh, offset_y))
            scale_x = win_w / float(bw) if bw > 0 else 1.0
            scale_y = win_h / float(bh) if bh > 0 else 1.0
            rx = offset_x / float(bw) if bw > 0 else 0.5  # 仅用于日志显示
            ry = offset_y / float(bh) if bh > 0 else 0.5
            mode = "绿框"
        else:
            # 未校准：回退旧方案（整个小地图归一化，到边时不准）
            offset_x = mx
            offset_y = my
            scale_x = win_w / float(r["width"]) if r["width"] > 0 else 1.0
            scale_y = win_h / float(r["height"]) if r["height"] > 0 else 1.0
            rx = mx / float(r["width"])
            ry = my / float(r["height"])
            mode = "全图"
        sx = int(offset_x * scale_x)
        sy = int(offset_y * scale_y)
        # 去掉EMA平滑：直接用当前帧坐标，反应更快不延迟（用户要求跟手，抖动可接受）
        if getattr(self, 'frame_count', 0) % 20 == 0:
            _debug_log("[光点锁定] 光点(%d,%d) %s偏移(%d,%d)缩放(%.2f,%.2f)屏幕(%d,%d)" % (mx, my, mode, offset_x, offset_y, scale_x, scale_y, sx, sy))
        if getattr(self, 'frame_count', 0) % 30 == 0:
            _fz = getattr(self, '_blue_box_deadzone_pos', None)
            _cs = getattr(self, '_camera_state', '?')
            print("[光点锁定] 成功: 光点(%d,%d) state=%s box=(%d,%d) 偏移(%d,%d) 缩放(%.2f,%.2f) 屏幕(%d,%d) win=%dx%d" % (
                mx, my, _cs, box_x, box_y, offset_x, offset_y, scale_x, scale_y, sx, sy, win_w, win_h))
        return (sx, sy)

    def monster_to_map(self, monster_sx, monster_sy):
        """【光点锁定·不用倍率】怪物屏幕坐标 → 小地图显示位置(反用归一化, 不用倍率).
        原理: 人物屏幕坐标(锁定的) + 怪物-人物屏幕偏移 归一化 → 映射到小地图显示框内."""
        r = getattr(self, 'map_area_rect', None)
        if not r or r.get("width", 0) <= 0 or r.get("height", 0) <= 0:
            return None
        pos = self._player_screen_pos
        if not pos:
            return None
        psx, psy = pos
        win_w, win_h = getattr(self, '_target_window_size', None) or (0, 0)
        if win_w <= 0 or win_h <= 0:
            # _target_window_size未记录时，用当前window_rect的宽高（窗口实际大小，与蒙板同一坐标系）
            _wr = getattr(self, 'window_rect', None)
            if _wr and _wr.get("width", 0) > 0 and _wr.get("height", 0) > 0:
                win_w, win_h = _wr["width"], _wr["height"]
            else:
                if getattr(self, 'frame_count', 0) % 30 == 0:
                    print("[光点锁定] 失败: 窗口大小无效 target=(%d,%d) rect=%s" % (win_w, win_h, _wr))
                return None
        dx_ratio = (monster_sx - psx) / float(win_w)
        dy_ratio = (monster_sy - psy) / float(win_h)
        p_rx = psx / float(win_w)
        p_ry = psy / float(win_h)
        rx = p_rx + dx_ratio
        ry = p_ry + dy_ratio
        map_x = int(r["left"] + rx * r["width"])
        map_y = int(r["top"] + ry * r["height"])
        return (map_x, map_y)

    def _get_player_screen_pos(self, frame):
        """获取人物在游戏画面中的坐标: 多特征融合模板匹配(已含每特征offset到脚), 失败宽限期用上次位置."""
        # 1) 多特征融合匹配(每个特征独立offset到人物脚，一致性校验+加权平均)
        match = self._match_character(frame)
        if match:
            mx, my, _ = match
            return (mx, my)  # 已含特征偏移，不再加全局偏移
        # 3) 稳远期: 宽限用上次成功位置
        last_pos = getattr(self, '_last_char_match_pos', None)
        last_time = getattr(self, '_last_char_match_time', 0)
        now_ms = time.time() * 1000
        if last_pos and now_ms - last_time < 1500:
            return last_pos
        # 4) 超时: None
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
        # 启动后3秒内不检测吃药（避免窗口刚加载截图不准导致误加蓝）
        if not hasattr(self, '_pot_start_time'):
            self._pot_start_time = now
        if now - self._pot_start_time < 3000:
            return
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

        # 遮挡判定：游戏窗口不在前台（被其他窗口挡住/最小化）时跳过吃药
        import ctypes
        fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
        occluded = (fg_hwnd != self.hwnd)
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

        # === YOLO怪物检测 + 血条检测（每20ms一次，双检测合并）===
        if now - self._last_yolo_check > 20:
            self._last_yolo_check = now
            frame = self._capture_window()
            if frame is not None:
                yolo_monsters = self._detect_monsters(frame)
                # 怪物特征匹配（手动添加的怪物模板，和YOLO合并显示小地图紫点）
                feature_monsters = self._match_monster(frame) if self._monster_templates else []
                # 合并两个结果，去重（距离太近的合并，保留置信度高的）
                _all_m = yolo_monsters + feature_monsters
                _all_m.sort(key=lambda m: m[4], reverse=True)
                _merged_m = []
                _used_m = [False] * len(_all_m)
                for _i, _m1 in enumerate(_all_m):
                    if _used_m[_i]:
                        continue
                    _merged_m.append(_m1)
                    _used_m[_i] = True
                    _c1x = (_m1[0] + _m1[2]) // 2
                    _c1y = (_m1[1] + _m1[3]) // 2
                    for _j in range(_i + 1, len(_all_m)):
                        if _used_m[_j]:
                            continue
                        _m2 = _all_m[_j]
                        _c2x = (_m2[0] + _m2[2]) // 2
                        _c2y = (_m2[1] + _m2[3]) // 2
                        _dist = ((_c1x - _c2x)**2 + (_c1y - _c2y)**2) ** 0.5
                        if _dist < max(_m1[2]-_m1[0], _m1[3]-_m1[1]) * 0.6:
                            _used_m[_j] = True
                yolo_monsters = _merged_m
                self._monsters = _merged_m
                self._player_screen_pos = self._get_player_screen_pos(frame)
                # === 镜头死区检测：右键单击检测框进入移动模式，再次右键保存 ===
                _rb_down = bool(user32.GetAsyncKeyState(0x02) & 0x8000)  # VK_RBUTTON
                if _rb_down and not self._last_rbutton_down:
                    # 右键刚按下：取光标位置转游戏窗口客户区坐标
                    _cursor = POINT()
                    user32.GetCursorPos(ctypes.byref(_cursor))
                    if self.window_rect:
                        _cx = _cursor.x - self.window_rect['left']
                        _cy = _cursor.y - self.window_rect['top']
                    else:
                        _cx, _cy = _cursor.x, _cursor.y
                    if self._bg_dragging >= 0:
                        # 正在移动模式：再次右键=保存并退出
                        self._save_bg_regions()
                        _di = self._bg_dragging
                        _debug_log("[镜头检测] 保存检测框%d位置(%d,%d)，退出移动模式" % (
                            _di + 1, self._bg_regions[_di]["x"], self._bg_regions[_di]["y"]))
                        self._bg_dragging = -1
                    else:
                        # 没在移动模式：检查右键是否点在某个检测框内
                        for _ri, _rr in enumerate(self._bg_regions):
                            if _rr["x"] <= _cx <= _rr["x"] + _rr["w"] and _rr["y"] <= _cy <= _rr["y"] + _rr["h"]:
                                self._bg_dragging = _ri
                                _debug_log("[镜头检测] 进入检测框%d移动模式，再次右键保存" % (_ri + 1))
                                break
                self._last_rbutton_down = _rb_down
                # 移动模式下：检测框跟随光标（以光标为中心）
                if self._bg_dragging >= 0:
                    _cursor2 = POINT()
                    user32.GetCursorPos(ctypes.byref(_cursor2))
                    if self.window_rect:
                        _mx = _cursor2.x - self.window_rect['left']
                        _my = _cursor2.y - self.window_rect['top']
                    else:
                        _mx, _my = _cursor2.x, _cursor2.y
                    _db = self._bg_regions[self._bg_dragging]
                    _db["x"] = max(0, _mx - _db["w"] // 2)
                    _db["y"] = max(0, _my - _db["h"] // 2)
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
                # 怪物数据记住最后一个：检测为空时，宽限期2秒内保留上次结果（避免偶发漏检导致怪物点消失）
                if merged:
                    self._monsters = merged
                    self._last_monsters_time = time.time()
                else:
                    last_mtime = getattr(self, '_last_monsters_time', 0)
                    if time.time() - last_mtime < 2.0 and self._monsters:
                        pass  # 宽限期内保留上次结果
                    else:
                        self._monsters = []

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
            # 启动人物坐标跟踪线程（暂时注释，排查绑定问题）
            # self._start_player_track()
        else:
            self._add_log("未找到游戏窗口")
            print("[窗口绑定] 未找到游戏窗口")

    def run(self):
        self._boot_t = time.time()
        print("[冷启动] %.2fs run开始" % (time.time()-self._boot_t))
        win = "PLAY AND HAPPY"
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        print("[冷启动] %.2fs namedWindow完成" % (time.time()-self._boot_t))
        cv2.setMouseCallback(win, self._on_mouse)
        self._win_name = win
        self._win_size = (UI_W, UI_H)
        # 防冷启动灰屏：窗口创建后先渲染一帧并泵一次Windows消息，避免第一帧检测耗时过长被系统判未响应（v73验证）
        cv2.imshow(win, self._ui_bg)
        cv2.waitKey(1)
        print("[冷启动] %.2fs 首帧泵消息完成" % (time.time()-self._boot_t))
        while True:
            if self.frame_count <= 3: print("[冷启动] %.2fs 第%d帧开始" % (time.time()-self._boot_t, self.frame_count))
            try:
                map_area = self._capture_map()
            except Exception as _e:
                print("[主循环] _capture_map异常: %s" % _e)
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
            # FPS统计（每秒打印一次，定位检测慢的原因）
            if not hasattr(self, '_fps_last_time'):
                self._fps_last_time = time.time()
                self._fps_count = 0
                self._fps_capture_time = 0
                self._fps_match_time = 0
            self._fps_count += 1
            _now_fps = time.time()
            if _now_fps - self._fps_last_time >= 1.0:
                _fps = self._fps_count / (_now_fps - self._fps_last_time)
                print(f"[FPS统计] 帧率={_fps:.1f} 截图总耗时={self._fps_capture_time*1000:.0f}ms 匹配总耗时={self._fps_match_time*1000:.0f}ms")
                self._fps_last_time = _now_fps
                self._fps_count = 0
                self._fps_capture_time = 0
                self._fps_match_time = 0
            if self._auto_refresh and self.frame_count % 30 == 0:
                self._detect_minimap(debug=False)
            # 窗口大小固定：每30帧检测一次，变动则拉回
            if self.frame_count % 30 == 0:
                self._ensure_window_size()
            player_pos = self.find_player_dot(map_area)  # 每帧都检测光点
            # 光点不做EMA平滑（保证轻微移动也能反映到比例上），检测失败时用上一帧位置
            if player_pos is not None:
                self._player_map_pos = player_pos
                self._last_smooth_dot = player_pos
            else:
                _last_dot = getattr(self, '_last_smooth_dot', None)
                if _last_dot is not None:
                    self._player_map_pos = _last_dot
            # 保存小地图坐标供战斗逻辑判断平台
            # 【模块B】独立检测人物屏幕位置+怪物（不依赖运行状态，脚本启动就工作）
            if self.hwnd:  # 人物屏幕位置每帧检测（绿框跟随人物实时刷新）
                try:
                    _t0 = time.time()
                    _frame = self._capture_window()
                    _t1 = time.time()
                    self._fps_capture_time += (_t1 - _t0)
                    if _frame is not None:
                        _t2 = time.time()
                        self._player_screen_pos = self._get_player_screen_pos(_frame)
                        _t3 = time.time()
                        self._fps_match_time += (_t3 - _t2)
                        # 每帧触发蒙板重绘（人物框/怪物框实时跟随，不依赖100ms定时器）
                        if getattr(self, '_overlay_hwnd', None):
                            user32.InvalidateRect(self._overlay_hwnd, None, True)
                        # 怪物特征匹配（每帧调用，不管运行还是不运行都调用，确保怪物特征显示点总是能出来且流利）
                        # 注意：这里只更新_monster_feature_matches用于显示特征点，不合并到怪物列表
                        # 有条件if self._monster_templates，只有保存了怪物特征模板才调用，不会空枪也不会卡
                        if self._monster_templates:
                            try:
                                self._match_monster(_frame)
                            except Exception as _e:
                                print("[主循环] 怪物特征匹配异常:", _e)
                        # 不运行时也检测怪物（YOLO每2帧一次减少卡顿，怪物特征匹配每帧一次保证跟手）
                        if not self._running:
                            yolo_monsters = self._detect_monsters(_frame) if self.frame_count % 2 == 0 else []
                            # 怪物特征匹配（手动添加的怪物模板，和YOLO合并显示小地图紫点，每帧一次保证跟手）
                            feature_monsters = self._match_monster(_frame) if self._monster_templates else []
                            # 合并两个结果，去重（距离太近的合并，保留置信度高的）
                            all_monsters = yolo_monsters + feature_monsters
                            all_monsters.sort(key=lambda m: m[4], reverse=True)
                            merged = []
                            used = [False] * len(all_monsters)
                            for i, m1 in enumerate(all_monsters):
                                if used[i]:
                                    continue
                                merged.append(m1)
                                used[i] = True
                                c1x = (m1[0] + m1[2]) // 2
                                c1y = (m1[1] + m1[3]) // 2
                                for j in range(i + 1, len(all_monsters)):
                                    if used[j]:
                                        continue
                                    m2 = all_monsters[j]
                                    c2x = (m2[0] + m2[2]) // 2
                                    c2y = (m2[1] + m2[3]) // 2
                                    dist = ((c1x - c2x)**2 + (c1y - c2y)**2) ** 0.5
                                    if dist < max(m1[2]-m1[0], m1[3]-m1[1]) * 0.6:
                                        used[j] = True
                            self._monsters = merged
                except Exception as _e:
                    print("[主循环] 帧检测异常:", _e)
            # 【模块B】自动校准scale比例（人物移动时记录屏幕和小地图变化，越跑越准）
            self._update_scale_calibration()
            # 【模块B】自动记录端点已取消，改用手动同屏三点校准（不跨画面更准）
            # self._auto_calibrate_edges()

            # 【模块B】蒙板拖动检测（仅stage=1时，红绿蓝三点跟随人物移动，可拖动绿点蓝点调偏移）
            if self._auto_calib_stage == 1:
                # 实时更新基点位置（红色基点覆盖人物特征，跟随人物移动）
                # 小地图坐标[2],[3]始终用光点实时更新(准)，不受屏幕位置匹配失败影响，避免红点慢一拍
                if self._player_map_pos:
                    _pmx, _pmy = self._player_map_pos[0], self._player_map_pos[1]
                else:
                    _pmx = _pmy = 0
                if self._player_screen_pos:
                    _psx, _psy = self._player_screen_pos[0], self._player_screen_pos[1]
                    self._auto_calib_base = (_psx, _psy, _pmx, _pmy)  # 屏幕+光点都更新
                elif self._player_map_pos:
                    # 屏幕位置匹配失败时，仍用小地图光点更新基点小地图坐标[2],[3]，红点跟上光点不慢一拍
                    _ob = self._auto_calib_base
                    _psx = _ob[0] if _ob else 0
                    _psy = _ob[1] if _ob else 0
                    self._auto_calib_base = (_psx, _psy, _pmx, _pmy)
                # 绿点蓝点屏幕坐标 = 基点 + 相对偏移（跟着人物一起动）
                base = self._auto_calib_base
                if base:
                    bx, by = base[0], base[1]
                    goff = getattr(self, '_auto_calib_green_offset', (400, 0))
                    boff = getattr(self, '_auto_calib_blue_offset', (0, -400))
                    green_scr = (bx + goff[0], by + goff[1])
                    blue_scr = (bx + boff[0], by + boff[1])
                else:
                    green_scr = None
                    blue_scr = None
                # 鼠标拖动检测（全局GetAsyncKeyState，不依赖蒙板窗口消息）
                left_down = user32.GetAsyncKeyState(0x01) & 0x8000  # VK_LBUTTON
                cursor = POINT()
                user32.GetCursorPos(ctypes.byref(cursor))
                # 全局坐标转窗口坐标（减窗口左上角，和蒙板绘制/_capture_window一致）
                if self.window_rect:
                    mx = cursor.x - self.window_rect['left']
                    my = cursor.y - self.window_rect['top']
                else:
                    mx, my = cursor.x, cursor.y
                if left_down and not self._auto_calib_dragging:
                    # 左键刚按下，检测是否点中绿点或蓝点（±12px范围）
                    if green_scr and abs(mx - green_scr[0]) <= 18 and abs(my - green_scr[1]) <= 18:
                        self._auto_calib_dragging = 'green'
                    elif blue_scr and abs(mx - blue_scr[0]) <= 18 and abs(my - blue_scr[1]) <= 18:
                        self._auto_calib_dragging = 'blue'
                elif left_down and self._auto_calib_dragging:
                    # 拖动中，更新相对偏移（绿/蓝圈可上下左右自由移动，基点跟随人物）
                    if base:
                        bx, by = base[0], base[1]
                        if self._auto_calib_dragging == 'green':
                            self._auto_calib_green_offset = (mx - bx, my - by)  # 绿圈可上下左右移动
                        elif self._auto_calib_dragging == 'blue':
                            self._auto_calib_blue_offset = (mx - bx, my - by)  # 蓝圈可上下左右移动
                elif not left_down and self._auto_calib_dragging:
                    # 左键松开，结束拖动
                    self._auto_calib_dragging = None

            # 【模块B】模板匹配跟踪（stage>=2时，每5帧匹配一次，跟踪特色位置画绿/蓝圆）
            if self._auto_calib_stage >= 2 and self.frame_count % 5 == 0:
                self._match_calib_templates()

            if self.recording_platform:
                _debug_log("[录制A] player_pos=%s points_count=%d recording=%s" % (str(player_pos), len(self.platform_points), self.recording_platform))  # 调试日志：验证录制时人物光点是否有效
            if self.recording_platform and player_pos:
                # 同一X位置(差值<1px)的新点覆盖旧点，以后画的为准；移动超过1px就记录新点，提高轨迹密度
                if self.platform_points and abs(self.platform_points[-1][0] - player_pos[0]) < 1:
                    self.platform_points[-1] = player_pos
                else:
                    self.platform_points.append(player_pos)
                    _debug_log("[录制C] 新增点 pos=%s 总点数=%d" % (str(player_pos), len(self.platform_points)))
            if self.recording_ladder and player_pos:
                self.ladder_points.append(player_pos)

            self._random_step(player_pos)
            self._check_hotkeys()
            # 蓝色框校准模式：方向键微调选中角点，S保存，Q退出（与输入框一致的set差集边沿触发，避免字典重置bug）
            if self._calibrating_blue_box:
                if not hasattr(self, '_bluebox_prev_keys'):
                    self._bluebox_prev_keys = set()
                _bluebox_vks = [0x25, 0x26, 0x27, 0x28, 0x53, 0x51]
                _current = set()
                for _vk in _bluebox_vks:
                    if user32.GetAsyncKeyState(_vk) & 0x8000:
                        _current.add(_vk)
                _new_keys = _current - self._bluebox_prev_keys
                self._bluebox_prev_keys = _current
                for _vk in _new_keys:
                    self._handle_blue_box_key(_vk)

            # === 自动吃药检测（HP/MP低于阈值） ===
            try:
                self._check_auto_potion()
            except Exception as e:
                print("[自动吃药] 异常:", e)
            try:
                self._combat_tick()
            except Exception as e:
                print("[战斗] 异常:", e)

            # === tkinter独立窗口事件泵（仅在有窗口打开时调用，避免与OpenCV冲突）===
            try:
                if hasattr(self, '_tk_root') and self._tk_root is not None:
                    has_win = (getattr(self, '_save_window', None) is not None or
                               getattr(self, '_plan_window', None) is not None or
                               getattr(self, '_clear_window', None) is not None or
                               getattr(self, '_char_feature_window', None) is not None or
                               getattr(self, '_monster_feature_window', None) is not None)
                    if has_win:
                        # 处理所有待处理事件（最多10ms，避免阻塞主循环），提高弹窗输入/移动响应速度
                        # 注意：必须循环调用dooneevent直到没有事件或超时，否则after定时器事件可能不被处理
                        _tk_start = time.time()
                        _tk_count = 0
                        while time.time() - _tk_start < 0.010:
                            if not self._tk_root.dooneevent(0):  # 0 = 不等待，有事件就处理
                                # 没有事件时短暂sleep，避免CPU占用过高
                                time.sleep(0.001)
                                _tk_count += 1
                                if _tk_count > 3:  # 连续3次没有事件就退出
                                    break
                            else:
                                _tk_count = 0  # 有事件时重置计数
            except Exception as e:
                _debug_log("[方案窗口] tk update异常: %s" % e)

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
            # 人物位置黄点：不运行时也更新到蒙板（偏移反馈闪烁需要char_pos）
            if self._monster_overlay_data is None:
                self._monster_overlay_data = {}
            if self._player_screen_pos:
                self._monster_overlay_data["char_pos"] = self._player_screen_pos
            # 同步特征单独匹配结果到蒙板（显示每个特征的匹配点+数字，方便发现误判）
            self._monster_overlay_data["char_feature_matches"] = self._char_feature_matches
            self._monster_overlay_data["monster_feature_matches"] = self._monster_feature_matches
            # 调试日志：确认怪物特征匹配结果（每2秒一次）
            _now_sync = time.time()
            if not hasattr(self, '_last_monster_sync_log') or _now_sync - self._last_monster_sync_log > 2:
                self._last_monster_sync_log = _now_sync
                _debug_log("[蒙板同步] 人物特征点%d个 怪物特征点%d个 怪物匹配值:%s" % (
                    len(self._char_feature_matches), len(self._monster_feature_matches),
                    str([(f[0], f[1], f[2]) for f in self._monster_feature_matches[:3]])))
            if self._running:
                try:
                    if self._monster_overlay_data is None:
                        self._monster_overlay_data = {}
                    # 同步怪物和人物位置到蒙板
                    self._monster_overlay_data["monsters"] = self._monsters
                    self._monster_overlay_data["monster_hp_bars"] = self._monster_hp_bars
                except Exception as e:
                    print("[蒙板] 同步异常:", e)

            # === 准星拖拽绑定检测 ===
            if self._drag_crosshair:
                # 处理pygame事件，避免窗口无响应
                if self._crosshair_pygame_inited:
                    pygame.event.pump()
                left_down = user32.GetAsyncKeyState(0x01) & 0x8000  # VK_LBUTTON
                if left_down:
                    # 跟随全局鼠标位置（不限制在UI窗口内，可拖到其他窗口）
                    cursor = POINT()
                    user32.GetCursorPos(cursor)
                    # 用pygame透明置顶窗口显示准星，可拖到屏幕任意位置
                    if self._crosshair_pygame_hwnd is None:
                        self._create_crosshair_window()  # 首次拖拽时创建窗口
                    self._update_crosshair_window(cursor.x, cursor.y)  # 更新窗口位置到鼠标位置
                    # 同时更新UI窗口上的准星位置（用于UI窗口内显示）
                    hwnd_ui = user32.FindWindowW(None, "PLAY AND HAPPY")
                    if hwnd_ui:
                        client_cursor = POINT(cursor.x, cursor.y)
                        user32.ScreenToClient(hwnd_ui, ctypes.byref(client_cursor))
                        self._crosshair_pos = (client_cursor.x, client_cursor.y)
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
                    # 拖拽结束，销毁pygame准星窗口
                    self._destroy_crosshair_window()

            try:
                frame = self.draw(map_area, player_pos)
                cv2.imshow(win, frame)
            except Exception as e:
                print("draw error:", e)
                cv2.imshow(win, self._ui_bg)

            key = cv2.waitKey(10) & 0xFF
            if self.frame_count <= 3: print("[冷启动] %.2fs 第%d帧waitKey完成 key=%d" % (time.time()-self._boot_t, self.frame_count, key))
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
        # 停止人物坐标跟踪线程
        self._stop_player_track()
        cv2.destroyAllWindows()
        print("Final:", len(self.platforms), "platforms,", len(self.ladders), "ladders")



if __name__ == "__main__":
    # === 管理员权限检查 ===
    # 游戏(冒险岛怀旧服)以管理员权限运行，UIPI会阻止普通权限进程向管理员进程发送模拟输入
    # 必须以管理员权限启动bot，否则按键/加药全部无效
    import ctypes as _ctypes, sys as _sys
    # 启动时自动修正工作目录（防止管理员重启后工作目录变为System32）
    if getattr(_sys, "frozen", False):
        _exe_dir = os.path.dirname(os.path.abspath(_sys.executable))
        if os.getcwd() != _exe_dir:
            os.chdir(_exe_dir)
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
            _workdir = os.path.dirname(os.path.abspath(_sys.executable)) if getattr(_sys, "frozen", False) else os.getcwd()
            _ctypes.windll.shell32.ShellExecuteW(None, "runas", _sys.executable, _params, _workdir, 1)
        except Exception as _e:
            print("[权限] 自动提升失败: %s" % _e)
            print("[权限] 请右键 MapleBot.exe 选择'以管理员身份运行'")
            try:
                input("按回车退出...")
            except:
                pass
        _sys.exit()
    print("[权限] 已以管理员权限运行，模拟输入可正常发送到游戏")
    try:
        MinimapRouteRecorder().run()
    except Exception as _e:
        import traceback
        _err = traceback.format_exc()
        print("[全局异常] %s" % _e)
        _debug_log("[全局异常] %s" % _err)
        _debug_log(_err)
        # 异常后等待3秒让用户看到错误，然后退出（避免input卡住表现为未响应）
        import time
        time.sleep(3)

