"""
Minimap Route Recorder - 榧犳爣鎿嶄綔鐗?
Auto lock game window + blue border detection (projection) + ROI dot tracking
涓夊鏂规锛坮oute_1/2/3锛夛紝姣忓鐙珛瀛樺偍骞冲彴+姊瓙锛涙柟寮忥細鎵嬪姩/闅忔満
鎿嶄綔锛氱函榧犳爣鐐瑰嚮锛岀涓€鎺?骞冲彴/姊瓙/娓呭钩鍙?娓呮瀛?淇濆瓨/鎵嬪姩/鍒锋柊
      绗簩鎺?鏂规1/鏂规2/鏂规3/娓呮柟妗?鏂瑰紡鍒囨崲
"""
import ctypes
import struct
import mss
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
import os
import json
import time
import sys
import subprocess
import queue
import random
import threading

# === 蹇呴』鍦ㄥ垱寤轰换浣曠獥鍙ｄ箣鍓嶈缃?DPI 鎰熺煡锛屽惁鍒欓珮DPI缂╂斁涓嬭挋鏉垮潗鏍囬敊浣?===
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

def _debug_log(msg):
    """鍐欒皟璇曟棩蹇楀埌鏂囦欢锛宔xe鏃犳帶鍒跺彴鏃剁敤銆傝秴杩?0MB鑷姩杞浆澶囦唤銆?""
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

# 鏃犵紦鍐茶緭鍑猴紝鏂逛究瀹炴椂鐪嬫棩蹇楋紙windowed妯″紡涓媠tdout涓篘one锛岃烦杩囷級
if sys.stdout is not None:
    sys.stdout.reconfigure(line_buffering=True)

def resource_path(relative_path):
    """鑾峰彇璧勬簮鏂囦欢璺緞锛屽吋瀹筆yInstaller鎵撳寘"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def load_png(path):
    """鍔犺浇PNG锛堜繚鐣檃lpha閫忔槑閫氶亾锛夛紝鍏煎涓枃璺緞"""
    try:
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        return img
    except Exception:
        return None

def draw_asset(frame, asset, x, y, w, h):
    """灏嗙礌鏉愮粯鍒跺埌frame涓婏紝鏀寔PNG閫忔槑閫氶亾娣峰悎"""
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
    """缁樺埗鍦嗚鐭╁舰锛坱hickness=-1涓哄～鍏咃級"""
    r = min(radius, w // 2, h // 2)
    # 鍥涗釜瑙?
    cv2.circle(img, (x + r, y + r), r, color, thickness)
    cv2.circle(img, (x + w - r, y + r), r, color, thickness)
    cv2.circle(img, (x + r, y + h - r), r, color, thickness)
    cv2.circle(img, (x + w - r, y + h - r), r, color, thickness)
    # 涓棿鐭╁舰
    cv2.rectangle(img, (x + r, y), (x + w - r, y + h), color, thickness)
    cv2.rectangle(img, (x, y + r), (x + w, y + h - r), color, thickness)

def app_dir():
    """鑾峰彇绋嬪簭鎵€鍦ㄧ洰褰曪紙鐢ㄤ簬鍙啓鏁版嵁锛夛紝鍏煎PyInstaller"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

os.chdir(app_dir())

DISPLAY_SCALE = 1
WINDOW_TITLE = "鍐掗櫓宀涙€€鏃ф湇"
WINDOW_KEYWORDS = ["鍐掗櫓宀?]  # 鑷姩缁戝畾鍙尮閰嶅啋闄╁矝锛屽叾浠栫獥鍙ｇ敤鍑嗘槦鎵嬪姩缁戝畾
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
    """鏋氫妇鎵€鏈夐《灞傜獥鍙ｏ紝鎵炬爣棰樺寘鍚叧閿瘝鐨勬父鎴忕獥鍙?""
    global _enum_result
    _enum_result = []
    try:
        user32.EnumWindows(_enum_windows_cb, 0)
    except Exception as e:
        print("[绐楀彛鏋氫妇] 寮傚父:", e)
        return None
    if _enum_result:
        for hwnd, title in _enum_result:
            if "鍐掗櫓宀? in title:
                return hwnd
        return _enum_result[0][0]
    return None
# 鍐呴儴灏忓湴鍥炬覆鏌撳昂瀵革紙娓叉煋鍚庣缉鏀惧埌UI鍖哄煙锛?
FIXED_W = 340
MAP_H = 250
BTN_BAR_H = 77
BTN_ROW_H = BTN_BAR_H // 2
BTN_COLS = 4
BTN_W = FIXED_W // BTN_COLS
FIXED_H = MAP_H + BTN_BAR_H
DROPDOWN_ITEM_H = 24

# === UI 鏁翠綋缂╂斁 ===
# === UI 鏁翠綋灏哄锛堟寜鍙傝€冨浘 鏁堟灉鍥句竴.png 461x900锛?==
UI_W = 461
UI_H = 900

def _s(v):
    """fight/potion椤电敤锛氬師330x566璁捐缂╂斁鍒癠I灏哄"""
    return int(round(v * UI_W / 330.0))

# === 灏忓湴鍥惧唴瀹瑰尯鍩?===
UI_MAP_X = 29
UI_MAP_Y = 131
UI_MAP_W = 403  # 灏忓湴鍥炬樉绀哄搴?
UI_MAP_H = 279  # 灏忓湴鍥炬樉绀洪珮搴?
UI_MAP_SCALE = UI_MAP_W / FIXED_W

# === 鎸夐挳锛堝弬鑰冨浘绮剧‘鍧愭爣锛?==
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

# === 鍋忕Щ杈撳叆妗?===
# 鏁板瓧瀹為檯缁樺埗鍖哄煙锛堝皬妗嗭級
OFFSET_X_DRAW = (228, 653, 87, 22)
OFFSET_Y_DRAW = (324, 654, 85, 22)
# 鐐瑰嚮鍖哄煙锛堟墿澶э紝鍖呭惈"X鍋忕Щ/Y鍋忕Щ"鏍囩鏂囧瓧锛?
OFFSET_X_CLICK = (228, 628, 87, 44)
OFFSET_Y_CLICK = (319, 628, 85, 45)

# === 宸ュ叿鏍忥紙灏忓湴鍥句笂鏂癸級===
BTN_REFRESH = (28, 103, 57, 26)
BTN_MANUAL = (91, 104, 56, 25)
BTN_PLAN_TOOLBAR = (156, 104, 57, 25)
# 銆愭ā鍧桞銆戣嚜鍔ㄦ牎鍑嗘寜閽紙鍚屽睆涓夌偣鏍″噯锛氬熀鐐?鍙?00+涓?00锛屾寜鏁堟灉鍥捐皟鏁翠綅缃ぇ灏忥級
BTN_CALIB_AUTO = (216, 104, 41, 25)

# === 绐楀彛缁戝畾 + 鍑嗘槦 ===
BTN_WINBIND = (25, 826, 124, 46)
CROSSHAIR_POS = (116, 849)
CROSSHAIR_SIZE = 30

# === 鏃ュ織鍖哄煙 ===
UI_LOG_X = 166
UI_LOG_Y = 754
UI_LOG_W = 274
UI_LOG_H = 135
UI_LOG_CONTENT_Y = 776

# === 宸茬粦绐楀彛涓嬫媺 ===
UI_BOUND_X = 31
UI_BOUND_Y = 777
UI_BOUND_W = 114
UI_BOUND_H = 24

# === 浜虹墿鐗瑰緛涓嬫媺闈㈡澘 ===
CHAR_DD_X = 54
CHAR_DD_W = 180
CHAR_DD_SCROLL_W = 22
CHAR_DD_ITEM_H = 26
CHAR_DD_VISIBLE = 5
CHAR_DD_ITEMS = 10
CHAR_DD_FEAT_PER_PAGE = 4
YELLOW_H_LOW = 20
YELLOW_H_HIGH = 40
YELLOW_S_LOW = 80
YELLOW_V_LOW = 150

VK_F5 = 0x74
VK_F6 = 0x75
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78
VK_F10 = 0x79
VK_F11 = 0x7A  # 鍧愭爣娴嬮噺鐑敭
VK_F12 = 0x7B

# 娓告垙鎺у埗鎸夐敭锛堝啋闄╁矝榛樿锛屽彲鏍规嵁瀹為檯璁剧疆璋冩暣锛?
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

# === 浜虹墿鐗瑰緛妯℃澘 ===
CHAR_TEMPLATE_DIR = os.path.join(DATA_DIR, "char_templates")
os.makedirs(CHAR_TEMPLATE_DIR, exist_ok=True)
CHAR_TEMPLATE_META = os.path.join(CHAR_TEMPLATE_DIR, "meta.json")
CHAR_MAX_TEMPLATES = 10
CHAR_MATCH_THRESHOLD = 0.70

# === 鎵撴€?鑽搧 杈撳叆妗嗛厤缃?===
INPUT_CONFIG_FILE = os.path.join(DATA_DIR, "fight_potion_config.json")
YOLO_CONFIG_FILE = os.path.join(DATA_DIR, "yolo_config.json")
INPUT_FONT = cv2.FONT_HERSHEY_SIMPLEX
INPUT_FONT_SCALE = 0.5 * UI_W / 330.0
INPUT_FONT_THICKNESS = 1
INPUT_TEXT_COLOR = (40, 40, 40)  # BGR 娣辫壊鏂囧瓧
INPUT_FOCUS_COLOR = (0, 170, 255)  # BGR 姗欒壊鑱氱劍杈规

# 鎵撴€〉瀛楁瀹氫箟 (x, y, w, h, type, id) 鈥?鍧愭爣鐢辨柊鑳屾櫙(461x900)鐧借壊鏂规绮剧‘妫€娴?
# type: "key"=鎸夐敭褰曞叆, "num"=鏁板瓧褰曞叆
# 鍧愭爣鐢辨柊鑳屾櫙(ui_tab_fight.png, 462x900)鐧借壊杈撳叆妗嗙簿纭娴?
FIGHT_FIELDS = [
    # 涓绘敾
    (100, 155, 54, 26, "key", "atk1_key"),
    (211, 154, 108, 30, "num", "atk1_interval"),
    (371, 154, 74, 29, "num", "atk1_distance"),
    # 缇ゆ敾
    (100, 198, 54, 26, "key", "aoe_key"),
    (211, 196, 110, 29, "num", "aoe_interval"),
    (371, 195, 74, 29, "num", "aoe_distance"),
    # 璺宠穬 + 鎶€鑳介殢鏈烘椂闂?
    (100, 251, 54, 26, "key", "jump_key"),
    (306, 242, 138, 27, "num", "skill_random"),
    # 鐬Щ + 鐬Щ璺濈锛堢敤浜庝笂/涓嬪眰骞冲彴锛屼笉濉?涓嶅惎鐢級
    (100, 294, 54, 26, "key", "teleport_key"),
    (243, 294, 62, 26, "num", "teleport_distance"),
    # BUFF 1-6锛堟妧鑳?鍐峰嵈/鍚庢憞锛?
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
    # BUFF鎶€鑳介殢鏈烘椂闂?
    (229, 706, 182, 28, "num", "buff_random"),
]

# 璺嚎椤靛瓧娈靛畾涔?鈥?浜虹墿X/Y鍋忕Щ锛堢偣鍑昏寖鍥村姞澶э紝瑕嗙洊鍋忕Щ鏍囩涓嬪崐閮ㄥ垎锛?
ROUTE_FIELDS = [
    (OFFSET_X_CLICK[0], OFFSET_X_CLICK[1], OFFSET_X_CLICK[2], OFFSET_X_CLICK[3], "num", "char_x_offset"),
    (OFFSET_Y_CLICK[0], OFFSET_Y_CLICK[1], OFFSET_Y_CLICK[2], OFFSET_Y_CLICK[3], "num", "char_y_offset"),
]

# 鑽搧椤靛瓧娈靛畾涔?(x, y, w, h, type, id) 鈥?鍧愭爣鐢辨柊鑳屾櫙(461x900)鐧借壊鏂规绮剧‘妫€娴?
POTION_FIELDS = [
    # Hp / Mp / 瀹犵墿椋?
    (101, 174, 119, 43, "key", "hp_key"),
    (314, 177, 124, 37, "num", "hp_value"),
    (101, 226, 119, 43, "key", "mp_key"),
    (314, 229, 124, 38, "num", "mp_value"),
    (101, 286, 119, 43, "key", "pet_key"),
    (314, 287, 124, 38, "num", "pet_cd"),
    # 1-5鎸夐敭锛堝喎鍗存鍔犲锛?
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
    # 鑽搧鎶€鑳介殢鏈烘椂闂?
    (213, 673, 218, 31, "num", "potion_random"),
]

# 鎸夐挳棰滆壊 (BGR)
BTN_GREEN = (0, 165, 0)
BTN_BLUE = (210, 130, 0)
BTN_BLACK = (48, 48, 48)
BTN_ORANGE = (0, 135, 225)
BTN_WHITE = (255, 255, 255)

# 瀹屾暣铏氭嫙閿爜鈫掗敭鍚嶆槧灏勶紙鐢ㄤ簬GetAsyncKeyState鎸夐敭鎹曡幏锛?
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
# 杞鎹曡幏鏃舵娴嬬殑閿爜鍒楄〃锛堟寜浼樺厛绾ф帓搴忥紝淇グ閿斁鍚庨潰閬垮厤璇Е锛?
VK_POLL_LIST = (
    [0x70+i for i in range(4)] +  # F1-F4 (F5-F12鐣欎綔鐑敭涓嶆崟鑾?
    [0x30+i for i in range(10)] +  # 0-9
    [0x41+i for i in range(26)] +  # A-Z
    [0x60+i for i in range(10)] +  # num0-9
    [0x20, 0x0D, 0x09] +  # space enter tab (backspace/esc鍗曠嫭澶勭悊涓嶆崟鑾?
    [0x21, 0x22, 0x23, 0x24, 0x2D, 0x2E] +  # pgup pgdn end home insert delete
    # 鏂瑰悜閿?ScrollLock/Pause/PrintScreen 涓嶆崟鑾凤紝閬垮厤鍐茬獊
    [0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE] +  # 绗﹀彿
    [0x6A, 0x6B, 0x6D, 0x6E, 0x6F] +  # 灏忛敭鐩樿繍绠?
    [0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5]  # 宸﹀彸淇グ閿?
)

# 鎸夐挳甯冨眬锛?鏂囧瓧, 鑳屾櫙鑹? 鏄惁鏈変笅鎷?
BTN_ROW1 = [
    ("骞冲彴", BTN_GREEN, False),
    ("姊瓙", BTN_BLUE, False),
    ("淇濆瓨", BTN_BLACK, True),
    ("鏂规", BTN_ORANGE, True),
]
BTN_ROW2 = [
    ("娓呴櫎", BTN_GREEN, False),   # 娓呭钩鍙?
    ("娓呴櫎", BTN_BLUE, False),    # 娓呮瀛?
    ("妯″紡", BTN_BLACK, True),
    ("娓呴櫎", BTN_ORANGE, True),   # 娓呮柟妗?
]


def route_files(route_id):
    """杩斿洖鎸囧畾鏂规鐨勫钩鍙版枃浠跺拰姊瓙鏂囦欢璺緞"""
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
    """浣庣骇閿洏閽╁瓙鍏ㄥ眬鐑敭锛堜富绾跨▼鐗堬級锛岀粫杩?UIPI锛屾父鎴忓墠鍙颁篃鑳芥崟鑾?""
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
        """鍦ㄤ富绾跨▼瀹夎閽╁瓙锛岃繑鍥炴槸鍚︽垚鍔?""
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p)
        self._hook_proc_ref = HOOKPROC(self._hook_proc)
        kernel32 = ctypes.windll.kernel32
        self._hook = user32.SetWindowsHookExW(
            self.WH_KEYBOARD_LL, self._hook_proc_ref,
            kernel32.GetModuleHandleW(None), 0
        )
        return bool(self._hook)

    def pump(self):
        """姣忓抚璋冪敤锛屽鐞嗛挬瀛愭秷鎭紙蹇呴』鍦ㄥ畨瑁呴挬瀛愮殑绾跨▼璋冪敤锛?""
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
    """浣庣骇榧犳爣閽╁瓙锛堜富绾跨▼鐗堬級锛屽叏灞€鎹曡幏榧犳爣浜嬩欢锛屾父鎴忓墠鍙颁篃鑳芥崟鑾?""
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
                print("[绐楀彛缁戝畾] 鑷姩缁戝畾鎴愬姛")
            else:
                print("[璀﹀憡] 鏈壘鍒版父鎴忕獥鍙ｏ紝璇风敤鍑嗘槦鎷栨嫿缁戝畾")
                self.hwnd = None
                self.window_rect = None
                self.map_area_rect = None
        except Exception as e:
            print("[绐楀彛缁戝畾] 鑷姩缁戝畾寮傚父:", e)
            self.hwnd = None
            self.window_rect = None
            self.map_area_rect = None

        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []
        # 鏂规绯荤粺锛氬綋鍓嶆柟妗?1-3) + 杩愯鏂瑰紡(鎵嬪姩/闅忔満)
        self.current_route = 1
        self.route_mode = "鎵嬪姩"
        self._dropdown = None  # 褰撳墠灞曞紑鐨勪笅鎷夎彍鍗? None/"save"/"route"/"mode"/"clear_route"
        # 銆愭ā鍧桞銆戝钩鍙伴€夋嫨锛氶€夋嫨鍦ㄥ摢涓钩鍙颁笂鎵撴€紙缂栧彿浠?寮€濮嬶紝绌哄垪琛?鍏ㄩ儴骞冲彴锛?
        self._selected_platforms = []  # 閫変腑鐨勫钩鍙扮紪鍙峰垪琛紝绌?鍏ㄩ儴骞冲彴
        self._show_platform_selector = False  # 鏄惁鏄剧ず骞冲彴閫夋嫨闈㈡澘
        # 骞冲彴閫夋嫨鎸夐挳鍖哄煙锛堝皬鍦板浘宸︿笂鏂癸級
        self._btn_platform_selector = None  # "鍙板瓙閫夋嫨"鎸夐挳
        self._btn_platform_selector_close = None  # 閫夋嫨闈㈡澘鍏抽棴鎸夐挳
        # 銆愭ā鍧桞銆戠鐐规寜閽寜涓嬬壒鏁堢姸鎬?
        self._calib_left_pressed = False
        self._calib_right_pressed = False
        self._calib_top_pressed = False
        self._calib_top_pt = None  # Y杞翠笂绔偣锛?灞忓箷Y, 灏忓湴鍥綴)
        # 鍙嫋鎷藉噯鏄燂紙绐楀彛缁戝畾鐢級
        self._crosshair_size = CROSSHAIR_SIZE
        self._crosshair_home = CROSSHAIR_POS
        self._crosshair_pos = self._crosshair_home
        self._drag_crosshair = False
        # 宸茬粦绐楀彛鍒楄〃
        self._bound_windows = []  # [{hwnd, title}]
        # 鑷姩缁戝畾鐨勭獥鍙ｅ姞鍏ュ凡缁戝畾鍒楄〃
        if self.hwnd:
            try:
                length = user32.GetWindowTextLengthW(self.hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(self.hwnd, buf, length + 1)
                title = buf.value or "鏈煡绐楀彛"
                self._bound_windows.append({"hwnd": self.hwnd, "title": title})
            except Exception:
                self._bound_windows.append({"hwnd": self.hwnd, "title": "娓告垙绐楀彛"})
        self._bound_dropdown = False
        self._char_dropdown = False  # 浜虹墿鐗瑰緛涓嬫媺闈㈡澘寮€鍏?
        self._char_scroll = 0  # 涓嬫媺闈㈡澘褰撳墠婊氬姩浣嶇疆锛堢壒寰佽捣濮嬬储寮曪級
        # 鍔犺浇璺嚎椤礥I绱犳潗锛堝甫閫忔槑閫氶亾锛?
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
        # 宸ュ叿鏍忕礌鏉愶紙灏忓湴鍥句笂鏂癸級
        self._ui_refresh = load_png(resource_path(os.path.join("data", "ui_refresh.png")))
        self._ui_manual = load_png(resource_path(os.path.join("data", "ui_manual.png")))
        self._ui_plan_toolbar = load_png(resource_path(os.path.join("data", "ui_plan_toolbar.png")))
        # 銆愭ā鍧桞銆戣嚜鍔ㄦ牎鍑嗘寜閽紙鍚屽睆涓夌偣鏍″噯锛氬熀鐐?鍙?00+涓?00锛?
        self._ui_calib_auto = load_png(resource_path(os.path.join("data", "ui_calib_auto.png")))
        # MP鏍囩妯℃澘锛堥伄鎸℃娴嬶細鏍囩鍦?娌℃尅浣?鍚冭嵂锛屾爣绛炬秷澶?琚尅浣?涓嶅悆鑽級
        _mp_label_path = resource_path(os.path.join("data", "templates", "mp_label.png"))
        if os.path.exists(_mp_label_path):
            self._mp_label_template = cv2.imread(_mp_label_path)
            _debug_log("[MP閬尅] 鏍囩妯℃澘宸插姞杞?%dx%d" % self._mp_label_template.shape[:2])
        else:
            self._mp_label_template = None
            _debug_log("[MP閬尅] 鏍囩妯℃澘涓嶅瓨鍦? 璺宠繃閬尅妫€娴?)
        # 琛€鏉＄┖鐧界伆鑹叉ā鏉匡紙绔栨鍐呮ā鏉垮尮閰嶏紝鍖归厤鍒?绌虹櫧=鍔犺嵂锛?
        _gray_bar_path = resource_path(os.path.join("data", "templates", "gray_bar.png"))
        if os.path.exists(_gray_bar_path):
            self._gray_bar_template = cv2.imread(_gray_bar_path)
            _debug_log("[鍔犺嵂] 鐏拌壊绌虹櫧妯℃澘宸插姞杞?%dx%d" % self._gray_bar_template.shape[:2])
        else:
            self._gray_bar_template = None
            _debug_log("[鍔犺嵂] 鐏拌壊绌虹櫧妯℃澘涓嶅瓨鍦? 鍥為€€棰滆壊妫€娴?)
        # 杩愯鏃ュ織锛堟柊淇℃伅鍦ㄥ簳閮紝鍚戜笂娴佸姩锛屽彲婊氬姩锛?
        self._runtime_logs = []  # [{time, msg, color}]
        self._log_scroll = 0  # 0=搴曢儴锛堟渶鏂帮級锛屾鏁?鍚戜笂婊氬姩鐪嬪巻鍙?
        self._log_max = 500
        # 绐楀彛澶у皬鍥哄畾锛氱粦瀹氭椂璁板綍鐩爣澶у皬锛岃繍琛屼腑鐩戞帶鎷夊洖
        self._target_window_size = None  # (width, height) 鎴?None
        # 浜虹墿鐗瑰緛妯℃澘锛堟渶澶?0濂楋級
        self._char_templates = []  # [{id, img(numpy), width, height, created_at}]
        self._load_char_templates()
        # 鎵撴€?鑽搧杈撳叆妗嗙姸鎬?
        self._field_values = {}  # {field_id: value_string}
        self._focused_field = None  # 褰撳墠鑱氱劍鐨勫瓧娈礽d
        self._load_input_config()
        # YOLO妯″瀷璺緞锛堟墜鍔ㄩ€夋嫨锛?
        self._yolo_model_path = None
        self._load_yolo_config()
        # HP/MP鑷姩鍚冭嵂鐘舵€?
        self._hp_bar = None  # (x, y, w) 鎵弿绾?
        self._mp_bar = None
        self._last_hp_pot = 0  # 涓婃鍚冪孩鏃堕棿鎴?
        self._last_mp_pot = 0
        self._hp_pot_delay = 1  # 鍚冪孩鍚庡欢鏃?ms)锛?-20姣闅忔満
        self._mp_pot_delay = 1
        self._last_pot_check = 0
        self._auto_potion_enabled = True
        self._max_hp = 0  # 妫€娴嬪埌鐨凥P涓婇檺锛?=鏈煡
        self._max_mp = 0
        self._digit_templates = {}  # 0-9鏁板瓧妯℃澘
        self._last_max_check = 0
        # YOLO鎬墿妫€娴?
        self._yolo_net = None
        self._monsters = []  # [(x1,y1,x2,y2,score), ...]
        self._last_yolo_check = 0
        self._yolo_conf = 0.4
        self._yolo_nms = 0.45
        # YOLO鎬墿妫€娴?
        self._yolo_net = None
        self._monsters = []  # [(x1,y1,x2,y2,score), ...]
        self._last_yolo_check = 0
        self._yolo_conf = 0.4
        self._yolo_nms = 0.45
        # BUFF/鑽搧鍐峰嵈鐘舵€侊紙鍚姩鍚庣敓鏁堬級
        self._buff_last = {}  # buffN_key -> 涓婃閲婃斁鏃堕棿鎴?
        self._potion_last = {}  # potionN_key -> 涓婃閲婃斁鏃堕棿鎴?
        self._attack_last = {}  # atk1/aoe -> 涓婃閲婃斁鏃堕棿鎴?
        self._player_screen_pos = None  # (x,y) 浜虹墿鐢婚潰鍧愭爣
        self._combat_busy_until = 0  # 鍚庢憞閿佸畾鏃堕棿鎴?
        # === 浜烘€у寲鎴樻枟鐘舵€?===
        self._combat_react_until = 0       # 鍙嶅簲寤惰繜缁撴潫鏃堕棿
        self._combat_idle_until = 0        # 鍙戝憜缁撴潫鏃堕棿
        self._combat_last_idle_check = 0   # 涓婃鍙戝憜妫€鏌?
        self._combat_last_jump = 0         # 涓婃璺宠穬鏃堕棿
        self._combat_last_move = 0         # 涓婃璧颁綅鏃堕棿
        self._combat_target_idx = 0        # 褰撳墠鐩爣绱㈠紩锛堟帓搴忓悗锛?
        self._combat_facing = 0            # 0=鏈煡, 1=鍙? -1=宸?
        self._combat_turn_until = 0        # 杞韩鍔ㄧ敾缁撴潫鏃堕棿
        self._combat_had_target = False    # 涓婁竴甯ф槸鍚︽湁鐩爣
        self._combat_timed_keys = []       # 瀹氭椂閲婃斁鐨勬寜閿?[(vk, release_ms)]锛堜粎鐢ㄤ簬鐭寜杞韩锛?
        self._combat_last_target_pos = None  # 涓婁竴娆℃敾鍑荤洰鏍囦綅缃?x,y)锛岀敤浜庤繎鎴樻尅韬綋鏃舵悳琛€鏉?
        self._combat_held_keys = set()     # 鎸佺画鎸変綇鐨勬柟鍚戦敭锛堟祦鐣呯Щ鍔ㄧ敤锛?
        self._combat_move_dir = None       # 褰撳墠鎸佺画绉诲姩鏂瑰悜 "left"/"right"/None
        self._combat_locked_target = None  # 閿佸畾鐨勭洰鏍?(cx, cy)锛屾墦姝绘墠鎹紝涓嶄腑閫斿垏鎹?
        # === 妯″潡A锛氭墦鎬紭鍖栨柊澧炵姸鎬佸彉閲?===
        self._combat_active = False         # 銆愭垬鏂楁椿璺冩爣蹇椼€戞妧鑳借寖鍥村唴鏈夋€椂=True锛屾鏃舵殏鍋滃贰璺Щ鍔紝涓撳績鎵撴€?
        self._combat_target_lock_x = None   # 銆愰攣瀹氱洰鏍囬娆銆戣褰曞垰閿佸畾鏃剁洰鏍囩殑X鍧愭爣锛岀敤浜?绉掓棤鍙樺寲妫€娴?
        self._combat_target_lock_time = 0    # 銆愰攣瀹氱洰鏍囨椂闂存埑銆戣褰曢攣瀹氱洰鏍囩殑鏃堕棿(姣)锛岀敤浜庤绠?绉掓槸鍚﹀埌浜?
        self._combat_target_alive = False    # 銆愮洰鏍囨槸鍚﹀瓨娲汇€戞湁琛€鏉℃垨浼ゅ鏁板瓧鏃?True锛岃鏄庢€繕娌℃墦姝?
        self._combat_range_clear = False     # 銆愯寖鍥存竻鎬ā寮忋€戞妧鑳借寖鍥村唴鏈夋€椂=True锛岃寖鍥村唴鎬叏閮ㄦ墦瀹屾墠鎭㈠宸¤矾
        self._player_map_pos = None        # 鐜╁灏忓湴鍥惧潗鏍囷紝鐢ㄤ簬鍒ゆ柇褰撳墠骞冲彴
        self._monster_hp_bars = []         # 妫€娴嬪埌鐨勬€墿琛€鏉?[(x,y,w,h),...]
        self._hp_pot_wait_until = 0        # HP鍚冭嵂绛夊緟鍒拌繖涓椂闂?
        self._mp_pot_wait_until = 0        # MP鍚冭嵂绛夊緟鍒拌繖涓椂闂?
        self._prev_key_states = set()  # 鎸夐敭鎹曡幏杞鐢?
        # 鎸夐敭鎹曡幏鐘舵€侊紙GetAsyncKeyState杞锛?
        self._prev_key_states = set()  # 涓婁竴杞凡鎸変笅鐨勯敭鐮侀泦鍚?
        self._last_periodic_pot = {}  # {pot_key: last_use_ms} 鍛ㄦ湡鎬у悆鑽褰?
        self._load_route_config()
        pf_file, ld_file = route_files(self.current_route)
        self.platforms = self._load(pf_file, "platforms")
        self.ladders = self._load(ld_file, "ladders")
        # 鍔犺浇褰撳墠鏂规鐨勫乏鍙崇鐐癸紙鍜屽钩鍙版瀛愪竴璧蜂綔涓轰竴濂楁柟妗堬紝姘镐箙淇濆瓨锛?
        self._calib_left_pt = None
        self._calib_right_pt = None
        self._calib_top_pt = None
        calib_file = os.path.join(DATA_DIR, "route_%d_calib.json" % self.current_route)
        if os.path.exists(calib_file):
            try:
                with open(calib_file, "r", encoding="utf-8") as f:
                    cd = json.load(f)
                self._calib_left_pt = cd.get("calib_left")
                self._calib_right_pt = cd.get("calib_right")
                self._calib_top_pt = cd.get("calib_top")
            except Exception:
                pass

        # 鍔犺浇鎸夐挳鏍忔暣鍥?
        self._btn_bar_img = None
        btn_path = resource_path(os.path.join("data", "templates", "btn_bar.png"))
        if os.path.exists(btn_path):
            self._btn_bar_img = cv2.imread(btn_path)

        # 鎵嬪姩妗嗛€夋ā寮忕姸鎬?
        self._selecting = False
        self._select_frame = None
        self._select_rect = None
        self._select_dragging = False

        # 闅忔満妯″紡杩愯鐘舵€?
        self._random_running = False
        self._random_route_id = None
        self._random_platform_idx = 0
        self._random_state = "idle"  # idle/moving/attacking/returning/climbing
        self._random_attack_start = 0
        self._random_move_keys = set()  # 褰撳墠鎸変綇鐨勭Щ鍔ㄩ敭
        # 姊瓙鏀€鐖姸鎬佹満
        self._climb_state = "none"  # none/to_ladder/climbing/jump_down/teleport
        self._climb_ladder_x = 0
        self._climb_target_y = 0
        self._climb_direction = 0  # 1=up, -1=down
        self._climb_start_y = 0    # 璺宠穬/鐬Щ鍓嶇殑y鍧愭爣锛岀敤浜庢娴嬫槸鍚︾敓鏁?
        self._climb_action_time = 0  # 璺宠穬/鐬Щ鍔ㄤ綔寮€濮嬫椂闂?

        # 鑷姩鍒锋柊鐘舵€侊細榛樿寮€鍚紝鎵嬪姩妗嗛€夊悗鍏抽棴锛岀偣鍒锋柊閲嶆柊寮€鍚?
        self._auto_refresh = True

        self.last_player_pos = None
        self.frame_count = 0

        # 鐑敭鐘舵€侊紙淇濈暀浠ュ榧犳爣鍥炶皟澶嶇敤_handle_hotkey锛?
        self._key_state = {vk: False for vk in [VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10, VK_F12]}
        self._running = False  # 鑴氭湰杩愯鐘舵€侊紝F10鍚姩 F12鍋滄
        self._last_input_change = 0  # 杈撳叆妗嗘渶鍚庝慨鏀规椂闂达紝鐢ㄤ簬3绉掕嚜鍔ㄥけ鐒?
        # 鍋忕Щ瑙嗚鍙嶉锛氳濂藉亸绉诲悗绛?绉掞紝鍦ㄤ汉鐗╁亸绉荤偣浣嶇敾榛勭偣闂儊5娆?
        self._offset_feedback_start = 0  # 鍋忕Щ淇敼鏃堕棿鎴?
        self._offset_feedback_done = True  # 鏄惁宸插畬鎴愭湰娆″弽棣堬紙閬垮厤閲嶅瑙﹀彂锛?
        # 鎬墿妫€娴嬮€忔槑钂欐澘锛堢粺涓€钂欐澘锛氶粍鐐?鎬墿妗?琛€鏉＄孩鐐?钃濇潯钃濈偣锛?
        self._monster_overlay_running = False
        self._overlay_hwnd = None
        self._monster_overlay_data = None  # {char_pos, monsters, hp_marker, mp_marker, blink_until}
        self._monster_overlay_thread = None
        # 銆愭ā鍧桞銆戣嚜鍔ㄦ牎鍑嗙姸鎬侊紙鍚屽睆涓夌偣鏍″噯锛氬熀鐐?鍙?00+涓?00锛?
        self._auto_calib_stage = 0  # 0=绌洪棽, 1=钂欐澘鍑轰笁鐐瑰彲鎷栧姩瀹氱壒鑹蹭綅缃? 2=宸茶褰曠豢鐐瑰皬鍦板浘浣嶇疆寰呰褰曡摑鐐? 3=瀹屾垚
        self._auto_calib_base = None  # 鍩虹偣锛?灞忓箷X, 灞忓箷Y, 灏忓湴鍥綳, 灏忓湴鍥綴)
        self._auto_calib_green_map = None  # 缁跨偣灏忓湴鍥惧潗鏍囷紙浜虹墿璧板埌鐗硅壊浣嶇疆鍚庤褰曞厜鐐逛綅缃級
        self._auto_calib_blue_map = None  # 钃濈偣灏忓湴鍥惧潗鏍囷紙浜虹墿璧板埌鐗硅壊浣嶇疆鍚庤褰曞厜鐐逛綅缃級
        self._auto_calib_green_screen = None  # 缁跨偣灞忓箷鍧愭爣锛堣挋鏉挎嫋鍔ㄥ畾鐗硅壊浣嶇疆锛宻tage>=2鏃跺浐瀹氾級
        self._auto_calib_blue_screen = None  # 钃濈偣灞忓箷鍧愭爣锛堣挋鏉挎嫋鍔ㄥ畾鐗硅壊浣嶇疆锛宻tage>=2鏃跺浐瀹氾級
        self._auto_calib_green_offset = (400, 0)  # 缁跨偣鐩稿鍩虹偣鐨勫亸绉伙紙stage=1鏃舵嫋鍔ㄨ皟鏁达紝璺熺潃浜虹墿绉诲姩锛?
        self._auto_calib_blue_offset = (0, -400)  # 钃濈偣鐩稿鍩虹偣鐨勫亸绉伙紙stage=1鏃舵嫋鍔ㄨ皟鏁达紝璺熺潃浜虹墿绉诲姩锛?
        self._auto_calib_dragging = None  # 钂欐澘鎷栧姩鐘舵€侊細None/'green'/'blue'
        self._calib_overlay_msg = None  # 钂欐澘姝ｄ腑闂翠复鏃舵彁绀烘枃瀛楋紙濡傛埅鍥惧け璐ユ彁绀猴級锛?鏂囧瓧, 棰滆壊BGR, 鎴鏃堕棿鎴?
        # 妯℃澘鍖归厤璺熻釜锛堢浜屾鐐瑰€嶇巼鍚庢埅鍥剧壒鑹茶儗鏅紝妯℃澘鍖归厤璺熻釜浣嶇疆锛岀敾缁?钃濈┖蹇冨渾锛?
        self._calib_green_template = None  # 缁跨偣浣嶇疆鐨勮儗鏅ā鏉垮浘锛坣umpy鏁扮粍锛?
        self._calib_blue_template = None   # 钃濈偣浣嶇疆鐨勮儗鏅ā鏉垮浘
        self._calib_green_match_pos = None  # 缁跨偣妯℃澘鍖归厤鍒扮殑灞忓箷浣嶇疆 (x, y)
        self._calib_blue_match_pos = None   # 钃濈偣妯℃澘鍖归厤鍒扮殑灞忓箷浣嶇疆 (x, y)
        self._calib_template_size = 54       # 妯℃澘鎴浘澶у皬锛?4x54鍍忕礌锛宧alf=27锛?7*2=54锛?
        self._calib_match_threshold = 0.78  # 妯℃澘鍖归厤缃俊搴﹂槇鍊硷紙0.78鍏奸【鍑嗙‘鐜囧拰鍙洖鐜囷級
        # 鐑敭璺戦┈鐏粴鍔ㄥ亸绉伙紙浠庡彸鍒板乏娴佸姩锛?
        self._hotkey_scroll_x = 0
        # 鐑敭璺戦┈鐏鍔犺浇瀛椾綋鍜屾枃瀛楀昂瀵革紙閬垮厤姣忓抚鍔犺浇鍜岃绠楀鑷村崱椤匡級
        self._hotkey_text = "灏忔彁绀猴細F5骞冲彴褰曞埗锛孎6姊瓙褰曞埗锛孎7鏂规娓呴櫎锛孎8鏂规淇濆瓨锛孎9鎵嬪姩鎴彇灏忓湴鍥撅紝F10寮€濮嬭繍琛岋紝F12鍋滄杩愯"
        try:
            self._hotkey_font = ImageFont.truetype("simhei.ttf", 24)
            # 棰勮绠楁枃瀛楀搴﹂珮搴︼紝閬垮厤姣忓抚textbbox璁＄畻鍗￠】
            _tmp_img = Image.new('RGB', (10, 10))
            _tmp_draw = ImageDraw.Draw(_tmp_img)
            _bbox = _tmp_draw.textbbox((0, 0), self._hotkey_text, font=self._hotkey_font)
            self._hotkey_text_w = _bbox[2] - _bbox[0]
            self._hotkey_text_h = _bbox[3] - _bbox[1]
        except Exception:
            self._hotkey_font = ImageFont.load_default()
            self._hotkey_text_w = 800
            self._hotkey_text_h = 24
        # 鎸夐挳鐐瑰嚮鐗规晥
        self._pressed_btn = None       # 褰撳墠鎸変笅鐨勬寜閽畆ect (x,y,w,h)
        self._btn_flashes = []         # [(rect, start_ms, color_bgr), ...]

        # 鍔犺浇UI鑳屾櫙鍥撅紙浜斾釜鏍囩椤碉級
        self._ui_bgs = {}
        for tab, fname in [("route", "ui_bg_blank.png"), ("fight", "ui_tab_fight.png"),
                           ("potion", "ui_tab_potion.png"), ("chat", "ui_tab_chat.png"),
                           ("lie", "ui_tab_lie.png")]:
            p = resource_path(os.path.join("data", fname))
            img = cv2.imread(p)
            if img is not None:
                self._ui_bgs[tab] = cv2.resize(img, (UI_W, UI_H))
            else:
                self._ui_bgs[tab] = np.ones((UI_H, UI_W, 3), dtype=np.uint8) * 200
        self._ui_bg = self._ui_bgs["route"]
        self._current_tab = "route"

        # 椤堕儴鏍囩椤电偣鍑诲尯鍩燂紙楂樺害鏀剁揣锛岄伩鍏嶅拰涓嬫柟鎸夐挳閲嶅彔锛?
        self._tab_areas = {
            "route": (_s(5), _s(34), _s(75), _s(28)),
            "fight": (_s(82), _s(34), _s(60), _s(28)),
            "potion": (_s(145), _s(34), _s(60), _s(28)),
            "chat": (_s(207), _s(34), _s(58), _s(28)),
            "lie": (_s(266), _s(34), _s(58), _s(28)),
        }

        # 鏃ュ織
        self._logs = []

        if self.map_area_rect:
            print("Map area:", self.map_area_rect["width"], "x", self.map_area_rect["height"])
        else:
            print("Map area: 鏈娴嬪埌锛堣鍏堢粦瀹氭父鎴忕獥鍙ｆ垨F9鏍″噯锛?)
        print("鏂规 %d 宸插姞杞? %d 骞冲彴, %d 姊瓙 (妯″紡: %s)" % (
            self.current_route, len(self.platforms), len(self.ladders), self.route_mode))
        print("UI: 宸︿笂瑙?鍒锋柊/鎵嬪姩/鏂规X  绗竴鎺?骞冲彴/姊瓙/淇濆瓨鈻?鏂规鈻?)
        print("    绗簩鎺?娓呴櫎(缁?骞冲彴)/娓呴櫎(钃?姊瓙)/妯″紡鈻?娓呴櫎(姗?鏂规)\n")

        # 鑷姩澶囦唤绾跨▼锛氭瘡30鍒嗛挓澶囦唤涓€娆℃簮鐮侊紝淇濈暀鏈€杩?0涓?
        self._auto_backup_interval = 1800  # 30鍒嗛挓
        self._last_backup_time = 0
        self._auto_backup_thread = threading.Thread(target=self._auto_backup_loop, daemon=True)
        self._auto_backup_thread.start()
        print("[鑷姩澶囦唤] 宸插惎鍔紝姣?0鍒嗛挓Git鑷姩鎻愪氦涓€娆?)

    def _auto_backup_loop(self):
        """鑷姩澶囦唤寰幆锛氭瘡30鍒嗛挓妫€鏌ヤ竴娆★紝婧愮爜鏈変慨鏀瑰垯git commit骞秔ush鍒拌繙绋?
        鐢ㄩ€旓細闃叉鏈湴鏂囦欢涓㈠け锛岃嚜鍔ㄥ悓姝ュ埌GitHub杩滅▼浠撳簱
        娉ㄦ剰锛欸itHub鍗曟枃浠剁‖闄愬埗100MB锛宔xe绾?6MB鍙甯告帹閫?""
        import subprocess
        git_exe = r"C:\Program Files\Git\bin\git.exe"
        work_dir = os.path.dirname(os.path.abspath(__file__))
        # Windows涓撶敤锛欳REATE_NO_WINDOW鏍囧織锛岄槻姝ubprocess寮瑰嚭鎺у埗鍙伴粦绐?
        CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
        while True:
            try:
                time.sleep(60)  # 姣忓垎閽熸鏌ヤ竴娆?
                now = time.time()
                if now - self._last_backup_time < self._auto_backup_interval:
                    continue
                if not os.path.exists(git_exe):
                    continue
                # 姝ラ1锛氭鏌ユ槸鍚︽湁淇敼
                result = subprocess.run([git_exe, "status", "--porcelain"], cwd=work_dir,
                                        capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                if not result.stdout.strip():
                    self._last_backup_time = now
                    continue
                # 姝ラ2锛歡it add 鎵€鏈変慨鏀?
                subprocess.run([git_exe, "add", "-A"], cwd=work_dir,
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
                # 姝ラ3锛歡it commit
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                commit_msg = "鑷姩澶囦唤 %s" % timestamp
                subprocess.run([git_exe, "commit", "-m", commit_msg], cwd=work_dir,
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
                self._last_backup_time = now
                print("[鑷姩澶囦唤] Git宸叉彁浜? %s" % commit_msg)
                # 姝ラ4锛歡it push 鍒拌繙绋婫itHub锛堝ぇ闄嗙綉缁滃彲鑳藉け璐ワ紝澶辫触涓嶅奖鍝嶆湰鍦癱ommit锛?
                push_result = subprocess.run([git_exe, "push", "origin", "main"], cwd=work_dir,
                                             capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
                                             timeout=60)
                if push_result.returncode == 0:
                    print("[鑷姩澶囦唤] 宸叉帹閫佸埌杩滅▼GitHub")
                else:
                    # push澶辫触锛堢綉缁滈棶棰橈級锛屾湰鍦癱ommit宸蹭繚瀛橈紝涓嬫閲嶈瘯
                    print("[鑷姩澶囦唤] push澶辫触(缃戠粶闂)锛屾湰鍦板凡淇濆瓨锛屼笅娆￠噸璇? %s" % push_result.stderr[:200])
            except subprocess.TimeoutExpired:
                print("[鑷姩澶囦唤] push瓒呮椂(缃戠粶鎱?锛屾湰鍦板凡淇濆瓨锛屼笅娆￠噸璇?)
            except Exception as e:
                print("[鑷姩澶囦唤] 寮傚父:", e)
                time.sleep(60)

    def _update_window_rect(self):
        rect = ctypes.create_string_buffer(16)
        user32.GetWindowRect(self.hwnd, rect)
        l, t, r, b = struct.unpack("llll", rect.raw)
        self.window_rect = {"left": l, "top": t, "width": r - l, "height": b - t}

    def _save_target_window_size(self):
        """璁板綍褰撳墠绐楀彛澶у皬涓虹洰鏍囧ぇ灏忥紙缁戝畾鎴愬姛鍚庤皟鐢級"""
        if self.hwnd and self.window_rect:
            self._target_window_size = (self.window_rect["width"], self.window_rect["height"])
            print("[绐楀彛鍥哄畾] 鐩爣澶у皬宸茶褰? %dx%d" % self._target_window_size)

    def _ensure_window_size(self):
        """妫€娴嬬獥鍙ｅぇ灏忔槸鍚﹀彉鍔紝鍙樺姩鍒欐媺鍥炵洰鏍囧ぇ灏?""
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
            print("[绐楀彛鍥哄畾] 妫€娴嬪埌澶у皬鍙樺姩 %dx%d -> 宸叉媺鍥?%dx%d" % (cur_w, cur_h, tgt_w, tgt_h))

    def _load_region(self):
        """浠庢枃浠跺姞杞藉凡淇濆瓨鐨勫皬鍦板浘鍖哄煙锛屾垚鍔熻繑鍥?True"""
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
        """涓夌壒寰佺偣瀹氫綅锛氬乏=灏忓湴鍥炬枃瀛楀乏锛屽彸=澶у湴鍥炬枃瀛楀彸锛屼笅=搴曢儴钃濊壊绾匡紙棰滆壊妫€娴嬶級
        debug=False 鏃朵负姣忓抚杞婚噺妯″紡锛屼笉鍐欒皟璇曞浘"""
        if self.hwnd is None:
            return
        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]

        # 鎳掑姞杞芥ā鏉?
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

        # 1. 鎵?灏忓湴鍥?鏂囧瓧
        roi_m = frame[0:120, 0:300]
        res_m = cv2.matchTemplate(roi_m, tpl_m, cv2.TM_CCOEFF_NORMED)
        _, val_m, _, loc_m = cv2.minMaxLoc(res_m)
        mini_x, mini_y = loc_m
        if debug:
            print("灏忓湴鍥? val=%.3f at (%d,%d)" % (val_m, mini_x, mini_y))
        if val_m < 0.55:
            if debug:
                print("灏忓湴鍥惧尮閰嶅害杩囦綆锛屽洖閫€鎵弿绾挎硶")
                self._detect_minimap_scanline()
            return

        # 2. 鎵?澶у湴鍥?鏂囧瓧锛堝皬鍦板浘鍙充晶鍚岃锛?
        roi_b_x1 = mini_x + mw
        roi_b_x2 = min(fw, mini_x + 400)  # X鑼冨洿鍔犲ぇ鍒?00锛岄伩鍏嶅彸杈硅瘑鍒笉鍒?
        roi_b = frame[max(0, mini_y - 5):mini_y + mh + 10, roi_b_x1:roi_b_x2]
        res_b = cv2.matchTemplate(roi_b, tpl_b, cv2.TM_CCOEFF_NORMED)
        _, val_b, _, loc_b = cv2.minMaxLoc(res_b)
        big_x = roi_b_x1 + loc_b[0]
        big_y = max(0, mini_y - 5) + loc_b[1]
        if debug:
            print("澶у湴鍥? val=%.3f at (%d,%d)" % (val_b, big_x, big_y))

        # 3. 杈圭晫锛氬乏=灏忓湴鍥惧乏锛屽彸=澶у湴鍥惧彸锛屼笂=灏忓湴鍥句笅
        left = mini_x
        right = big_x + bw - 5  # 鍙宠竟鐣屽悜宸︾Щ5px
        top = mini_y + mh
        if debug:
            print("杈圭晫: L=%d R=%d T=%d W=%d" % (left, right, top, right - left))

        # 4. 妯℃澘鍖归厤搴曢儴杈圭晫鍥撅紙鏇夸唬钃濊壊绾块鑹叉娴嬶紝閬垮厤浜虹墿缁忚繃鏃惰鍒わ級
        tpl_btm = self._tpl_minimap_bottom
        btm_h, btm_w = tpl_btm.shape[:2]
        search_y1 = top
        search_y2 = min(fh, top + 350)
        # 鍦ㄥ皬鍦板浘宸﹀彸杈圭晫鍐呮悳绱㈠簳閮ㄦā鏉匡紙瀹藉害鍙兘灏忎簬灏忓湴鍥惧搴︼紝灞呬腑鎴栧亸宸﹂兘鑳藉尮閰嶏級
        search_x1 = max(0, left - 20)
        search_x2 = min(fw, right + 20)
        roi_btm = frame[search_y1:search_y2, search_x1:search_x2]
        bottom = None
        if roi_btm.shape[0] >= btm_h and roi_btm.shape[1] >= btm_w:
            res_btm = cv2.matchTemplate(roi_btm, tpl_btm, cv2.TM_CCOEFF_NORMED)
            _, val_btm, _, loc_btm = cv2.minMaxLoc(res_btm)
            if val_btm >= 0.55:
                # 搴曢儴杈圭晫瀹氬湪妯℃澘椤堕儴鍐嶅悜涓婄Щ15鍍忕礌锛堝幓鎺夌伆鑹茶竟妗嗗尯鍩燂級
                bottom = search_y1 + loc_btm[1]  # 搴曢儴杈圭晫瀹氬湪妯℃澘椤堕儴锛堝悜涓嬬Щ15px鍥炲師浣嶏級
                if debug:
                    print("搴曢儴妯℃澘: val=%.3f at (%d,%d), bottom_y=%d" % (
                        val_btm, search_x1 + loc_btm[0], search_y1 + loc_btm[1], bottom))
        if bottom is None:
            if debug:
                print("搴曢儴妯℃澘鏈壘鍒?鍖归厤搴﹁繃浣?锛岃烦杩囨湰甯?)
            return

        # 5. 璁＄畻鍖哄煙
        new_minimap = {
            "left": left, "top": mini_y,
            "width": right - left, "height": bottom - mini_y
        }
        TITLE_PAD = 53  # 浠庝笂杈圭晫鍚戜笅绉?3px寮€濮嬫埅鍙栵紙鍘?5锛屽悜涓嬬Щ8px锛?
        new_map = {
            "left": left,
            "top": top + TITLE_PAD,
            "width": right - left,
            "height": bottom - top - TITLE_PAD
        }

        # 杞婚噺妯″紡锛氬尯鍩熷彉鍖栧皬浜?px鍒欎笉鏇存柊锛堥槻鎶栵級锛屼笉鍐欐枃浠朵笉鍐欏浘
        if not debug:
            old = self.map_area_rect
            if (abs(old["left"] - new_map["left"]) <= 3 and
                abs(old["top"] - new_map["top"]) <= 3 and
                abs(old["width"] - new_map["width"]) <= 3 and
                abs(old["height"] - new_map["height"]) <= 3):
                return
            print("[鑷姩鍒锋柊] 灏忓湴鍥惧尯鍩熷彉鍖? %dx%d -> %dx%d" % (
                old["width"], old["height"], new_map["width"], new_map["height"]))

        self.minimap_rect = new_minimap
        self.map_area_rect = new_map
        self._save_region()
        self.last_player_pos = None

        if debug:
            # 璋冭瘯鍥?
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
        """銆愬厹搴曘€戞壂鎻忕嚎娉曪細鐩存帴宸℃渶澶栭潰鐨勭粏杈规锛堝惈鍦嗚锛夛紝鏍囬鏍忓寘鍚湪鍐?""
        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]

        # 鎼滅储鍖哄煙锛氱獥鍙ｅ乏涓婅灏忚寖鍥达紙灏忓湴鍥惧浐瀹氬湪宸︿笂瑙掞紝閬垮厤鎵埌娓告垙鑳屾櫙锛?
        roi_top = 8
        roi_bottom = min(fh, 260)
        roi_right = min(fw, 220)
        roi = frame[roi_top:roi_bottom, 0:roi_right].copy()
        roi_h, roi_w = roi.shape[:2]

        # 鐏板害 + 浜害闃堝€兼壘鐏扮櫧鑹茬粏杈规
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

        # 椤堕儴锛氫粠涓婂線涓嬬涓€鏉′寒绾?
        top_y = scan_h(0, roi_h // 2, 1, 130, 0.55)

        # 宸﹀彸杈规鍏堟壘锛堢敤椤堕儴浠ヤ笅鐨勮寖鍥达級
        if top_y is not None:
            mid_y1 = top_y + 20
            mid_y2 = min(roi_h - 5, top_y + 180)
            left_x = scan_v(0, roi_w // 2, 1, mid_y1, mid_y2, 130, 0.45)
            right_x = scan_v(roi_w - 1, roi_w // 2, -1, mid_y1, mid_y2, 130, 0.45)
        else:
            left_x = scan_v(0, roi_w // 2, 1, 20, roi_h - 5, 130, 0.45)
            right_x = scan_v(roi_w - 1, roi_w // 2, -1, 20, roi_h - 5, 130, 0.45)

        # 搴曢儴锛氬湪鍚堢悊鑼冨洿鍐呮壘锛堝皬鍦板浘楂樺姣旂害1:1锛岄珮搴︹増瀹藉害卤30锛?
        if top_y is not None and left_x is not None and right_x is not None:
            est_h = right_x - left_x  # 浼拌楂樺害鈮堝搴?
            bottom_search_top = top_y + max(120, est_h - 30)
            bottom_search_bottom = top_y + min(roi_h - top_y - 5, est_h + 40)
            bottom_y = scan_h(bottom_search_bottom, bottom_search_top, -1, 120, 0.45)
        else:
            bottom_y = scan_h(roi_h - 1, 60, -1, 130, 0.50)

        # 鍏滃簳
        if top_y is None: top_y = 5
        if bottom_y is None: bottom_y = roi_h - 5
        if left_x is None: left_x = 3
        if right_x is None: right_x = roi_w - 5

        print("Scan border: top=%d bottom=%d left=%d right=%d" % (top_y, bottom_y, left_x, right_x))

        # 灏忓湴鍥惧妗?= 鎵弿绾跨矖瀹氫綅锛堝惈鏍囬鏍忥級
        self.minimap_rect = {
            "left": left_x,
            "top": roi_top + top_y,
            "width": right_x - left_x,
            "height": bottom_y - top_y
        }

        # ===== 绗簩姝ワ細棰滆壊妫€娴嬬簿淇紝瑁佹帀澶氫綑杈规 =====
        # 鎴彇绮楀畾浣嶅尯鍩燂紝鐢ㄩ鑹插垎鏋愭壘鐪熷疄鍐呭杈圭晫
        coarse = frame[roi_top + top_y:roi_top + bottom_y, left_x:right_x].copy()
        ch, cw = coarse.shape[:2]
        hsv_c = cv2.cvtColor(coarse, cv2.COLOR_BGR2HSV)
        # 鍐呭鍍忕礌锛氶潪浜竟妗嗭紙浜害<160 鎴?楗卞拰搴?50锛夛紝鍗虫繁鑹茶儗鏅?褰╄壊骞冲彴+鍏夌偣
        content_mask = ((hsv_c[:, :, 2] < 160) | (hsv_c[:, :, 1] > 50)).astype(np.uint8) * 255
        content_mask = cv2.morphologyEx(content_mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

        def find_content_edge(mask, axis, start, end, step, ratio=0.15):
            """娌?axis=0(琛? 鎴?axis=1(鍒? 鎵弿锛屾壘绗竴涓唴瀹瑰崰姣?ratio鐨勪綅缃?""
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

        # 绮句慨鍥涜竟锛堜粠绮楄竟妗嗗悜鍐呮壘鍐呭杈圭晫锛?
        refine_top = find_content_edge(content_mask, 0, 0, ch // 2, 1, 0.15)
        refine_bottom = find_content_edge(content_mask, 0, ch - 1, ch // 3, -1, 0.15)
        refine_left = find_content_edge(content_mask, 1, 0, cw // 2, 1, 0.10)
        refine_right = find_content_edge(content_mask, 1, cw - 1, cw // 2, -1, 0.10)

        # 绮句慨澶辫触鍒欑敤绮楀畾浣?+ 鍥哄畾鍐呰竟璺?
        if refine_left is None: refine_left = 8
        if refine_top is None: refine_top = 2
        if refine_right is None: refine_right = cw - 2
        if refine_bottom is None: refine_bottom = ch - 2

        print("Refine: L=%d T=%d R=%d B=%d (coarse %dx%d)" % (
            refine_left, refine_top, refine_right, refine_bottom, cw, ch))

        # 鍦板浘鍖哄煙 = 绮句慨鍚庣殑鍐呭鍖猴紙绐楀彛鍐呭潗鏍囷級
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
        """鍔犺浇鏂规閰嶇疆锛堝綋鍓嶆柟妗?+ 杩愯鏂瑰紡锛?""
        if os.path.exists(ROUTE_CONFIG_FILE):
            try:
                with open(ROUTE_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.current_route = data.get("current_route", 1)
                self.route_mode = data.get("route_mode", "鎵嬪姩")
            except Exception:
                pass

    def _save_route_config(self):
        """淇濆瓨鏂规閰嶇疆"""
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
        """鏂规鏄惁宸插綍锛氬彧瑕佸钩鍙版枃浠跺瓨鍦ㄥ氨绠楀凡褰?""
        pf_file, _ = route_files(route_id)
        return os.path.exists(pf_file)

    def _save_to_route(self, route_id):
        """淇濆瓨褰撳墠褰曞埗鐨勫钩鍙?姊瓙+绔偣鍒版寚瀹氭柟妗堟枃浠讹紙瑕嗙洊锛?""
        pf_file, ld_file = route_files(route_id)
        with open(pf_file, "w", encoding="utf-8") as f:
            json.dump({"platforms": self.platforms, "count": len(self.platforms)}, f, indent=2)
        with open(ld_file, "w", encoding="utf-8") as f:
            json.dump({"ladders": self.ladders, "count": len(self.ladders)}, f, indent=2)
        # 鍚屾椂淇濆瓨绔偣锛堝乏/鍙?涓婏級鍒版柟妗堟枃浠?
        self._save_calib()
        self.current_route = route_id
        self._save_route_config()
        print("[淇濆瓨] 鏂规%d: %d 骞冲彴, %d 姊瓙, 绔偣宸?%s 鍙?%s 涓?%s锛堝凡瑕嗙洊锛? % (
            route_id, len(self.platforms), len(self.ladders),
            "鏈? if self._calib_left_pt else "鏃?, "鏈? if self._calib_right_pt else "鏃?,
            "鏈? if getattr(self, '_calib_top_pt', None) else "鏃?))

    def _save(self):
        """淇濆瓨鍒板綋鍓嶆柟妗堬紙鍏煎鍒囨崲鏃惰皟鐢級"""
        self._save_to_route(self.current_route)

    def _switch_route(self, route_id):
        """鍒囨崲鏂规锛氫笉鑷姩淇濆瓨锛岀洿鎺ュ姞杞界洰鏍囨柟妗堟暟鎹?""
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
        # 鍒囨崲鏂规鏃跺姞杞藉搴旀柟妗堢殑宸﹀彸绔偣
        self._calib_left_pt = None
        self._calib_right_pt = None
        self._calib_top_pt = None
        calib_file = os.path.join(DATA_DIR, "route_%d_calib.json" % route_id)
        if os.path.exists(calib_file):
            try:
                with open(calib_file, "r", encoding="utf-8") as f:
                    cd = json.load(f)
                self._calib_left_pt = cd.get("calib_left")
                self._calib_right_pt = cd.get("calib_right")
                self._calib_top_pt = cd.get("calib_top")
                # 浼樺厛鍔犺浇淇濆瓨鐨勫€嶇巼鍊硷紝娌℃湁鍐嶉噸鏂拌绠?
                saved_sx = cd.get("scale_x")
                saved_sy = cd.get("scale_y")
                if saved_sx and saved_sy:
                    self._calibrated_scale_x = float(saved_sx)
                    self._calibrated_scale_y = float(saved_sy)
                    self._map_screen_scale = self._calibrated_scale_x
                    print("[鏍″噯] 鍔犺浇淇濆瓨鍊嶇巼: X=%.4f Y=%.4f" % (self._calibrated_scale_x, self._calibrated_scale_y))
                # 鍔犺浇鏍″噯鏁版嵁鍚庨噸鏂拌绠楀€嶇巼锛岀‘淇濆皬鍦板浘搴曢儴鐘舵€佹爮鏄剧ず鍊嶇巼
                elif self._calib_left_pt and self._calib_right_pt and self._calib_top_pt:
                    base_sx, base_sy, base_mx, base_my = self._calib_left_pt
                    green_sx, green_sy, green_mx, green_my = self._calib_right_pt
                    blue_sy, blue_my = self._calib_top_pt
                    dx_screen = green_sx - base_sx
                    dy_screen = base_sy - blue_sy
                    dx_map = green_mx - base_mx
                    dy_map = base_my - blue_my
                    if dx_screen > 0 and dx_map > 0 and dy_screen > 0 and dy_map > 0:
                        self._calibrated_scale_x = dx_map / float(dx_screen)
                        self._calibrated_scale_y = dy_map / float(dy_screen)
                        self._map_screen_scale = self._calibrated_scale_x
                        print("[鏍″噯] 鍔犺浇鍊嶇巼: X=%.4f Y=%.4f" % (self._calibrated_scale_x, self._calibrated_scale_y))
            except Exception:
                pass
        self._save_route_config()
        print("[鍒囨崲] 鏂规 %d: %d 骞冲彴, %d 姊瓙" % (
            route_id, len(self.platforms), len(self.ladders)))

    def _clear_route_file(self, route_id):
        """娓呴櫎鎸囧畾鏂规锛氬垹闄ゆ枃浠讹紝鑻ヤ负褰撳墠鏂规鍒欐竻绌哄唴瀛?""
        pf_file, ld_file = route_files(route_id)
        calib_file = os.path.join(DATA_DIR, "route_%d_calib.json" % route_id)
        for f in (pf_file, ld_file, calib_file):
            if os.path.exists(f):
                os.remove(f)
        if route_id == self.current_route:
            self.platforms = []
            self.ladders = []
            self.platform_points = []
            self.ladder_points = []
            self.recording_platform = False
            self.recording_ladder = False
        print("[娓呴櫎] 鏂规%d 宸插垹闄? % route_id)

    def _clear_route(self):
        """娓呴櫎褰撳墠鏂规锛堜繚鐣欏吋瀹癸級"""
        self._clear_route_file(self.current_route)

    def _pop_platform(self):
        """鍒犻櫎鏈€鍚庝竴涓钩鍙版"""
        if self.platforms:
            removed = self.platforms.pop()
            print("[娓呭钩鍙癩 鍒犻櫎鏈€鍚庝竴涓钩鍙?id=%s (鍓╀綑 %d)" % (removed.get("id"), len(self.platforms)))
        else:
            print("[娓呭钩鍙癩 娌℃湁鍙垹闄ょ殑骞冲彴")

    def _pop_ladder(self):
        """鍒犻櫎鏈€鍚庝竴涓瀛愭"""
        if self.ladders:
            removed = self.ladders.pop()
            print("[娓呮瀛怾 鍒犻櫎鏈€鍚庝竴涓瀛?id=%s (鍓╀綑 %d)" % (removed.get("id"), len(self.ladders)))
        else:
            print("[娓呮瀛怾 娌℃湁鍙垹闄ょ殑姊瓙")

    def _toggle_mode(self):
        """鍒囨崲杩愯鏂瑰紡锛氭墜鍔?<-> 闅忔満"""
        self.route_mode = "闅忔満" if self.route_mode == "鎵嬪姩" else "鎵嬪姩"
        self._save_route_config()
        if self.route_mode == "闅忔満":
            self._start_random()
        else:
            self._stop_random()
        print("[鏂瑰紡] 鍒囨崲涓? %s" % self.route_mode)

    def _dropdown_items(self):
        """杩斿洖褰撳墠涓嬫媺鑿滃崟鐨勮彍鍗曢」鍒楄〃"""
        if self._dropdown == "save":
            return ["淇濆瓨涓烘柟妗堜竴", "淇濆瓨涓烘柟妗堜簩", "淇濆瓨涓烘柟妗堜笁"]
        elif self._dropdown == "route":
            items = []
            for i in range(1, 4):
                status = "宸插綍" if self._route_has_file(i) else "鏈綍"
                items.append("鏂规%s銆?s銆? % ("涓€浜屼笁"[i - 1], status))
            return items
        elif self._dropdown == "mode":
            return ["鎵嬪姩", "闅忔満"]
        elif self._dropdown == "clear_route":
            return ["娓呴櫎鏂规涓€", "娓呴櫎鏂规浜?, "娓呴櫎鏂规涓?]
        return []

    def _handle_dropdown_item(self, menu, item_idx):
        """澶勭悊涓嬫媺鑿滃崟椤圭偣鍑?""
        if menu == "save":
            self._save_to_route(item_idx + 1)
        elif menu == "route":
            self._switch_route(item_idx + 1)
        elif menu == "mode":
            self.route_mode = "鎵嬪姩" if item_idx == 0 else "闅忔満"
            self._save_route_config()
            if self.route_mode == "闅忔満":
                self._start_random()
            else:
                self._stop_random()
            print("[妯″紡] 鍒囨崲涓? %s" % self.route_mode)
        elif menu == "clear_route":
            self._clear_route_file(item_idx + 1)

    # ===== 闅忔満妯″紡杩愯閫昏緫 =====

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
        """鍚姩闅忔満妯″紡锛氬仠姝㈠綍鍒讹紝娓呯┖鎸夐敭锛屽紑濮嬬姸鎬佹満"""
        if self._random_running:
            return
        if self.hwnd is None:
            print("[鍚姩] 鏈粦瀹氭父鎴忕獥鍙ｏ紝璇峰厛缁戝畾")
            self._add_log("鏈粦瀹氱獥鍙ｏ紝鏃犳硶鍚姩")
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
        # 鍚屾椂鍚姩鎴樻枟閫昏緫鍜岄€忔槑钂欐澘锛堜笌F10涓€鑷达級
        self._running = True
        print("[闅忔満] 妯″紡宸插惎鍔紝灏嗚嚜鍔ㄩ€夋柟妗堟墦骞冲彴")
        self._add_log("闅忔満妯″紡宸插惎鍔紙鍚垬鏂?钂欐澘锛?)
        _debug_log("[闅忔満] 杩愯鎸夐挳宸茶Е鍙? _running=True, _random_running=True")

    def _stop_random(self):
        """鍋滄闅忔満妯″紡锛氭澗寮€鎵€鏈夋寜閿?""
        if not self._random_running:
            return
        self._release_all_keys()
        self._reset_climb()
        self._random_running = False
        self._random_state = "idle"
        # 鍚屾椂鍋滄鎴樻枟閫昏緫鍜岄€忔槑钂欐澘
        self._running = False
        if self._monster_overlay_running:
            self._stop_monster_overlay()
        print("[闅忔満] 妯″紡宸插仠姝?)
        self._add_log("闅忔満妯″紡宸插仠姝?)
        _debug_log("[闅忔満] 妯″紡宸插仠姝?)

    def _random_pick_route(self):
        """闅忔満閫変竴涓湁鏁版嵁鐨勬柟妗堬紝鎺掗櫎褰撳墠鏂规锛堥伩鍏嶈繛缁噸澶嶏級"""
        available = [i for i in range(1, 4) if self._route_has_file(i)]
        if not available:
            return None
        if len(available) > 1 and self._random_route_id in available:
            available = [i for i in available if i != self._random_route_id]
        return random.choice(available)

    def _find_nearest_ladder(self, px, py, target_y):
        """鎵炬渶杩戠殑鍙敤姊瓙锛堥潬杩戝綋鍓嶉珮搴﹀嵆鍙紝涓嶈姹傝鐩栧叏绋嬶級"""
        best = None
        best_dist = 9999
        for ld in self.ladders:
            lx = ld["x"]
            y_top = ld["y_top"]
            y_bottom = ld["y_bottom"]
            # 姊瓙鑼冨洿鍖呭惈褰撳墠楂樺害锛堝厑璁嘎?璇樊锛?
            if y_top - 5 <= py <= y_bottom + 5:
                dist = abs(lx - px)
                if dist < best_dist:
                    best_dist = dist
                    best = ld
        return best

    def _reset_climb(self):
        """閲嶇疆鏀€鐖?璺宠穬/鐬Щ鐘舵€?""
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
        self._move_stuck_inited = False  # 鐖缁撴潫閲嶇疆鍗′綇妫€娴?

    def _do_teleport(self, current_y):
        """鎵ц涓€娆＄灛绉伙細鎸夋柟鍚戦敭+鐬Щ鎶€鑳介敭"""
        fight_cfg = self._get_fight_config()
        tp_key = fight_cfg.get("teleport_key", "")
        if not tp_key:
            return
        # 鍏堟寜鏂瑰悜閿紙涓?涓嬶級
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
        # 鎸夌灛绉绘妧鑳介敭
        self._press_game_key(tp_key, duration=60)
        self._climb_start_y = current_y
        self._climb_action_time = time.time() * 1000

    def _move_to(self, player_pos, target_x, target_y):
        """绉诲姩瑙掕壊鍒扮洰鏍囦綅缃紙灏忓湴鍥惧潗鏍囷級锛屾敮鎸佹瀛愭攢鐖€傝繑鍥炴槸鍚﹀埌杈?""
        if player_pos is None:
            return False
        px, py = player_pos
        dx = target_x - px
        dy = target_y - py

        # === 鏀€鐖姸鎬佹満 ===
        if self._climb_state == "to_ladder":
            # 绉诲姩鍒版瀛恱浣嶇疆
            ldx = self._climb_ladder_x - px
            fight_cfg = self._get_fight_config()
            jump_key = fight_cfg.get("jump_key", "")
            if abs(ldx) > 10:
                # 杩樿繙锛屾按骞崇Щ鍔ㄩ潬杩?
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
                # 璺戠潃鎺ヨ繎姊瓙锛寈杩樻湁鐐硅窛绂?鈫?鎻愬墠璺?鏂瑰悜閿姄姊瓙
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
                _debug_log("[鐖] 璺戣烦鎶撴瀛?ldx=%.0f" % ldx)
                return False
            else:
                # 鍒拌揪姊瓙x锛堟涓嬫柟锛夛紝鏉惧紑鏂瑰悜閿紝寮€濮嬫攢鐖?
                if VK_LEFT in self._random_move_keys:
                    self._key_up(VK_LEFT)
                if VK_RIGHT in self._random_move_keys:
                    self._key_up(VK_RIGHT)
                self._climb_state = "climbing"
                self._climb_start_y = py  # 璁板綍璧峰Y锛岀敤浜庢攢鐖垚鍔熺‘璁?
                self._climb_action_time = time.time() * 1000  # 璁板綍鏀€鐖紑濮嬫椂闂?
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
                _debug_log("[鐖] 寮€濮嬫攢鐖?鏂瑰悜=%s 璧峰Y=%.0f 鐩爣Y=%.0f" % (
                    "涓? if self._climb_direction > 0 else "涓?, py, self._climb_target_y))
                return False

        if self._climb_state == "climbing":
            now_ms = time.time() * 1000
            elapsed = now_ms - self._climb_action_time
            # === Y鍊肩‘璁わ細鏀€鐖?00ms鍚庢娴媃鏄惁鍙樺寲锛屾病鍙樺寲=琚€尅浣?娌℃姄绋?澶辫触 ===
            if elapsed > 800 and abs(py - self._climb_start_y) < 6:
                _debug_log("[鐖] 澶辫触锛歒鏈彉鍖?%.0f->%.0f) %.0fms锛岄噸缃噸璇曪紙鎴樻枟绯荤粺鍏堟竻鎬級" % (
                    self._climb_start_y, py, elapsed))
                self._reset_climb()
                return False
            # 鎸佺画鎸変綇涓?涓嬶紝妫€娴嬫槸鍚﹀埌杈剧洰鏍囬珮搴?
            cdy = self._climb_target_y - py
            if abs(cdy) <= 4:
                # 鍒拌揪鐩爣楂樺害锛屽仠姝㈡攢鐖?
                _debug_log("[鐖] 鎴愬姛锛歒浠?.0f鍒?.0f锛岀敤鏃?.0fms" % (
                    self._climb_start_y, py, elapsed))
                self._reset_climb()
                return False  # 涓嬩竴杞户缁按骞崇Щ鍔ㄥ埌鐩爣x
            # 淇鏂瑰悜锛堝彲鑳界埇杩囦簡锛?
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

        # === 鍚戜笂璺崇姸鎬侊紙璺宠穬閿紝妫€娴媦鏄惁涓婂崌锛?==
        if self._climb_state == "jump_up":
            now_ms = time.time() * 1000
            elapsed = now_ms - self._climb_action_time
            # 灏忓湴鍥緔鍑忓皬=鍚戜笂绉诲姩
            went_up = py < self._climb_start_y - 5
            if went_up:
                if abs(py - self._climb_target_y) <= 8:
                    self._reset_climb()
                else:
                    self._climb_state = "none"
                return False
            if elapsed > 800:
                # 瓒呮椂娌′笂鍗?= 璺充笉涓婂幓锛屾敼鐢ㄧ灛绉绘垨姊瓙
                self._climb_state = "none"
                _debug_log("[涓婅烦] 璺充笉涓婂幓锛坹鏈笂鍗囷級锛屾敼鐢ㄧ灛绉?姊瓙")
                return False
            return False

        # === 鍚戜笅璺崇姸鎬侊紙涓?璺宠穬閿紝妫€娴媦鏄惁涓嬮檷锛?==
        if self._climb_state == "jump_down":
            now_ms = time.time() * 1000
            elapsed = now_ms - self._climb_action_time
            # 妫€娴媦鏄惁涓嬮檷锛堝皬鍦板浘y澧炲ぇ=鍚戜笅绉诲姩锛?
            went_down = py > self._climb_start_y + 5
            if went_down:
                # 鎴愬姛璺充笅锛屾澗寮€涓嬮敭
                self._key_up(VK_DOWN)
                if abs(py - self._climb_target_y) <= 8:
                    self._reset_climb()
                else:
                    # 杩樻病鍒扮洰鏍囧眰锛屼笅涓€杞户缁垽鏂紙鍙兘鍐嶈烦鎴栬蛋姊瓙锛?
                    self._climb_state = "none"
                return False
            if elapsed > 800:
                # 瓒呮椂娌′笅闄?= 璺充笉涓嬪幓锛屾敼鐢ㄦ瀛?
                self._key_up(VK_DOWN)
                self._climb_state = "none"
                _debug_log("[涓嬭烦] 璺充笉涓嬪幓锛坹鏈笅闄嶏級锛屾敼鐢ㄦ瀛?)
                return False
            return False

        # === 鐬Щ鐘舵€侊紙鏂瑰悜閿?鐬Щ鎶€鑳斤紝妫€娴嬫槸鍚︾敓鏁堬級===
        if self._climb_state == "teleport":
            now_ms = time.time() * 1000
            elapsed = now_ms - self._climb_action_time
            y_changed = abs(py - self._climb_start_y) > 3
            if y_changed or elapsed > 800:
                if abs(py - self._climb_target_y) <= 8:
                    self._reset_climb()
                    return False
                # 娌″埌鐩爣灞傦紝鍐嶇灛绉讳竴娆★紙鏈€澶?绉掞級
                if elapsed > 3000:
                    self._reset_climb()
                    _debug_log("[鐬Щ] 澶氭鏈埌杈剧洰鏍囷紝鏀圭敤姊瓙")
                else:
                    self._do_teleport(py)
            return False

        # === 姝ｅ父绉诲姩锛堥潪鏀€鐖姸鎬侊級===
        # 闇€瑕佷笂涓嬪眰鏃讹細鍏堟壘姊瓙锛屾壘鍒扮洿鎺ュ幓姊瓙浣嶇疆锛堜笉瑕佹眰dx<=25锛岄伩鍏嶆瀛愪笉鍦ㄥ钩鍙颁腑蹇冨氨鎵句笉鍒帮級
        if abs(dy) > 8:
            ladder = self._find_nearest_ladder(px, py, target_y)
            if ladder:
                self._climb_state = "to_ladder"
                self._climb_ladder_x = ladder["x"]
                self._climb_target_y = target_y
                self._climb_direction = 1 if target_y < py else -1
                _debug_log("[璺嚎] 闇€涓婁笅灞俤y=%.0f锛岀洿鎺ュ幓姊瓙x=%.0f" % (dy, ladder["x"]))
                return False

        # 鍨傜洿宸紓澶т笖姘村钩宸插榻?鈫?璺宠穬/鐬Щ锛堟病姊瓙鏃剁殑鍏滃簳锛?
        if abs(dy) > 8 and abs(dx) <= 25:
            now_ms = time.time() * 1000
            fight_cfg = self._get_fight_config()
            tp_key = fight_cfg.get("teleport_key", "")
            tp_dist = fight_cfg.get("teleport_distance", 0)
            jump_key = fight_cfg.get("jump_key", "")
            vertical_gap = abs(dy)
            going_up = target_y < py  # 灏忓湴鍥緔瓒婂皬瓒婇潬涓?
            aligned = abs(dx) <= 6  # 姘村钩瀵归綈鎵嶈烦锛岄伩鍏嶄贡璺?

            # --- 鍘讳笂灞傦細鍏堣烦 鈫?鐬Щ 鈫?姊瓙 ---
            if going_up:
                # 1. 灏忛珮搴﹀樊涓旀按骞冲榻愭墠璺?
                if vertical_gap <= 15 and jump_key and aligned:
                    self._climb_state = "jump_up"
                    self._climb_target_y = target_y
                    self._climb_start_y = py
                    self._climb_action_time = now_ms
                    self._press_game_key(jump_key, duration=80)
                    _debug_log("[涓婅烦] 鐩爣y=%.0f 褰撳墠y=%.0f锛岄棿璺?%.0f锛屽皾璇曡烦璺? % (
                        target_y, py, vertical_gap))
                    return False
                # 2. 鐬Щ锛堟病閰嶇疆鐩存帴蹇界暐锛?
                if tp_key and tp_dist > 0 and tp_dist >= vertical_gap:
                    self._climb_state = "teleport"
                    self._climb_target_y = target_y
                    self._climb_direction = 1
                    self._do_teleport(py)
                    _debug_log("[鐬Щ] 鐩爣y=%.0f 褰撳墠y=%.0f锛岄棿璺?%.0f锛岀灛绉昏窛绂?%d锛屽悜涓? % (
                        target_y, py, vertical_gap, tp_dist))
                    return False
                # 3. 閮戒笉琛?鈫?鐖瀛?
                ladder = self._find_nearest_ladder(px, py, target_y)
                if ladder:
                    self._climb_state = "to_ladder"
                    self._climb_ladder_x = ladder["x"]
                    self._climb_target_y = target_y
                    self._climb_direction = 1
                    _debug_log("[鐖] 鐩爣y=%.0f 褰撳墠y=%.0f锛屾壘姊瓙x=%.0f锛屽悜涓? % (
                        target_y, py, ladder["x"]))
                    return False

            # --- 鍘讳笅灞傦細鍏堝垽瀹氫笅璺?鈫?鐬Щ 鈫?姊瓙 ---
            else:
                # 1. 鍒ゅ畾楂樺害宸兘鍚︿笅璺充笖姘村钩瀵归綈
                if jump_key and vertical_gap <= 30 and aligned:
                    self._climb_state = "jump_down"
                    self._climb_target_y = target_y
                    self._climb_start_y = py
                    self._climb_action_time = now_ms
                    self._key_down(VK_DOWN)
                    self._press_game_key(jump_key, duration=80)
                    _debug_log("[涓嬭烦] 闂磋窛%.0f<=30锛屼笅+璺宠穬" % vertical_gap)
                    return False
                # 2. 鐬Щ锛堟病閰嶇疆鐩存帴蹇界暐锛?
                if tp_key and tp_dist > 0 and tp_dist >= vertical_gap:
                    self._climb_state = "teleport"
                    self._climb_target_y = target_y
                    self._climb_direction = -1
                    self._do_teleport(py)
                    _debug_log("[鐬Щ] 鐩爣y=%.0f 褰撳墠y=%.0f锛岄棿璺?%.0f锛岀灛绉昏窛绂?%d锛屽悜涓? % (
                        target_y, py, vertical_gap, tp_dist))
                    return False
                # 3. 閮戒笉琛?鈫?鐖瀛?
                ladder = self._find_nearest_ladder(px, py, target_y)
                if ladder:
                    self._climb_state = "to_ladder"
                    self._climb_ladder_x = ladder["x"]
                    self._climb_target_y = target_y
                    self._climb_direction = -1
                    _debug_log("[鐖] 鐩爣y=%.0f 褰撳墠y=%.0f锛屾壘姊瓙x=%.0f锛屽悜涓? % (
                        target_y, py, ladder["x"]))
                    return False

            # 娌℃湁姊瓙锛屽皬楂樺害宸皾璇曟櫘閫氳烦璺?
            if abs(dy) <= 20 and jump_key:
                self._press_game_key(jump_key, duration=80)
                return False

        # 姘村钩绉诲姩
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

            # === 鍗′綇妫€娴嬶細姘村钩绉诲姩鏃舵瘡1.5绉掔‘璁鏄惁鍙樺寲锛屾病鍙樺寲=琚殰纰嶇墿鍗′綇鈫掕烦璺冭劚鍥?===
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
                        _debug_log("[绉诲姩] 鍗′綇锛氭柟鍚?%s X=%.0f 1.5绉掓湭鍙樺寲锛岃烦璺冭劚鍥? % (
                            "鍙? if dx > 0 else "宸?, px))
                self._move_stuck_last_x = px
                self._move_stuck_last_time = now_ms

            # 寰珮宸钩鍙板鎺ワ細Y宸?-20鍍忕礌锛岃竟璧拌竟璺宠法涓婄浉閭诲钩鍙?
            if 3 <= abs(dy) <= 20:
                fight_cfg = self._get_fight_config()
                jump_key = fight_cfg.get("jump_key", "")
                if jump_key:
                    last_jump = getattr(self, '_last_platform_gap_jump', 0)
                    if now_ms - last_jump > 350:
                        self._press_game_key(jump_key, duration=60)
                        self._last_platform_gap_jump = now_ms
                        _debug_log("[骞冲彴瀵规帴] 寰珮宸?.0fpx锛岃竟璧拌竟璺? % dy)
        else:
            if VK_LEFT in self._random_move_keys:
                self._key_up(VK_LEFT)
            if VK_RIGHT in self._random_move_keys:
                self._key_up(VK_RIGHT)
            self._move_stuck_inited = False  # 鍒拌揪鐩爣X锛岄噸缃崱浣忔娴?

        # 鍒拌揪鍒ゆ柇
        if abs(dx) <= 4 and abs(dy) <= 6:
            self._reset_climb()
            return True
        return False

    def _random_step(self, player_pos):
        """闅忔満妯″紡姣忓抚鐘舵€佹満"""
        if not self._random_running:
            return
        # 銆愭柊绯荤粺銆戜娇鐢ㄩ噸鏂板畾涔夌殑鎵撴€?绉诲姩/姊瓙绯荤粺鏃讹紝绂佺敤鏃у贰璺姸鎬佹満
        if getattr(self, '_use_new_system', True):
            return

        if self._random_state == "idle":
            if self.route_mode == "鎵嬪姩":
                # 鎵嬪姩妯″紡锛氱敤褰撳墠鎸囧畾鐨勬柟妗堬紝涓嶉殢鏈洪€?
                route_id = self.current_route if self._route_has_file(self.current_route) else None
            else:
                # 闅忔満妯″紡锛氶殢鏈洪€夋柟妗堬紙鎺掗櫎涓婁竴涓級
                route_id = self._random_pick_route()
            if route_id is None:
                # 娌℃湁淇濆瓨璺嚎鏃跺師鍦版墦鎬紝涓嶈窇骞冲彴锛屽彧妫€娴嬭韩杈规€紙淇濇寔_running=True鎴樻枟缁х画锛?
                if not getattr(self, '_random_no_route_logged', False):
                    self._random_no_route_logged = True
                    print("[闅忔満] 娌℃湁鍙敤璺嚎锛屽師鍦版墦鎬腑锛堜笉璺戝钩鍙帮級")
                    _debug_log("[闅忔満] 娌℃湁鍙敤璺嚎锛屽師鍦版墦鎬腑锛堜笉璺戝钩鍙帮級")
                    self._add_log("鏃犺矾绾匡紝鍘熷湴鎵撴€腑")
                return
            self._switch_route(route_id)
            self._random_route_id = route_id
            self._random_platform_idx = 0
            self._random_state = "moving"
            print("[闅忔満] 閫夋嫨鏂规%d锛?d骞冲彴锛夛紝寮€濮嬮€愪釜鎵? % (route_id, len(self.platforms)))

        elif self._random_state == "moving":
            # 銆愭ā鍧桝-闇€姹?銆戞垬鏂楁椿璺冩椂鏆傚仠宸¤矾绉诲姩锛岀敱_combat_tick鎺ョ鎵撴€?
            # 鍘熺悊锛氭妧鑳借寖鍥村唴鏈夋€椂_combat_active=True锛屾鏃朵汉鐗╁簲涓撳績鎵撴€笉寰€鍒殑骞冲彴璺?
            if getattr(self, '_combat_active', False):
                return
            if self._random_platform_idx >= len(self.platforms):
                # 鍏ㄩ儴骞冲彴鎵撳畬锛屽洖璧风偣
                self._random_state = "returning"
                return
            pf = self.platforms[self._random_platform_idx]
            pts = self._platform_points(pf)
            # 鐩爣=鏇茬嚎涓偣锛堣矾寰勪腑闂寸殑鐐癸級
            mid_pt = pts[len(pts) // 2]
            target_x, target_y = float(mid_pt[0]), float(mid_pt[1])
            arrived = self._move_to(player_pos, target_x, target_y)
            # 璺嚎璇婃柇鏃ュ織锛堟瘡1绉掍竴娆★級
            if player_pos and time.time() - getattr(self, '_last_route_log', 0) > 1.0:
                self._last_route_log = time.time()
                px, py = player_pos
                _debug_log("[璺嚎] 骞冲彴%d/%d 鐘舵€?%s 鐜╁(%.0f,%.0f) 鐩爣(%.0f,%.0f) dx=%.0f dy=%.0f climb=%s" % (
                    self._random_platform_idx + 1, len(self.platforms),
                    self._random_state, px, py, target_x, target_y,
                    target_x - px, target_y - py, self._climb_state))
            if arrived:
                self._release_all_keys()
                self._random_state = "attacking"
                self._random_attack_start = time.time()
                self._key_down(VK_ATTACK)
                print("[闅忔満] 鍒拌揪骞冲彴%d锛屽紑濮嬫敾鍑? % self._random_platform_idx)

        elif self._random_state == "attacking":
            # 绗笁灞傦細褰撳墠骞冲彴娓呭畬鍚庢墠鍒囨崲涓嬩竴涓钩鍙帮紙鑷冲皯鏀诲嚮1绉掗伩鍏峐OLO鏈娴嬪埌灏辫蛋锛?
            attack_elapsed = time.time() - self._random_attack_start
            if attack_elapsed > 1.0:
                monsters_on_platform = self._filter_monsters_on_platform(
                    self._monsters, self._player_screen_pos) if self._player_screen_pos else self._monsters
                if not monsters_on_platform:
                    self._key_up(VK_ATTACK)
                    self._random_platform_idx += 1
                    self._random_state = "moving"
                    print("[闅忔満] 骞冲彴%d宸叉竻瀹岋紝鍓嶅線涓嬩竴涓? % (self._random_platform_idx - 1))

        elif self._random_state == "returning":
            # 鍥炲埌璧风偣锛堢涓€涓钩鍙颁綅缃級锛岀劧鍚庨噸鏂伴殢鏈洪€夋柟妗?
            if self.platforms:
                pf = self.platforms[0]
                pts = self._platform_points(pf)
                mid_pt = pts[len(pts) // 2]
                target_x, target_y = float(mid_pt[0]), float(mid_pt[1])
                arrived = self._move_to(player_pos, target_x, target_y)
                if arrived:
                    self._release_all_keys()
                    self._random_state = "idle"
                    print("[闅忔満] 宸插洖璧风偣锛岄噸鏂伴殢鏈洪€夋柟妗?)

    def _capture_window(self):
        """鎴彇娓告垙鏁翠釜绐楀彛鐢婚潰锛堝寘鎷爣棰樻爮锛屽拰鑷姩鍚冭嵂绛夊姛鑳藉潗鏍囦竴鑷达級"""
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
        """銆愭ā鍧桞銆戞娴嬪皬鍦板浘涓婁汉鐗╅粍鑹插厜鐐癸紙甯﹁窡韪€昏緫锛岄伩鍏嶈妫€娴嬭繙澶勯粍鑹茬墿浣擄級
        鍘熺悊锛欻SV棰滆壊杩囨护鎵鹃粍鑹插尯鍩燂紝鏈変笂娆′綅缃椂鍙栫涓婃鏈€杩戠殑杞粨锛堣窡韪級锛屽惁鍒欏彇闈㈢Н鏈€澶х殑
        杩斿洖锛?x, y) 鍏夌偣姝ｄ腑蹇冨潗鏍囷紱鎵句笉鍒拌繑鍥濶one"""
        hsv = cv2.cvtColor(map_area, cv2.COLOR_BGR2HSV)
        lower = np.array([YELLOW_H_LOW, YELLOW_S_LOW, YELLOW_V_LOW])
        upper = np.array([YELLOW_H_HIGH, 255, 255])
        h, w = map_area.shape[:2]
        mask = cv2.inRange(hsv, lower, upper)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # 闈㈢Н鑼冨洿1-50鍍忕礌锛堝厜鐐瑰彲鑳界◢澶э級
        valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 50]
        if valid:
            # 璁＄畻鎵€鏈夋湁鏁堣疆寤撶殑璐ㄥ績
            centers = []
            for c in valid:
                M = cv2.moments(c)
                if M["m00"] > 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    centers.append((cx, cy, cv2.contourArea(c)))
            if centers:
                last_pos = getattr(self, 'last_player_pos', None)
                if last_pos:
                    # 鏈変笂娆′綅缃細鍙栫涓婃鏈€杩戠殑杞粨锛堣窡韪€昏緫锛岄伩鍏嶈妫€娴嬭繙澶勯粍鑹茬墿浣擄級
                    best = min(centers, key=lambda p: (p[0]-last_pos[0])**2 + (p[1]-last_pos[1])**2)
                    # 鏈€澶ц窛绂婚檺鍒讹細绂讳笂娆′綅缃秴杩?0鍍忕礌璇存槑璺熻釜涓簡锛岄噸鏂板彇闈㈢Н鏈€澶х殑锛堥伩鍏嶄竴鐩磋窡韪敊璇綅缃級
                    _dist = ((best[0]-last_pos[0])**2 + (best[1]-last_pos[1])**2)**0.5
                    if _dist > 60:
                        best = max(centers, key=lambda p: p[2])
                    self.last_player_pos = (best[0], best[1])
                    return (best[0], best[1])
                else:
                    # 娌℃湁涓婃浣嶇疆锛氬彇闈㈢Н鏈€澶х殑
                    best = max(centers, key=lambda p: p[2])
                    self.last_player_pos = (best[0], best[1])
                    return (best[0], best[1])
        self.last_player_pos = None
        return None

    def _point_to_polyline_dist(self, px, py, points):
        """鐐瑰埌鎶樼嚎鐨勬渶杩戣窛绂伙紙灏忓湴鍥惧潗鏍囷級銆俻oints涓篬(x,y),...]鍒楄〃銆?""
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
        """鑾峰彇骞冲彴鐨勬姌绾胯矾寰勭偣锛屽吋瀹规棫鏍煎紡{x_min,x_max,y_base}锛堣浆鎴愭按骞崇嚎锛夈€?""
        if "points" in pf and pf["points"] and len(pf["points"]) >= 2:
            return pf["points"]
        # 鏃ф牸寮忓吋瀹癸細鐢熸垚姘村钩鐩寸嚎
        x_min, x_max, y_base = pf["x_min"], pf["x_max"], pf["y_base"]
        return [[x_min, y_base], [x_max, y_base]]

    def _platform_x_range(self, pf):
        """鑾峰彇骞冲彴鐨剎鑼冨洿锛堝吋瀹规柊鏃ф牸寮忥級銆?""
        pts = self._platform_points(pf)
        xs = [p[0] for p in pts]
        return min(xs), max(xs)

    def _get_current_manual_platform(self):
        """銆愭ā鍧桞銆戣幏鍙栦汉鐗╁綋鍓嶆墍鍦ㄧ殑鎵嬪姩褰曞埗骞冲彴锛堢敤浜庣Щ鍔ㄨ竟鐣岄檺鍒讹級
        鐢ㄩ€旓細鍒ゆ柇浜虹墿鍦ㄥ摢涓墜鍔ㄥ綍鍒跺钩鍙颁笂锛岄檺鍒朵汉鐗╁湪骞冲彴X鑼冨洿鍐呮墦鎬?
        鍘熺悊锛?
          1. 閬嶅巻鎵€鏈夋墜鍔ㄥ綍鍒跺钩鍙?
          2. 璁＄畻浜虹墿灏忓湴鍥惧潗鏍囧埌骞冲彴鎶樼嚎鐨勮窛绂?
          3. 璺濈鏈€灏忎笖鈮?5px鐨勫钩鍙?= 浜虹墿褰撳墠鎵€鍦ㄥ钩鍙?
        杩斿洖锛氬钩鍙板璞ict锛涙壘涓嶅埌杩斿洖None"""
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
        """銆愭ā鍧桞銆戞娴嬩汉鐗╂槸鍚﹁秴鍑烘墜鍔ㄥ綍鍒跺钩鍙扮殑X杈圭晫锛岃秴鍑哄垯杩斿洖寰€鍥炶蛋鐨勬柟鍚?
        鐢ㄩ€旓細浜虹墿鍒颁簡骞冲彴杈圭紭鑷姩鍥炲幓锛屽彧鎵撳钩鍙癤鑼冨洿鍐呯殑鎬?
        鍘熺悊锛?
          1. 鑾峰彇浜虹墿褰撳墠鎵€鍦ㄧ殑鎵嬪姩褰曞埗骞冲彴
          2. 鑾峰彇骞冲彴X鑼冨洿锛坸_min, x_max锛?
          3. 浜虹墿X < x_min 鈫?闇€瑕佸線鍙宠蛋鍥炲幓
          4. 浜虹墿X > x_max 鈫?闇€瑕佸線宸﹁蛋鍥炲幓
          5. 鍦ㄨ寖鍥村唴 鈫?杩斿洖None锛堜笉闇€瑕佽皟鏁达級
        杩斿洖锛?right'=闇€瑕佸線鍙宠蛋, 'left'=闇€瑕佸線宸﹁蛋, None=鍦ㄨ寖鍥村唴"""
        pf = self._get_current_manual_platform()
        if pf is None or not self._player_map_pos:
            return None
        x_min, x_max = self._platform_x_range(pf)
        px = self._player_map_pos[0]
        if px < x_min + 2:  # 瓒呭嚭宸﹁竟鐣?px
            return 'right'
        elif px > x_max - 2:  # 瓒呭嚭鍙宠竟鐣?px
            return 'left'
        return None

    def _is_monster_in_manual_platform(self, screen_x, screen_y):
        """銆愭ā鍧桞銆戝垽鏂€槸鍚﹀湪浜虹墿褰撳墠鎵嬪姩褰曞埗骞冲彴鐨刋鑼冨洿鍐?
        鐢ㄩ€旓細鍙墦骞冲彴X鑼冨洿鍐呯殑鎬紝瓒呭嚭鑼冨洿鐨勬€笉鎵?
        鍘熺悊锛?
          1. 鑾峰彇浜虹墿褰撳墠鎵€鍦ㄧ殑鎵嬪姩褰曞埗骞冲彴
          2. 浼扮畻鎬殑灏忓湴鍥綳鍧愭爣
          3. 鎬猉鍦ㄥ钩鍙癤鑼冨洿鍐?鈫?True
          4. 瓒呭嚭鑼冨洿鎴栨病鏈夋墜鍔ㄥ綍鍒跺钩鍙?鈫?False锛堟病鏈夋墜鍔ㄥ綍鍒舵椂鍏ㄥ湴鍥炬墦鎬級
        鍙傛暟锛歴creen_x, screen_y = 鎬睆骞曞潗鏍?
        杩斿洖锛歍rue=鍦ㄨ寖鍥村唴鍙互鎵? False=瓒呭嚭鑼冨洿涓嶆墦锛堟垨娌℃湁鎵嬪姩褰曞埗骞冲彴锛?""
        pf = self._get_current_manual_platform()
        if pf is None:
            return True  # 娌℃湁鎵嬪姩褰曞埗骞冲彴鏃讹紝鍏ㄥ湴鍥炬墦鎬紙鐢ㄨ嚜鍔ㄥ綍鍒跺钩鍙帮級
        map_pos = self._screen_to_map(screen_x, screen_y)
        if map_pos is None:
            return False
        x_min, x_max = self._platform_x_range(pf)
        return x_min <= map_pos[0] <= x_max

    # ========================================================================
    # 銆愭ā鍧桞銆戝钩鍙板垽瀹氫紭鍖栵細閰嶅悎灏忓湴鍥剧豢绾垮拰浜虹墿鍏夌偣锛屽垽瀹氭€湪鍝釜骞冲彴
    # ========================================================================

    def _screen_to_map(self, screen_x, screen_y):
        """銆愭ā鍧桞銆戝睆骞曞潗鏍囪浆灏忓湴鍥惧潗鏍囷紙浠ヤ汉鐗╁厜鐐逛负鍙傝€冪偣锛屾瘮鍥哄畾scale鏇村噯锛?
        鐢ㄩ€旓細鎬湪灞忓箷涓殑浣嶇疆(YOLO妫€娴? 鈫?浼扮畻鎬湪灏忓湴鍥句笂鐨勫潗鏍?
        鍘熺悊锛氭€皬鍦板浘X = 浜虹墿灏忓湴鍥綳 + (鎬睆骞昘 - 浜虹墿灞忓箷X) * scale
              鎬皬鍦板浘Y = 浜虹墿灏忓湴鍥綴 + (鎬睆骞昚 - 浜虹墿灞忓箷Y) * scale
        鍙傛暟锛歴creen_x, screen_y = 鎬湪娓告垙鐢婚潰涓殑灞忓箷鍧愭爣
        杩斿洖锛?map_x, map_y) 浼扮畻鐨勫皬鍦板浘鍧愭爣锛涗汉鐗╀綅缃湭鐭ユ椂杩斿洖None"""
        # 浜虹墿灏忓湴鍥惧潗鏍囷紙榛勮壊鍏夌偣涓績锛?
        if not self._player_map_pos or not self._player_screen_pos:
            return None
        pmap_x, pmap_y = self._player_map_pos       # 浜虹墿鍦ㄥ皬鍦板浘涓婄殑鍧愭爣
        pscr_x, pscr_y = self._player_screen_pos     # 浜虹墿鍦ㄦ父鎴忕敾闈腑鐨勫睆骞曞潗鏍?
        # X鍜孻鐢ㄥ悇鑷殑scale锛堝皬鍦板浘X/Y鍘嬬缉姣旂巼涓嶅悓锛屽繀椤诲垎寮€绠楋級
        # scale_x闈犲乏鍙崇鐐规牎鍑嗘渶鍑嗭紝scale_y闈犱笂绔偣鏍″噯鎴栦汉鐗╀笂涓嬬Щ鍔ㄨ嚜鍔ㄦ牎鍑?
        scale_x = getattr(self, '_calibrated_scale_x', 0.10)
        scale_y = getattr(self, '_calibrated_scale_y', 0.10)
        # 浠ヤ汉鐗╀负鍙傝€冪偣锛岃绠楁€浉瀵逛簬浜虹墿鐨勫亸绉伙紝鍐嶈浆鎴愬皬鍦板浘鍋忕Щ
        map_x = pmap_x + (screen_x - pscr_x) * scale_x
        map_y = pmap_y + (screen_y - pscr_y) * scale_y
        return (map_x, map_y)

    def _update_scale_calibration(self):
        """銆愭ā鍧桞銆戣嚜鍔ㄦ牎鍑唖cale姣斾緥锛堜汉鐗╃Щ鍔ㄦ椂璁板綍灞忓箷鍜屽皬鍦板浘鍙樺寲锛岃绠楀疄闄呮瘮渚嬶級
        鐢ㄩ€旓細鏇夸唬鍥哄畾scale=0.10锛岃秺璺戣秺鍑?
        鍘熺悊锛?
          1. 璁板綍涓婁竴甯т汉鐗╃殑灞忓箷鍧愭爣鍜屽皬鍦板浘鍧愭爣
          2. 褰撳墠甯ц绠楀彉鍖栭噺 螖灞忓箷 鍜?螖灏忓湴鍥?
          3. 瀹為檯scale = 螖灏忓湴鍥?/ 螖灞忓箷锛堝彉鍖栭噺瓒冲澶ф椂鎵嶆洿鏂帮紝閬垮厤鍣０锛?
          4. 鐢ㄦ粦鍔ㄥ钩鍧囨洿鏂版牎鍑嗗€硷紙鏂板€煎崰20%锛屾棫鍊煎崰80%锛?
        璋冪敤鏃舵満锛氭瘡甯т汉鐗╀綅缃洿鏂板悗璋冪敤"""
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
            # X杞村彉鍖栭噺>20灞忓箷px鏃舵墠鏍″噯锛堥伩鍏嶉潤姝㈡椂鍣０锛?
            if dx_scr > 20 and dx_map > 1:
                scale_x = dx_map / dx_scr
                old_scale = getattr(self, '_calibrated_scale_x', 0.10)
                # 婊戝姩骞冲潎锛氭柊鍊煎崰20%锛屾棫鍊煎崰80%锛岄槻姝㈢獊鍙?
                self._calibrated_scale_x = old_scale * 0.8 + scale_x * 0.2
                self._map_screen_scale = self._calibrated_scale_x  # 鏇存柊涓籹cale
                # X鍜孻缂╂斁姣旂巼涓嶅悓锛孹鏍″噯鏃朵笉鏀筜
            # Y杞村彉鍖栭噺>15灞忓箷px鏃舵墠鐙珛鏍″噯锛堜汉鐗╀笂涓嬪钩鍙?姊瓙鏃讹級
            if dy_scr > 15 and dy_map > 1:
                scale_y = dy_map / dy_scr
                old_scale_y = getattr(self, '_calibrated_scale_y', 0.10)
                # Y鐙珛鏍″噯锛屼笉鍜宻cale_x姣旇緝锛圶/Y姣旂巼鏈潵灏变笉鍚岋級
                self._calibrated_scale_y = old_scale_y * 0.8 + scale_y * 0.2
        # 淇濆瓨褰撳墠甯у潗鏍囦緵涓嬫鏍″噯
        self._last_calib_map = cur_map
        self._last_calib_scr = cur_scr

    def _auto_calibrate_edges(self):
        """銆愭ā鍧桞銆戣嚜鍔ㄨ褰曚汉鐗╂渶宸?鏈€鍙崇鐐癸紙姣?绉掓娴嬩竴娆★紝浜虹墿绔欏湪杈圭紭3绉掕嚜鍔ㄨ褰曪級
        鐢ㄩ€旓細閫氳繃璁板綍浜虹墿鍦ㄦ渶宸﹀拰鏈€鍙虫椂鐨勫睆骞昘鍜屽皬鍦板浘X锛岃绠楀疄闄卻cale_x
        鍘熺悊锛?
          1. 姣?绉掓娴嬩竴娆′汉鐗╀綅缃紙閬垮厤姣忓抚姣旇緝锛屽噺灏戞€ц兘娑堣€楋級
          2. 姣旀渶宸︾偣鏇村乏 鈫?鏇存柊鏈€宸︾偣锛堣褰曞睆骞昘+灏忓湴鍥綳+灏忓湴鍥綴锛?
          3. 姣旀渶鍙崇偣鏇村彸 鈫?鏇存柊鏈€鍙崇偣
          4. 宸﹀彸閮借褰曞埌鍚?鈫?scale_x = (鍙冲皬鍦板浘X - 宸﹀皬鍦板浘X) / (鍙冲睆骞昘 - 宸﹀睆骞昘)
        浣跨敤鏂规硶锛氫汉鐗╃珯鍦ㄦ渶宸﹁竟3绉掕嚜鍔ㄨ褰曪紝鍐嶇珯鏈€鍙宠竟3绉掕嚜鍔ㄨ褰?
        鎵嬪姩鏍″噯浼樺厛锛歘manual_calib_done=True鏃讹紝璺宠繃鑷姩璁板綍锛堥伩鍏嶈鐩栨墜鍔ㄥ€硷級
        鍓綔鐢紙姘镐箙璁颁綇锛夛細
          1. 鑷姩璁板綍鐨勫乏鍙崇鐐瑰彲鑳戒笉鏄湡姝ｇ殑骞冲彴涓ょ锛堜汉鐗╂病璧板埌杈圭紭锛?
          2. 濡傛灉浜虹墿鍦ㄥ皬鍦板浘鑼冨洿鍐呯Щ鍔紝璁板綍鐨勮寖鍥村亸灏忥紝scale_x涓嶅噯
          3. 瑙ｅ喅锛氫笉鍑嗘椂鐢ㄦ墜鍔ㄨ褰曪紙浜虹墿鍋滃湪骞冲彴涓ょ鐐规寜閽級"""
        # 鎵嬪姩鏍″噯宸叉墽琛屾椂锛岃烦杩囪嚜鍔ㄨ褰曪紙閬垮厤瑕嗙洊鎵嬪姩鍊硷級
        if getattr(self, '_manual_calib_done', False):
            return
        # 姣?绉掓娴嬩竴娆★紙閬垮厤姣忓抚姣旇緝锛屽噺灏戞€ц兘娑堣€楋紝浜虹墿绔欏湪杈圭紭3绉掕嚜鍔ㄨ褰曪級
        now_ms = time.time() * 1000
        last_time = getattr(self, '_last_auto_calib_time', 0)
        if now_ms - last_time < 3000:
            return
        self._last_auto_calib_time = now_ms
        if not self._player_map_pos or not self._player_screen_pos:
            # 璋冭瘯锛氭瘡5绉掓墦鍗颁竴娆℃娴嬬姸鎬侊紝甯姪鎺掓煡
            _now = time.time()
            if not hasattr(self, '_last_calib_debug') or _now - self._last_calib_debug > 5:
                self._last_calib_debug = _now
                _debug_log("[鑷姩鏍″噯] 妫€娴嬬姸鎬? 灏忓湴鍥句綅缃?%s 灞忓箷浣嶇疆=%s (灞忓箷浣嶇疆闇€璁剧疆浜虹墿鐗瑰緛妯℃澘)" % (
                    'OK' if self._player_map_pos else 'None',
                    'OK' if self._player_screen_pos else 'None(闇€璁剧疆浜虹墿鐗瑰緛)'))
            return
        cur_scr_x = self._player_screen_pos[0]
        cur_scr_y = self._player_screen_pos[1]
        cur_map_x = self._player_map_pos[0]
        cur_map_y = self._player_map_pos[1]
        # 鍒濆鍖栧乏鍙崇鐐硅褰?
        left_pt = getattr(self, '_calib_left_pt', None)
        right_pt = getattr(self, '_calib_right_pt', None)
        old_left = left_pt
        old_right = right_pt
        # 鑷姩鏇存柊鏈€宸︾偣锛堝綋鍓嶅睆骞昘姣旇褰曠殑鏇村乏锛?
        if left_pt is None or cur_scr_x < left_pt[0]:
            # 璁板綍瀹屾暣鍧愭爣锛?灞忓箷X, 灞忓箷Y, 灏忓湴鍥綳, 灏忓湴鍥綴)
            self._calib_left_pt = (cur_scr_x, cur_scr_y, cur_map_x, cur_map_y)
            left_pt = self._calib_left_pt
        # 鑷姩鏇存柊鏈€鍙崇偣锛堝綋鍓嶅睆骞昘姣旇褰曠殑鏇村彸锛?
        if right_pt is None or cur_scr_x > right_pt[0]:
            # 璁板綍瀹屾暣鍧愭爣锛?灞忓箷X, 灞忓箷Y, 灏忓湴鍥綳, 灏忓湴鍥綴)
            self._calib_right_pt = (cur_scr_x, cur_scr_y, cur_map_x, cur_map_y)
            right_pt = self._calib_right_pt
        # 鑷姩鏇存柊鏈€楂樼偣锛堝綋鍓嶅睆骞昚姣旇褰曠殑鏇村皬=鏇撮珮锛?
        top_pt = getattr(self, '_calib_top_pt', None)
        old_top = top_pt
        if top_pt is None or cur_scr_y < top_pt[0]:
            self._calib_top_pt = (cur_scr_y, cur_map_y)
            top_pt = self._calib_top_pt
        # 宸﹀彸閮借褰曞埌鍚庯紝璁＄畻scale_x
        if left_pt and right_pt and right_pt[0] > left_pt[0] + 50:
            # 灞忓箷X宸?50px鎵嶈绠楋紙閬垮厤鑼冨洿澶皬涓嶅噯锛?
            dx_scr = right_pt[0] - left_pt[0]
            # 鍏煎鏃ф牸寮忥細鏂版牸寮忓皬鍦板浘X鍦ㄧ储寮?锛屾棫鏍煎紡鍦ㄧ储寮?
            lx_map = left_pt[2] if len(left_pt) >= 4 else left_pt[1]
            rx_map = right_pt[2] if len(right_pt) >= 4 else right_pt[1]
            dx_map = rx_map - lx_map
            if dx_map > 1:
                scale_x = dx_map / dx_scr
                # 鑷姩鏍″噯鐨剆cale_x鏉冮噸50%锛堝洜涓哄彲鑳戒笉鏄湡姝ｇ殑骞冲彴涓ょ锛?
                old_scale = getattr(self, '_calibrated_scale_x', 0.10)
                self._calibrated_scale_x = old_scale * 0.5 + scale_x * 0.5
                self._map_screen_scale = self._calibrated_scale_x
        # 绔偣鏈夋洿鏂板氨鑷姩淇濆瓨鍒版枃浠讹紙姘镐箙淇濆瓨锛岄噸鍚笉涓㈠け锛?
        if (old_left != self._calib_left_pt) or (old_right != self._calib_right_pt) or (old_top != self._calib_top_pt):
            self._save_calib()
            # 涓婄鐐规垨宸︾鐐瑰彉鍖栨椂閲嶆柊璁＄畻scale_y
            if old_top != self._calib_top_pt or old_left != self._calib_left_pt:
                self._recalc_scale_from_edges()

    def _manual_calibrate_left(self):
        """銆愭ā鍧桞銆戞墜鍔ㄨ褰曞乏绔偣锛堜汉鐗╁仠鍦ㄥ钩鍙版渶宸︾鍚庣偣鎸夐挳锛?
        鐢ㄩ€旓細绮剧‘璁板綍骞冲彴宸︾锛屽悓鏃朵綔涓篩杞翠笅绔偣
        鍘熺悊锛氳褰曞綋鍓嶄汉鐗╃殑灞忓箷(X,Y)鍜屽皬鍦板浘(X,Y)浣滀负宸︾鐐?
        鍓綔鐢細鎵嬪姩璁板綍鍚庡叧闂嚜鍔ㄨ褰曪紙閬垮厤鑷姩璁板綍瑕嗙洊鎵嬪姩鍊硷級"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._add_log("鎵嬪姩鏍″噯澶辫触锛氭湭妫€娴嬪埌浜虹墿浣嶇疆")
            return
        # 璁板綍瀹屾暣鍧愭爣锛?灞忓箷X, 灞忓箷Y, 灏忓湴鍥綳, 灏忓湴鍥綴)
        self._calib_left_pt = (self._player_screen_pos[0], self._player_screen_pos[1],
                               self._player_map_pos[0], self._player_map_pos[1])
        self._manual_calib_done = True  # 鏍囪鎵嬪姩鏍″噯宸叉墽琛岋紝鍏抽棴鑷姩璁板綍
        self._add_log("宸茶褰曞乏绔偣锛氬睆骞?%d,%d) 灏忓湴鍥?%d,%d)" % (
            self._player_screen_pos[0], self._player_screen_pos[1],
            self._player_map_pos[0], self._player_map_pos[1]))
        self._save_calib()
        self._recalc_scale_from_edges()

    def _manual_calibrate_right(self):
        """銆愭ā鍧桞銆戞墜鍔ㄨ褰曞彸绔偣锛堜汉鐗╁仠鍦ㄥ钩鍙版渶鍙崇鍚庣偣鎸夐挳锛?
        鐢ㄩ€旓細绮剧‘璁板綍骞冲彴鍙崇
        鍘熺悊锛氳褰曞綋鍓嶄汉鐗╃殑灞忓箷(X,Y)鍜屽皬鍦板浘(X,Y)浣滀负鍙崇鐐?
        鍓綔鐢細鎵嬪姩璁板綍鍚庡叧闂嚜鍔ㄨ褰曪紙閬垮厤鑷姩璁板綍瑕嗙洊鎵嬪姩鍊硷級"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._add_log("鎵嬪姩鏍″噯澶辫触锛氭湭妫€娴嬪埌浜虹墿浣嶇疆")
            return
        # 璁板綍瀹屾暣鍧愭爣锛?灞忓箷X, 灞忓箷Y, 灏忓湴鍥綳, 灏忓湴鍥綴)
        self._calib_right_pt = (self._player_screen_pos[0], self._player_screen_pos[1],
                                self._player_map_pos[0], self._player_map_pos[1])
        self._manual_calib_done = True  # 鏍囪鎵嬪姩鏍″噯宸叉墽琛岋紝鍏抽棴鑷姩璁板綍
        self._add_log("宸茶褰曞彸绔偣锛氬睆骞?%d,%d) 灏忓湴鍥?%d,%d)" % (
            self._player_screen_pos[0], self._player_screen_pos[1],
            self._player_map_pos[0], self._player_map_pos[1]))
        self._save_calib()
        self._recalc_scale_from_edges()

    def _manual_calibrate_top(self):
        """銆愭ā鍧桞銆戞墜鍔ㄨ褰曚笂绔偣锛堜汉鐗╃埇鍒版渶楂樺鍚庣偣鎸夐挳锛?
        鐢ㄩ€旓細Y杞存牎鍑嗭紝閰嶅悎宸︾鐐癸紙Y涓嬬鐐癸級绠楀嚭scale_y
        鍘熺悊锛氳褰曞綋鍓嶄汉鐗╃殑灞忓箷Y鍜屽皬鍦板浘Y浣滀负涓婄鐐?
        璁板綍鏍煎紡锛?灞忓箷Y, 灏忓湴鍥綴)"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._add_log("鎵嬪姩鏍″噯澶辫触锛氭湭妫€娴嬪埌浜虹墿浣嶇疆")
            return
        self._calib_top_pt = (self._player_screen_pos[1], self._player_map_pos[1])
        self._add_log("宸茶褰曚笂绔偣锛氬睆骞昚=%d 灏忓湴鍥綴=%d" % (
            self._player_screen_pos[1], self._player_map_pos[1]))
        self._save_calib()
        self._recalc_scale_from_edges()

    def _start_auto_calibration(self):
        """銆愭ā鍧桞銆戣嚜鍔ㄦ牎鍑嗭紙浜旀娴佺▼锛屾瘡娆＄偣鍊嶇巼鎸夐挳鎺ㄨ繘涓€姝ワ級
        绗?娆＄偣(0鈫?)锛氳褰曞熀鐐癸紝钂欐澘鍑虹豢钃濆渾锛屽彲钂欐澘鎷栧姩鍒扮壒鑹茶儗鏅綅缃?
        绗?娆＄偣(1鈫?)锛氭埅鍥剧豢钃濆渾浣嶇疆鐨勮儗鏅浘淇濆瓨涓烘ā鏉匡紝寮€濮嬫ā鏉垮尮閰嶈窡韪紝钂欐澘鐢荤豢/钃濈┖蹇冨渾
        绗?娆＄偣(2鈫?)锛氫汉鐗╄蛋鍒扮豢鑹插渾涓婏紝璁板綍缁跨偣灏忓湴鍥惧潗鏍囷紙浜虹墿鍏夌偣浣嶇疆锛?
        绗?娆＄偣(3鈫?)锛氫汉鐗╄蛋鍒拌摑鑹插渾涓婏紝璁板綍钃濈偣灏忓湴鍥惧潗鏍?
        绗?娆＄偣(4鈫?)锛氳绠楀€嶇巼锛圶/Y鍒嗗紑锛夛紝鍏抽棴鎵€鏈夋樉绀猴紝娓呯┖鐐逛綅锛屼繚瀛樺€嶇巼"""
        # 銆愯皟璇?-鍏ュ彛銆戞柟娉曡璋冪敤锛岃緭鍑哄綋鍓峴tage鍜屼汉鐗╀綅缃姸鎬?
        self._rlog("銆愯皟璇?銆慒11琚皟鐢?stage=%d, 灞忓箷浣嶇疆=%s, 灏忓湴鍥句綅缃?%s" % (
            self._auto_calib_stage, self._player_screen_pos, self._player_map_pos))
        # 闃舵4鈫?锛氳绠楀€嶇巼锛屽叧闂樉绀猴紝娓呯┖鐐逛綅鍜屾ā鏉匡紝淇濆瓨鍊嶇巼
        if self._auto_calib_stage == 4:
            self._finish_auto_calibration()
            self._auto_calib_stage = 0
            self._auto_calib_base = None
            self._auto_calib_green_map = None
            self._auto_calib_blue_map = None
            self._auto_calib_green_screen = None
            self._auto_calib_blue_screen = None
            self._auto_calib_green_offset = (400, 0)
            self._auto_calib_blue_offset = (0, -400)
            self._auto_calib_dragging = None
            self._calib_green_template = None
            self._calib_blue_template = None
            self._calib_green_match_pos = None
            self._calib_blue_match_pos = None
            self._add_log("銆愭牎鍑嗗畬鎴愩€戝€嶇巼宸蹭繚瀛橈紝鐐逛綅宸叉竻绌猴紝鏄剧ず宸插叧闂?)
            return
        # 銆愬叧閿€戠洿鎺ョ敤涓诲惊鐜疄鏃舵洿鏂扮殑_player_map_pos锛屽厜鐐瑰湪鍝氨璁板綍鍦ㄥ摢锛屼笉閲嶆柊妫€娴嬮伩鍏嶅潗鏍囦笉鍚屾
        # 璋冭瘯锛氳褰曞綋鍓峗player_map_pos鍊煎埌鏂囦欢
        try:
            with open(os.path.join(DATA_DIR, "calib_debug.log"), "a", encoding="utf-8") as f:
                f.write("[%s] 鎸塅11鍓?stage=%d _player_map_pos=%s _player_screen_pos=%s\n" % (
                    time.strftime("%H:%M:%S"), self._auto_calib_stage,
                    str(self._player_map_pos), str(self._player_screen_pos)))
        except Exception:
            pass
        # 浜虹墿浣嶇疆妫€鏌ワ細stage 0鈫?/1鈫?闇€瑕佸睆骞?灏忓湴鍥惧潗鏍囷紱stage 2鈫?/3鈫?鍙渶瑕佸皬鍦板浘鍧愭爣
        cur_sx = cur_sy = cur_mx = cur_my = 0
        if self._auto_calib_stage in (0, 1):
            if not self._player_map_pos or not self._player_screen_pos:
                self._add_log("鑷姩鏍″噯澶辫触锛氭湭妫€娴嬪埌浜虹墿浣嶇疆锛岃纭繚浜虹墿鍦ㄥ睆骞曞唴")
                return
            cur_sx, cur_sy = self._player_screen_pos[0], self._player_screen_pos[1]
            cur_mx, cur_my = self._player_map_pos[0], self._player_map_pos[1]
        elif self._auto_calib_stage in (2, 3):
            if not self._player_map_pos:
                # 绗笁姝ュけ璐ユ彁绀虹豢鍏夊湀锛岀鍥涙澶辫触鎻愮ず钃濆厜鍦?
                if self._auto_calib_stage == 2:
                    self._add_log("缁垮厜鍦堜綅缃褰曞け璐?璇烽噸鎸?F11", (0, 0, 255))
                else:
                    self._add_log("钃濆厜鍦堜綅缃褰曞け璐?璇烽噸鎸?F11", (0, 0, 255))
                # 澶辫触涓夋鍚庣洿鎺ョ粨鏉熸暣涓繃绋?
                self._calib_retry_count = getattr(self, '_calib_retry_count', 0) + 1
                if self._calib_retry_count >= 3:
                    self._add_log("杩炵画3娆″け璐ワ紝鏍″噯杩囩▼宸插叧闂?, (0, 0, 255))
                    self._auto_calib_stage = 0
                    self._auto_calib_base = None
                    self._calib_green_template = None
                    self._calib_blue_template = None
                    self._calib_retry_count = 0
                    # 鍏抽棴钂欐澘鏄剧ず
                    if self._overlay_hwnd:
                        user32.ShowWindow(self._overlay_hwnd, 0)
                return
            cur_mx, cur_my = self._player_map_pos[0], self._player_map_pos[1]
        # 闃舵0鈫?锛氬紑濮嬫牎鍑嗭紙鍏堟竻绌烘棫鏁版嵁鍐嶅綍鍏ワ級
        if self._auto_calib_stage == 0:
            # 鍏堟竻绌轰笂涓€杞殑鏃ф暟鎹?
            self._auto_calib_base = None
            self._auto_calib_green_map = None
            self._auto_calib_blue_map = None
            self._auto_calib_green_screen = None
            self._auto_calib_blue_screen = None
            self._auto_calib_dragging = None
            self._calib_green_template = None
            self._calib_blue_template = None
            self._calib_green_match_pos = None
            self._calib_blue_match_pos = None
            # stage=1涓嶅浐瀹氬熀鐐癸紝鍩虹偣鍦ㄤ富寰幆涓疄鏃惰窡闅忎汉鐗╃Щ鍔?
            # 缁跨偣钃濈偣鐢ㄧ浉瀵瑰亸绉诲瓨鍌紝榛樿鍙?00/涓?00锛岀敤鎴峰彲钂欐澘鎷栧姩璋冩暣
            self._auto_calib_green_offset = (400, 0)
            self._auto_calib_blue_offset = (0, -400)
            self._auto_calib_stage = 1
            self._add_log("銆愮1姝?5銆戣绉诲姩浜虹墿鎵剧壒鑹蹭綅缃紝绾㈣壊鍩虹偣璺熼殢浜虹墿绉诲姩锛屾嫋鍔ㄧ豢鐐硅摑鐐硅皟鏁翠綅缃紝瀹氬ソ鍚庣偣鍊嶇巼")
            # 璋冭瘯锛氬啓鍏ユ棩蹇楁枃浠?
            try:
                with open(os.path.join(DATA_DIR, "calib_debug.log"), "a", encoding="utf-8") as f:
                    f.write("[%s] stage0鈫? 寮€濮嬫牎鍑?浜虹墿灏忓湴鍥?(%d,%d) 灞忓箷=(%d,%d)\n" % (
                        time.strftime("%H:%M:%S"), cur_mx, cur_my, cur_sx, cur_sy))
            except Exception:
                pass
            return
        # 闃舵1鈫?锛氬浐瀹氬熀鐐癸紙璁板綍褰撳墠浜虹墿浣嶇疆锛夛紝鐢ㄥ亸绉昏绠楃豢鐐硅摑鐐瑰睆骞曞潗鏍囷紝鎴浘妯℃澘
        if self._auto_calib_stage == 1:
            # 銆愯皟璇?-涓氬姟灞傘€戣繘鍏ラ樁娈?鈫?锛岃緭鍑哄綋鍓嶇姸鎬?
            self._rlog("銆愯皟璇?銆戣繘鍏ョ浜屾 stage=1, 浜虹墿灞忓箷=(%d,%d) 灏忓湴鍥?(%d,%d)" % (cur_sx, cur_sy, cur_mx, cur_my))
            # 鏄剧ず鎻愮ず锛氳绛夊緟鑷姩鎴浘淇濆瓨
            self._add_log("璇风瓑寰呰嚜鍔ㄦ埅鍥句繚瀛?..", (255, 165, 0))
            # 鍥哄畾鍩虹偣锛氳褰曞綋鍓嶄汉鐗╁睆骞曞潗鏍?灏忓湴鍥惧潗鏍?
            self._auto_calib_base = (cur_sx, cur_sy, cur_mx, cur_my)
            # 鐢ㄧ浉瀵瑰亸绉昏绠楃豢鐐硅摑鐐瑰睆骞曞潗鏍囷紙鍥哄畾涓嬫潵锛宻tage>=2涓嶅啀璺熼殢浜虹墿锛?
            goff = self._auto_calib_green_offset
            boff = self._auto_calib_blue_offset
            self._auto_calib_green_screen = (cur_sx + goff[0], cur_sy + goff[1])
            self._auto_calib_blue_screen = (cur_sx + boff[0], cur_sy + boff[1])
            # 銆愯皟璇?-鍧愭爣灞傘€戣緭鍑虹豢鐐硅摑鐐瑰睆骞曞潗鏍囧拰鍋忕Щ
            self._rlog("銆愯皟璇?銆戠豢鐐瑰睆骞?(%d,%d) 鍋忕Щ=(%d,%d), 钃濈偣灞忓箷=(%d,%d) 鍋忕Щ=(%d,%d)" % (
                self._auto_calib_green_screen[0], self._auto_calib_green_screen[1], goff[0], goff[1],
                self._auto_calib_blue_screen[0], self._auto_calib_blue_screen[1], boff[0], boff[1]))
            # 鎴浘鍓嶉殣钘忚挋鏉匡紝閬垮厤鎴埌缁跨偣钃濈偣鏈韩锛堟ā鏉垮繀椤绘槸绾儗鏅壒鑹诧級
            if self._overlay_hwnd:
                user32.ShowWindow(self._overlay_hwnd, 0)  # SW_HIDE
                time.sleep(0.1)  # 绛夊緟绐楀彛瀹屽叏闅愯棌鐢熸晥
            # 銆愯皟璇?-鍔ㄤ綔灞傘€戣挋鏉垮凡闅愯棌锛屽紑濮嬫埅鍥?
            self._rlog("銆愯皟璇?銆戣挋鏉垮凡闅愯棌锛屽紑濮嬫埅鍥剧豢鐐规ā鏉?)
            # 鎴浘缁跨偣浣嶇疆鐨勮儗鏅ā鏉匡紙鍔犲欢鏃堕敊寮€1绉掞紝閬垮厤杩炵画鎴浘鍐茬獊锛?
            _green_ok = False
            for _green_try in range(3):
                _g_ret = self._capture_calib_template(self._auto_calib_green_screen, 'green')
                # 銆愯皟璇?-璇嗗埆灞傘€戣緭鍑烘瘡娆℃埅鍥剧粨鏋?
                if _g_ret and self._calib_green_template is not None:
                    _gh, _gw = self._calib_green_template.shape[:2]
                    self._rlog("銆愯皟璇?銆戠豢鐐规埅鍥剧%d娆? 杩斿洖=%s 妯℃澘灏哄=%dx%d" % (_green_try + 1, _g_ret, _gw, _gh))
                    if _gh == self._calib_template_size and _gw == self._calib_template_size:
                        _green_ok = True
                        self._add_log("缁胯壊鍏夊湀妯℃澘淇濆瓨鎴愬姛 %dx%d" % (_gw, _gh), (0, 200, 0))
                        break
                else:
                    self._rlog("銆愯皟璇?銆戠豢鐐规埅鍥剧%d娆? 杩斿洖=%s 妯℃澘=None" % (_green_try + 1, _g_ret))
                if _green_try < 2:
                    time.sleep(0.3)
            if not _green_ok:
                # 鎴浘澶辫触鍚庡厛鎭㈠钂欐澘鏄剧ず锛岄伩鍏嶈挋鏉夸竴鐩撮殣钘忕敤鎴蜂互涓哄崱浣?
                if self._overlay_hwnd:
                    user32.ShowWindow(self._overlay_hwnd, 5)  # SW_SHOW
                self._rlog("銆愯皟璇?銆戠豢鐐规埅鍥惧け璐ワ紝鎭㈠钂欐澘锛宻tage淇濇寔1")
                self._add_log("鎴浘淇濆瓨澶辫触 璇烽噸鏂版寜 F11", (0, 0, 255))
                # 澶辫触涓夋鍚庣洿鎺ュ叧闂暣涓繃绋嬶紝涓嶅啀鏄剧ず鍩虹偣锛屼笉鍥炵涓€姝?
                self._calib_retry_count = getattr(self, '_calib_retry_count', 0) + 1
                if self._calib_retry_count >= 3:
                    self._add_log("杩炵画3娆″け璐ワ紝鏍″噯杩囩▼宸插叧闂?, (0, 0, 255))
                    self._auto_calib_stage = 0
                    self._auto_calib_base = None
                    self._calib_retry_count = 0
                    # 鍏抽棴钂欐澘鏄剧ず
                    if self._overlay_hwnd:
                        user32.ShowWindow(self._overlay_hwnd, 0)
                return
            time.sleep(1.0)  # 閿欏紑鎴浘1绉掞紝閬垮厤mss杩炵画璋冪敤鍐茬獊
            # 銆愯皟璇?-璇嗗埆灞傘€戝紑濮嬫埅鍥捐摑鐐规ā鏉?
            self._rlog("銆愯皟璇?銆戠豢鐐规埅鍥炬垚鍔燂紝绛夊緟1绉掑悗寮€濮嬫埅鍥捐摑鐐规ā鏉?)
            # 鎴浘钃濈偣浣嶇疆鐨勮儗鏅ā鏉?
            _blue_ok = False
            for _blue_try in range(3):
                _b_ret = self._capture_calib_template(self._auto_calib_blue_screen, 'blue')
                # 銆愯皟璇?-璇嗗埆灞傘€戣緭鍑烘瘡娆¤摑鐐规埅鍥剧粨鏋?
                if _b_ret and self._calib_blue_template is not None:
                    _bh, _bw = self._calib_blue_template.shape[:2]
                    self._rlog("銆愯皟璇?銆戣摑鐐规埅鍥剧%d娆? 杩斿洖=%s 妯℃澘灏哄=%dx%d" % (_blue_try + 1, _b_ret, _bw, _bh))
                    if _bh == self._calib_template_size and _bw == self._calib_template_size:
                        _blue_ok = True
                        self._add_log("钃濊壊鍏夊湀妯℃澘淇濆瓨鎴愬姛 %dx%d" % (_bw, _bh), (0, 200, 0))
                        break
                else:
                    self._rlog("銆愯皟璇?銆戣摑鐐规埅鍥剧%d娆? 杩斿洖=%s 妯℃澘=None" % (_blue_try + 1, _b_ret))
                if _blue_try < 2:
                    time.sleep(0.3)
            if not _blue_ok:
                # 鎴浘澶辫触鍚庡厛鎭㈠钂欐澘鏄剧ず锛岄伩鍏嶈挋鏉夸竴鐩撮殣钘忕敤鎴蜂互涓哄崱浣?
                if self._overlay_hwnd:
                    user32.ShowWindow(self._overlay_hwnd, 5)  # SW_SHOW
                self._rlog("銆愯皟璇?銆戣摑鐐规埅鍥惧け璐ワ紝鎭㈠钂欐澘锛宻tage淇濇寔1")
                self._add_log("鎴浘淇濆瓨澶辫触 璇烽噸鏂版寜 F11", (0, 0, 255))
                # 澶辫触涓夋鍚庣洿鎺ュ叧闂暣涓繃绋嬶紝涓嶅啀鏄剧ず鍩虹偣锛屼笉鍥炵涓€姝?
                self._calib_retry_count = getattr(self, '_calib_retry_count', 0) + 1
                if self._calib_retry_count >= 3:
                    self._add_log("杩炵画3娆″け璐ワ紝鏍″噯杩囩▼宸插叧闂?, (0, 0, 255))
                    self._auto_calib_stage = 0
                    self._auto_calib_base = None
                    self._calib_green_template = None
                    self._calib_retry_count = 0
                    # 鍏抽棴钂欐澘鏄剧ず
                    if self._overlay_hwnd:
                        user32.ShowWindow(self._overlay_hwnd, 0)
                return
            time.sleep(0.05)  # 绛夊緟鎴浘瀹屾垚
            # 鎭㈠钂欐澘鏄剧ず
            # 銆愯皟璇?-涓氬姟灞傘€戞埅鍥惧叏閮ㄦ垚鍔燂紝鍏堣stage=2鍐嶆仮澶嶈挋鏉匡紝閬垮厤绠ご闂儊
            self._rlog("銆愯皟璇?銆戠豢鐐硅摑鐐规埅鍥惧叏閮ㄦ垚鍔燂紝stage浠?鍙樻垚2锛屽啀鎭㈠钂欐澘鏄剧ず")
            self._auto_calib_stage = 2
            # 鍏堣stage=2鍐嶆仮澶嶈挋鏉匡紝杩欐牱鎭㈠钂欐澘鏃剁洿鎺ユ樉绀虹豢鍦堣摑鍦堬紝涓嶄細鏄剧ず绠ご闂儊
            if self._overlay_hwnd:
                user32.ShowWindow(self._overlay_hwnd, 5)  # SW_SHOW
                time.sleep(0.05)  # 绛夊緟绐楀彛鏄剧ず鐢熸晥
            self._add_log("銆愮2姝?5銆戝熀鐐瑰凡鍥哄畾(灞忓箷%d,%d 灏忓湴鍥?d,%d)锛屾ā鏉挎埅鍥惧畬鎴愶紝寮€濮嬭窡韪€傝浜虹墿璧板埌缁胯壊鍦嗕笂锛岀珯濂藉悗鐐瑰€嶇巼" % (
                cur_sx, cur_sy, cur_mx, cur_my))
            # 璋冭瘯锛氬啓鍏ユ棩蹇楁枃浠?
            try:
                with open(os.path.join(DATA_DIR, "calib_debug.log"), "a", encoding="utf-8") as f:
                    f.write("[%s] stage1鈫? 鍥哄畾鍩虹偣 灞忓箷=(%d,%d) 灏忓湴鍥?(%d,%d)\n" % (
                        time.strftime("%H:%M:%S"), cur_sx, cur_sy, cur_mx, cur_my))
            except Exception:
                pass
            return
        # 闃舵2鈫?锛氫汉鐗╄蛋鍒扮豢鍦嗕笂锛岃褰曠豢鐐瑰皬鍦板浘鍧愭爣
        if self._auto_calib_stage == 2:
            self._auto_calib_green_map = (cur_mx, cur_my)
            self._auto_calib_stage = 3
            self._add_log("銆愮3姝?5銆戠豢鐐瑰凡璁板綍(灏忓湴鍥?d,%d)锛岃浜虹墿璧板埌钃濊壊鍦嗕笂锛岀珯濂藉悗鐐瑰€嶇巼" % (cur_mx, cur_my))
            # 璋冭瘯锛氬啓鍏ユ棩蹇楁枃浠?
            try:
                with open(os.path.join(DATA_DIR, "calib_debug.log"), "a", encoding="utf-8") as f:
                    f.write("[%s] stage2鈫? 璁板綍缁跨偣 灏忓湴鍥?(%d,%d)\n" % (time.strftime("%H:%M:%S"), cur_mx, cur_my))
            except Exception:
                pass
            return
        # 闃舵3鈫?锛氫汉鐗╄蛋鍒拌摑鍦嗕笂锛岃褰曡摑鐐瑰皬鍦板浘鍧愭爣
        if self._auto_calib_stage == 3:
            self._auto_calib_blue_map = (cur_mx, cur_my)
            self._auto_calib_stage = 4
            self._add_log("銆愮4姝?5銆戣摑鐐瑰凡璁板綍(灏忓湴鍥?d,%d)锛屽啀鐐逛竴娆″€嶇巼璁＄畻鍊嶇巼骞跺叧闂? % (cur_mx, cur_my))
            # 璋冭瘯锛氬啓鍏ユ棩蹇楁枃浠?
            try:
                with open(os.path.join(DATA_DIR, "calib_debug.log"), "a", encoding="utf-8") as f:
                    f.write("[%s] stage3鈫? 璁板綍钃濈偣 灏忓湴鍥?(%d,%d)\n" % (time.strftime("%H:%M:%S"), cur_mx, cur_my))
            except Exception:
                pass
            return

    def _finish_auto_calibration(self):
        """銆愭ā鍧桞銆戝畬鎴愯嚜鍔ㄦ牎鍑嗭細鐢ㄥ疄闄呭睆骞曡窛绂诲拰灏忓湴鍥捐窛绂昏绠梥cale_x鍜宻cale_y"""
        if not self._auto_calib_base or not self._auto_calib_green_map or not self._auto_calib_blue_map:
            self._add_log("鑷姩鏍″噯澶辫触锛氭暟鎹笉瀹屾暣")
            return
        if not self._auto_calib_green_screen or not self._auto_calib_blue_screen:
            self._add_log("鑷姩鏍″噯澶辫触锛氬睆骞曚綅缃笉瀹屾暣")
            return
        base_sx, base_sy, base_mx, base_my = self._auto_calib_base
        green_sx, green_sy = self._auto_calib_green_screen
        blue_sx, blue_sy = self._auto_calib_blue_screen
        green_mx, green_my = self._auto_calib_green_map
        blue_mx, blue_my = self._auto_calib_blue_map
        # 瀹為檯灞忓箷璺濈锛堣挋鏉挎嫋鍔ㄥ悗鐨勫€硷紝涓嶆槸鍥哄畾800/400锛?
        dx_screen = green_sx - base_sx
        dy_screen = base_sy - blue_sy
        # 灏忓湴鍥捐窛绂伙紙浜虹墿璧板埌鐗硅壊浣嶇疆鍚庤褰曠殑鍏夌偣浣嶇疆宸級
        dx_map = green_mx - base_mx
        dy_map = base_my - blue_my
        if dx_screen <= 0 or dx_map <= 0:
            self._add_log("鑷姩鏍″噯澶辫触锛氱豢鐐瑰簲鍦ㄥ熀鐐瑰彸鏂癸紝灞忓箷璺濈=%d 灏忓湴鍥捐窛绂?%d" % (dx_screen, dx_map))
            return
        if dy_screen <= 0 or dy_map <= 0:
            self._add_log("鑷姩鏍″噯澶辫触锛氳摑鐐瑰簲鍦ㄥ熀鐐逛笂鏂癸紝灞忓箷璺濈=%d 灏忓湴鍥捐窛绂?%d" % (dy_screen, dy_map))
            return
        scale_x = dx_map / float(dx_screen)
        scale_y = dy_map / float(dy_screen)
        self._calibrated_scale_x = scale_x
        self._calibrated_scale_y = scale_y
        self._map_screen_scale = scale_x
        # 娉ㄦ剰锛氫笉鍐嶈缃畇tage=3锛岀敱_start_auto_calibration鍦╯tage=4鈫?鏃惰皟鐢ㄦ湰鍑芥暟锛岃皟鐢ㄥ悗鐩存帴娓呯┖骞跺叧闂?
        self._add_log("鏍″噯瀹屾垚锛歴cale_x=%.4f (灏忓湴鍥?dpx/灞忓箷%dpx) scale_y=%.4f (灏忓湴鍥?dpx/灞忓箷%dpx)" % (
            scale_x, dx_map, dx_screen, scale_y, dy_map, dy_screen))
        # 淇濆瓨鍒扮鐐规枃浠讹紙鍏煎鏃ф牸寮忥級
        self._calib_left_pt = (base_sx, base_sy, base_mx, base_my)
        self._calib_right_pt = (green_sx, green_sy, green_mx, green_my)
        self._calib_top_pt = (blue_sy, blue_my)
        self._save_calib()

    def _recalc_auto_calib_scale(self):
        """銆愭ā鍧桞銆戣挋鏉挎嫋鍔ㄧ豢鐐硅摑鐐瑰悗閲嶆柊璁＄畻灞忓箷璺濈锛堜粎鏇存柊灞忓箷鍧愭爣锛屽€嶇巼绛変汉鐗╄蛋瀹屽啀绠楋級"""
        # 钂欐澘鎷栧姩鍙敼鍙樺睆骞曚綅缃紝灏忓湴鍥句綅缃繕娌¤褰曪紝鎵€浠ヨ繖閲屼笉璁＄畻鍊嶇巼
        pass

    def _capture_calib_template(self, screen_pos, color_tag):
        """銆愭ā鍧桞銆戞埅鍙栨寚瀹氬睆骞曚綅缃懆鍥寸殑鑳屾櫙鍥句綔涓烘ā鏉匡紙鐢ㄤ簬妯℃澘鍖归厤璺熻釜鐗硅壊浣嶇疆锛?
        鍙傛暟锛歴creen_pos=(灞忓箷X,灞忓箷Y)锛宑olor_tag='green'/'blue'
        杩斿洖锛歍rue鎴愬姛锛孎alse澶辫触
        鎴浘鍚屾椂淇濆瓨鍒癱alib_screenshots鏂囦欢澶癸紝鏂逛究鐢ㄦ埛纭鎴浘鏄惁姝ｇ‘"""
        try:
            frame = self._capture_window()
            if frame is None:
                return False
            h, w = frame.shape[:2]
            sx, sy = screen_pos
            half = self._calib_template_size // 2
            # 纭繚妯℃澘瀹屾暣55x55锛岄潬杩戣竟缂樿嚜鍔ㄥ唴绉伙紙閬垮厤杈圭晫鎴柇瀵艰嚧鍖归厤澶辫触锛?
            sx = max(half, min(w - half - 1, sx))
            sy = max(half, min(h - half - 1, sy))
            x1 = sx - half
            y1 = sy - half
            x2 = sx + half
            y2 = sy + half
            template = frame[y1:y2, x1:x2].copy()
            if color_tag == 'green':
                self._calib_green_template = template
            else:
                self._calib_blue_template = template
            # 淇濆瓨鎴浘鍒版枃浠讹紝鏂逛究鐢ㄦ埛纭鎴浘鏄惁姝ｇ‘
            calib_dir = os.path.join(DATA_DIR, "calib_screenshots")
            if not os.path.exists(calib_dir):
                os.makedirs(calib_dir)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            save_path = os.path.join(calib_dir, "%s_%s.png" % (color_tag, timestamp))
            cv2.imwrite(save_path, template)
            _debug_log("[鏍″噯妯℃澘] %s鎴浘鎴愬姛 %dx%d at (%d,%d), 宸蹭繚瀛樺埌 %s" % (color_tag, template.shape[1], template.shape[0], sx, sy, save_path))
            return True
        except Exception as e:
            _debug_log("[鏍″噯妯℃澘] 鎴浘澶辫触: %s" % e)
            return False

    def _match_calib_templates(self):
        """銆愭ā鍧桞銆戞ā鏉垮尮閰嶏細鍦ㄥ綋鍓嶆父鎴忕敾闈腑鎼滅储缁胯摑妯℃澘鐨勪綅缃紝鏇存柊鍖归厤鍧愭爣
        浠呭湪鏍″噯stage>=2鏃惰皟鐢紝姣忓抚鎴栨瘡鍑犲抚璋冪敤涓€娆?
        娣诲姞璋冭瘯淇℃伅锛氳緭鍑哄尮閰嶅€煎拰浣嶇疆锛屼繚瀛樿皟璇曞浘锛屾柟渚挎帓鏌ヨ瘑鍒笉鍒扮殑闂"""
        if self._auto_calib_stage < 2:
            return
        if self._calib_green_template is None and self._calib_blue_template is None:
            return
        try:
            frame = self._capture_window()
            if frame is None:
                return
            debug_frame = frame.copy()  # 璋冭瘯鍥惧壇鏈?
            # 濂囧伓甯т氦鏇垮尮閰嶏細濂囨暟甯у尮閰嶇豢鐐癸紝鍋舵暟甯у尮閰嶈摑鐐癸紝涓€娆″彧鍖归厤涓€涓紝閬垮厤浜掔浉骞叉壈
            if self.frame_count % 2 == 1:
                # 鍖归厤缁跨偣妯℃澘
                if self._calib_green_template is not None:
                    res = cv2.matchTemplate(frame, self._calib_green_template, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    th, tw = self._calib_green_template.shape[:2]
                    self._last_green_match_val = max_val
                    _debug_log("[鏍″噯鍖归厤] 缁跨偣鍖归厤鍊? %.4f, 闃堝€? %.2f, 浣嶇疆: (%d,%d)" % (
                        max_val, self._calib_match_threshold, max_loc[0], max_loc[1]))
                    # 杈撳嚭鍖归厤鍊煎埌UI鏃ュ織锛屾柟渚挎帓鏌?
                    if self.frame_count % 30 == 0:
                        self._rlog("銆愬尮閰嶃€戠豢鐐瑰€?%.3f 钃濈偣鍊?%.3f 闃堝€?%.2f" % (
                            max_val, getattr(self, '_last_blue_match_val', 0), self._calib_match_threshold))
                    # 鍦ㄨ皟璇曞浘涓婄敾鍑虹豢鐐瑰尮閰嶄綅缃拰鍖归厤鍊?
                    cv2.rectangle(debug_frame, max_loc, (max_loc[0] + tw, max_loc[1] + th), (0, 255, 0), 2)
                    cv2.putText(debug_frame, "G:%.3f" % max_val, (max_loc[0], max_loc[1] - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    if max_val >= self._calib_match_threshold:
                        self._calib_green_match_pos = (max_loc[0] + tw // 2, max_loc[1] + th // 2)
                    else:
                        self._calib_green_match_pos = None
            else:
                # 鍖归厤钃濈偣妯℃澘
                if self._calib_blue_template is not None:
                    res = cv2.matchTemplate(frame, self._calib_blue_template, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    th, tw = self._calib_blue_template.shape[:2]
                    self._last_blue_match_val = max_val
                    _debug_log("[鏍″噯鍖归厤] 钃濈偣鍖归厤鍊? %.4f, 闃堝€? %.2f, 浣嶇疆: (%d,%d)" % (
                        max_val, self._calib_match_threshold, max_loc[0], max_loc[1]))
                    # 鍦ㄨ皟璇曞浘涓婄敾鍑鸿摑鐐瑰尮閰嶄綅缃拰鍖归厤鍊?
                    cv2.rectangle(debug_frame, max_loc, (max_loc[0] + tw, max_loc[1] + th), (255, 0, 0), 2)
                    cv2.putText(debug_frame, "B:%.3f" % max_val, (max_loc[0], max_loc[1] - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
                    if max_val >= self._calib_match_threshold:
                        self._calib_blue_match_pos = (max_loc[0] + tw // 2, max_loc[1] + th // 2)
                    else:
                        self._calib_blue_match_pos = None
            # 淇濆瓨璋冭瘯鍥惧埌calib_screenshots鏂囦欢澶?
            calib_dir = os.path.join(DATA_DIR, "calib_screenshots")
            if not os.path.exists(calib_dir):
                os.makedirs(calib_dir)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            debug_path = os.path.join(calib_dir, "match_debug_%s.png" % timestamp)
            cv2.imwrite(debug_path, debug_frame)
            _debug_log("[鏍″噯鍖归厤] 璋冭瘯鍥惧凡淇濆瓨鍒?%s" % debug_path)
        except Exception as e:
            _debug_log("[鏍″噯妯℃澘鍖归厤] 寮傚父: %s" % e)

    def _save_calib(self):
        """淇濆瓨绔偣鏁版嵁鍒版枃浠讹紙宸?鍙?涓婄鐐?+ 鍊嶇巼鍊硷級"""
        try:
            calib_file = os.path.join(DATA_DIR, "route_%d_calib.json" % self.current_route)
            with open(calib_file, "w", encoding="utf-8") as f:
                json.dump({
                    "calib_left": self._calib_left_pt,
                    "calib_right": self._calib_right_pt,
                    "calib_top": getattr(self, '_calib_top_pt', None),
                    "scale_x": getattr(self, '_calibrated_scale_x', None),
                    "scale_y": getattr(self, '_calibrated_scale_y', None),
                }, f, indent=2)
        except Exception:
            pass

    def _recalc_scale_from_region(self):
        """銆愭ā鍧桞銆戞牴鎹皬鍦板浘鍖哄煙灏哄璁＄畻X/Y scale鍒濆鍊?
        鍘熺悊锛歴cale_x=FIXED_W/灏忓湴鍥惧搴︼紝scale_y=MAP_H/灏忓湴鍥鹃珮搴?
        X鍜孻缂╂斁姣旂巼涓嶅悓锛屽繀椤诲垎寮€绠楋紝涓嶈兘榛樿鐩哥瓑"""
        r = getattr(self, 'map_area_rect', None)
        if r and r["width"] > 0 and r["height"] > 0:
            self._calibrated_scale_x = FIXED_W / r["width"]
            self._calibrated_scale_y = MAP_H / r["height"]
            self._map_screen_scale = self._calibrated_scale_x
            print("[scale] 鍒濆鍊? X=%.4f Y=%.4f (鍖哄煙%dx%d)" % (
                self._calibrated_scale_x, self._calibrated_scale_y, r["width"], r["height"]))

    def _recalc_scale_from_edges(self):
        """銆愭ā鍧桞銆戞牴鎹鐐归噸鏂拌绠梥cale_x鍜宻cale_y锛堟墜鍔ㄨ褰曞悗璋冪敤锛?
        鍘熺悊锛歴cale_x = (鍙冲皬鍦板浘X - 宸﹀皬鍦板浘X) / (鍙冲睆骞昘 - 宸﹀睆骞昘)
              scale_y = (涓婄鐐瑰皬鍦板浘Y - 宸︾鐐瑰皬鍦板浘Y) / (宸︾鐐瑰睆骞昚 - 涓婄鐐瑰睆骞昚)
        璁板綍鏍煎紡锛氬乏/鍙崇鐐?(灞忓箷X, 灞忓箷Y, 灏忓湴鍥綳, 灏忓湴鍥綴)锛屼笂绔偣=(灞忓箷Y, 灏忓湴鍥綴)
        鍏煎鏃ф牸寮忥細(灞忓箷X, 灏忓湴鍥綳, 灏忓湴鍥綴)娌℃湁灞忓箷Y鏃惰烦杩嘫鏍″噯
        鎵嬪姩璁板綍鐩存帴瑕嗙洊锛?00%鏉冮噸锛?""
        left_pt = getattr(self, '_calib_left_pt', None)
        right_pt = getattr(self, '_calib_right_pt', None)
        top_pt = getattr(self, '_calib_top_pt', None)
        # scale_x鏍″噯
        if left_pt and right_pt and right_pt[0] > left_pt[0]:
            dx_scr = right_pt[0] - left_pt[0]   # 灞忓箷X璺濈
            dx_map = right_pt[2] - left_pt[2] if len(left_pt) >= 4 else right_pt[1] - left_pt[1]  # 灏忓湴鍥綳璺濈
            if dx_map > 0 and dx_scr > 0:
                scale_x = dx_map / dx_scr
                self._calibrated_scale_x = scale_x  # 鎵嬪姩璁板綍鐩存帴瑕嗙洊锛?00%鏉冮噸锛?
                self._map_screen_scale = scale_x
                # 娓呮櫚鏄剧ず锛氬睆骞曡窛绂汇€佸皬鍦板浘璺濈銆佸€嶇巼
                self._add_log("X鏍″噯: 灞忓箷璺濈=%dpx, 灏忓湴鍥捐窛绂?%dpx, 鍊嶇巼=%.4f" % (dx_scr, dx_map, scale_x))
        # scale_y鏍″噯锛氫笂绔偣 + 宸︾鐐癸紙Y涓嬬鐐癸級
        if top_pt and left_pt and len(left_pt) >= 4:
            dy_scr = left_pt[1] - top_pt[0]   # 灞忓箷Y璺濈锛堜笅绔睆骞昚 - 涓婄灞忓箷Y锛?
            dy_map = left_pt[3] - top_pt[1]   # 灏忓湴鍥綴璺濈锛堜笅绔皬鍦板浘Y - 涓婄灏忓湴鍥綴锛?
            if dy_scr > 10 and dy_map > 1:
                scale_y = dy_map / dy_scr
                self._calibrated_scale_y = scale_y
                # 娓呮櫚鏄剧ず锛氬睆骞曡窛绂汇€佸皬鍦板浘璺濈銆佸€嶇巼
                self._add_log("Y鏍″噯: 灞忓箷璺濈=%dpx, 灏忓湴鍥捐窛绂?%dpx, 鍊嶇巼=%.4f" % (dy_scr, dy_map, scale_y))

    def _get_monster_map_pos_verified(self, screen_x, screen_y):
        """銆愭ā鍧桞銆戞€墿灞忓箷鍧愭爣杞皬鍦板浘鍧愭爣锛堜汉鐗╅敋鐐?鐩稿鍋忕Щ锛孻鐢ㄥ悓骞冲彴缁跨嚎鏍″噯锛?
        鍘熺悊锛?
          X = 浜虹墿灏忓湴鍥綳 + (鎬睆骞昘 - 浜虹墿灞忓箷X) * scale_x
          Y = 浜虹墿灏忓湴鍥綴 + (鎬睆骞昚 - 浜虹墿灞忓箷Y) * scale_y
          缁跨嚎鏍″噯锛氬彧鍦ㄦ€墿Y鍜屼汉鐗℡鐩稿樊<30px锛堝悓骞冲彴鑼冨洿锛夋椂锛屾墠鎵綳鏈€鎺ヨ繎鐨勭豢绾跨偣淇Y
          - 楂樺/浣庡骞冲彴鐨勬€紙Y宸?30px锛変笉寮哄埗鎷夊埌缁跨嚎涓婏紝淇濈暀绾挎€ц浆鎹
        鍙傛暟锛歴creen_x, screen_y = 鎬墿灞忓箷鍧愭爣锛圷OLO妫€娴嬫鐨勪腑蹇冪偣X锛屽簳閮╕锛?
        杩斿洖锛?map_x, map_y) 灏忓湴鍥惧潗鏍囷紱浜虹墿浣嶇疆鏈煡鏃惰繑鍥濶one"""
        # 鏂规硶A锛氫互浜虹墿涓哄弬鑰冪偣绾挎€ц浆鎹?
        pos_a = self._screen_to_map(screen_x, screen_y)
        if pos_a is None:
            return None
        map_x, map_y = pos_a
        # 缁跨嚎Y鏍″噯锛氬彧鏍″噯鍜屼汉鐗℡鐩稿樊<30px鐨勬€紙鍚屽钩鍙帮級锛岄伩鍏嶉珮澶勬€鎷夊埌浣庡眰
        player_map_y = self._player_map_pos[1] if self._player_map_pos else None
        if player_map_y is not None and abs(map_y - player_map_y) < 30:
            best_y = None
            best_dx = 999
            for p in self.platforms:
                pts = self._platform_points(p)
                for (px, py) in pts:
                    dx = abs(px - map_x)
                    dy = abs(py - map_y)
                    # X鏈€鎺ヨ繎涓擸鍋忓樊<15px锛堟€珯鍦ㄨ繖涓钩鍙颁笂锛?
                    if dx < best_dx and dy < 15:
                        best_dx = dx
                        best_y = py
            if best_y is not None:
                map_y = best_y
        return (map_x, map_y)

    def _get_monster_platform(self, screen_x, screen_y):
        """銆愭ā鍧桞銆戝垽瀹氭€湪鍝釜骞冲彴涓婏紙鐢ㄦ墜鍔ㄥ綍鍒跺钩鍙板垽瀹氾級
        鐢ㄩ€旓細鎵炬€椂鍒ゆ柇鎬拰浜虹墿鏄惁鍚屽钩鍙帮紝杩樻槸鍦ㄤ笂闈?涓嬮潰鐨勫钩鍙?
        鍘熺悊锛?
          1. 鎬睆骞曞潗鏍?YOLO) 鈫?浼扮畻灏忓湴鍥惧潗鏍?_screen_to_map)
          2. 鐢ㄦ墜鍔ㄥ綍鍒剁殑骞冲彴鍒ゅ畾锛氳窛绂烩墹15px = 鍦ㄨ骞冲彴涓?
        鍙傛暟锛歴creen_x, screen_y = 鎬湪娓告垙鐢婚潰涓殑灞忓箷鍧愭爣
        杩斿洖锛氬钩鍙板璞ict锛涙壘涓嶅埌杩斿洖None"""
        map_pos = self._screen_to_map(screen_x, screen_y)
        if map_pos is None:
            return None
        mx, my = map_pos
        # 鐢ㄦ墜鍔ㄥ綍鍒剁殑骞冲彴鍒ゅ畾
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
        """銆愭ā鍧桞銆戝垽瀹氭€浉瀵逛簬浜虹墿鏄笂鍧°€佷笅鍧¤繕鏄钩鍦?
        鐢ㄩ€旓細鏂滃潯鎵撴€椂锛屼笂鍧￠渶瑕佽烦鐫€鎵擄紝涓嬪潯鐩存帴璧拌繃鍘绘墦
        鍘熺悊锛?
          1. 鍏堝垽瀹氭€湪鍝釜骞冲彴(_get_monster_platform)
          2. 鎬拰浜虹墿鍚屽钩鍙帮細姣旇緝鎬及绠楃殑灏忓湴鍥綴 鍜?浜虹墿鍦ㄧ豢绾夸笂鐨刌
             - 鎬猋 < 浜虹墿Y 鈫?涓婂潯锛堟€湪鏇撮珮澶勶級
             - 鎬猋 > 浜虹墿Y 鈫?涓嬪潯锛堟€湪鏇翠綆澶勶級
             - 鐩稿樊鈮? 鈫?骞冲湴
          3. 鎬湪涓嶅悓骞冲彴锛氱洿鎺ュ垽瀹氫笂骞冲彴/涓嬪钩鍙?
        鍙傛暟锛歴creen_x, screen_y = 鎬湪娓告垙鐢婚潰涓殑灞忓箷鍧愭爣
        杩斿洖锛?up'=涓婂潯/涓婂钩鍙? 'down'=涓嬪潯/涓嬪钩鍙? 'flat'=骞冲湴, None=鏈煡"""
        if not self._player_map_pos:
            return None
        # 姝ラ1锛氭€湪鍝釜骞冲彴
        monster_pf = self._get_monster_platform(screen_x, screen_y)
        # 姝ラ2锛氫汉鐗╁湪鍝釜骞冲彴
        player_pf = self._get_current_platform()
        if monster_pf is None or player_pf is None:
            return None
        # 姝ラ3锛氬悓骞冲彴 鈫?姣旇緝Y鍒ゆ柇涓婂潯/涓嬪潯
        if monster_pf.get('id') == player_pf.get('id'):
            map_pos = self._screen_to_map(screen_x, screen_y)
            if map_pos is None:
                return None
            monster_y = map_pos[1]  # 鎬及绠楃殑灏忓湴鍥綴
            player_y = self._player_map_pos[1]  # 浜虹墿灏忓湴鍥綴
            y_diff = monster_y - player_y
            if y_diff < -5:
                return 'up'    # 鎬猋鏇村皬 = 鎬湪鏇撮珮澶?= 涓婂潯
            elif y_diff > 5:
                return 'down'  # 鎬猋鏇村ぇ = 鎬湪鏇翠綆澶?= 涓嬪潯
            else:
                return 'flat'  # Y鐩歌繎 = 骞冲湴
        else:
            # 姝ラ4锛氫笉鍚屽钩鍙?鈫?姣旇緝骞冲彴Y鍒ゆ柇涓?涓嬪钩鍙?
            m_pts = self._platform_points(monster_pf)
            p_pts = self._platform_points(player_pf)
            m_avg_y = sum(p[1] for p in m_pts) / len(m_pts)
            p_avg_y = sum(p[1] for p in p_pts) / len(p_pts)
            if m_avg_y < p_avg_y:
                return 'up'    # 鎬墍鍦ㄥ钩鍙癥鏇村皬 = 涓婇潰鐨勫钩鍙?
            else:
                return 'down'  # 鎬墍鍦ㄥ钩鍙癥鏇村ぇ = 涓嬮潰鐨勫钩鍙?

    def _find_nearest_monster_all(self):
        """銆愭ā鍧桞銆戠患鍚堟壘鏈€杩戠殑鎬紙鍖呮嫭鍚屽钩鍙板拰涓婁笅骞冲彴锛岃€冭檻骞冲彴鍒囨崲鎯╃綒锛?
        鐢ㄩ€旓細鍚屽钩鍙版病鎬椂锛屾壘鏈€杩戠殑鎬紝鍖呮嫭闇€瑕佺埇姊瓙/璺充笅鍘荤殑鎬?
        鍘熺悊锛?
          1. 瀵规瘡涓娴嬪埌鐨勬€紝璁＄畻"缁煎悎璺濈" = 灞忓箷璺濈 + 骞冲彴鍒囨崲鎯╃綒
          2. 鍚屽钩鍙版€細鎯╃綒=0锛堢洿鎺ヨ蛋杩囧幓鎵擄級
          3. 涓婂钩鍙版€細鎯╃綒鈮堢埇姊瓙鏃堕棿(绾?绉?2000璺濈鍗曚綅)
          4. 涓嬪钩鍙版€細鎯╃綒鈮堣烦涓嬪幓鏃堕棿(绾?.5绉?500璺濈鍗曚綅)
          5. 杩斿洖缁煎悎璺濈鏈€灏忕殑鎬?
        杩斿洖锛?screen_x, screen_y, 缁煎悎璺濈, 骞冲彴瀵硅薄, 鏂瑰悜)锛涙病鎬繑鍥濶one"""
        if not self._monsters or not self._player_screen_pos:
            return None
        px, py = self._player_screen_pos
        best = None
        best_cost = 99999
        for (x1, y1, x2, y2, score) in self._monsters:
            cx = (x1 + x2) // 2  # 鎬腑蹇僗
            cy = y2               # 鎬剼搴昚
            screen_dist = int(np.sqrt((cx - px) ** 2 + (cy - py) ** 2))
            # 鍒ゅ畾鎬湪鍝釜骞冲彴
            monster_pf = self._get_monster_platform(cx, cy)
            player_pf = self._get_current_platform()
            # 骞冲彴鍒囨崲鎯╃綒
            if monster_pf and player_pf and monster_pf.get('id') != player_pf.get('id'):
                direction = self._get_slope_direction(cx, cy)
                if direction == 'up':
                    penalty = 2000  # 涓婂钩鍙伴渶瑕佺埇姊瓙锛屾儵缃氬ぇ
                elif direction == 'down':
                    penalty = 500   # 涓嬪钩鍙拌烦涓嬪幓锛屾儵缃氬皬
                else:
                    penalty = 1000
            else:
                direction = self._get_slope_direction(cx, cy) or 'flat'
                penalty = 0       # 鍚屽钩鍙版棤鎯╃綒
            cost = screen_dist + penalty
            if cost < best_cost:
                best_cost = cost
                best = (cx, cy, cost, monster_pf, direction)
        return best

    # ========================================================================
    # 銆愭ā鍧桟銆戠豢绾挎尝鍔ㄦ娴嬶細鍙缁跨嚎涓嶆槸鐩寸殑锛屾湁娉㈠姩鐨勫湴鏂瑰氨瑕佽烦鐫€璺?
    # ========================================================================

    def _check_platform_slope_ahead(self, move_dir, look_ahead=50):
        """銆愭ā鍧桟銆戞娴嬩汉鐗╁墠鏂圭豢绾挎槸鍚︽湁娉㈠姩锛堟柇灞?涓婂潯/涓嬪潯锛夛紝鏈夊垯闇€瑕佽烦鐫€璺?
        鐢ㄩ€旓細鍙缁跨嚎涓嶆槸鐩寸殑锛屾湁娉㈠姩鐨勫湴鏂癸紙鏂眰銆佷笂鍧°€佷笅鍧★級锛屽氨瑕佽烦鐫€璺戣繃鍘?
        鍘熺悊锛?
          1. 鑾峰彇浜虹墿褰撳墠骞冲彴鐨勭豢绾挎姌鐐?
          2. 鎵惧埌浜虹墿鍦ㄧ豢绾夸笂鐨勬渶杩戠偣
          3. 鏍规嵁绉诲姩鏂瑰悜锛屽彇鍓嶆柟look_ahead璺濈(灏忓湴鍥緋x)鍐呯殑缁跨嚎鐐?
          4. 璁＄畻杩欎簺鐐圭殑Y鍙樺寲鑼冨洿(maxY - minY)
          5. Y鍙樺寲>闃堝€?10px) = 鏈夋尝鍔紝闇€瑕佽烦
        鍙傛暟锛歮ove_dir='left'/'right'锛宭ook_ahead=鍓嶆柟妫€娴嬭窛绂?灏忓湴鍥緋x锛岄粯璁?0)
        杩斿洖锛歍rue=鍓嶆柟鏈夋尝鍔ㄩ渶瑕佽烦锛孎alse=骞崇洿缁跨嚎涓嶉渶瑕佽烦"""
        current_pf = self._get_current_platform()
        if not current_pf or not self._player_map_pos:
            return False
        pts = self._platform_points(current_pf)
        if len(pts) < 2:
            return False
        ppx, ppy = self._player_map_pos
        # 姝ラ1锛氭壘鍒颁汉鐗╁湪缁跨嚎涓婄殑鏈€杩戠偣绱㈠紩
        best_idx = 0
        best_dist = 999.0
        for i, (x, y) in enumerate(pts):
            d = ((x - ppx) ** 2 + (y - ppy) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best_idx = i
        # 姝ラ2锛氭牴鎹Щ鍔ㄦ柟鍚戯紝鍙栧墠鏂筶ook_ahead璺濈鍐呯殑缁跨嚎鐐?
        ahead_pts = []
        if move_dir == 'right':
            # 鍚戝彸绉诲姩锛氬彇绱㈠紩澧炲ぇ鏂瑰悜鐨勭偣锛圶澧炲ぇ锛?
            for i in range(best_idx, len(pts)):
                if pts[i][0] - ppx <= look_ahead:
                    ahead_pts.append(pts[i])
                else:
                    break
        else:  # left
            # 鍚戝乏绉诲姩锛氬彇绱㈠紩鍑忓皬鏂瑰悜鐨勭偣锛圶鍑忓皬锛?
            for i in range(best_idx, -1, -1):
                if ppx - pts[i][0] <= look_ahead:
                    ahead_pts.append(pts[i])
                else:
                    break
        if len(ahead_pts) < 2:
            return False
        # 姝ラ3锛氳绠楀墠鏂圭豢绾跨偣鐨刌鍙樺寲鑼冨洿
        ys = [p[1] for p in ahead_pts]
        y_range = max(ys) - min(ys)
        # Y鍙樺寲>10px鍒ゅ畾涓烘湁娉㈠姩锛堟柇灞?涓婂潯/涓嬪潯锛夛紝闇€瑕佽烦鐫€璺?
        return y_range > 10

    def extract_platform(self, points):
        """褰曞埗鐨勮矾寰勭偣鎶界█鍚庝繚瀛樹负鎶樼嚎锛堟洸绾匡級锛屼竴鏉″綍鍒?涓€涓钩鍙般€?""
        if len(points) < 2:
            return []
        # 鎸夐棿璺濇娊绋€锛堣嚦灏?灏忓湴鍥緋x涓€涓偣锛夛紝淇濈暀鏇茬嚎褰㈢姸
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
        """GetAsyncKeyState 杞锛屾寜涓嬬灛闂磋Е鍙戜竴娆?""
        for vk in [VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10, VK_F11, VK_F12]:
            pressed = bool(user32.GetAsyncKeyState(vk) & 0x8000)
            if pressed and not self._key_state[vk]:
                _debug_log("[鐑敭] 妫€娴嬪埌鎸夐敭 VK=0x%X" % vk)
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
                print("[鍚姩] 鏈粦瀹氭父鎴忕獥鍙ｏ紝璇峰厛缁戝畾")
                self._add_log("鏈粦瀹氱獥鍙ｏ紝鏃犳硶鍚姩")
            else:
                self._running = True
                print("[鍚姩] 鑴氭湰宸插惎鍔?(F10)")
                self._add_log("鑴氭湰宸插惎鍔?F10")
                _debug_log("[鍚姩] F10 宸茶Е鍙? _running=True, hwnd=%s" % self.hwnd)
        elif vk == VK_F11:
            # 銆愯皟璇?鐑敭灞傘€慒11鎸夐敭琚崟鑾凤紝杈撳嚭褰撳墠鐘舵€?
            self._rlog("銆愯皟璇?鐑敭銆慒11琚寜涓?stage=%d, 钂欐澘hwnd=%s, 钂欐澘鍙=%s" % (
                self._auto_calib_stage, self._overlay_hwnd, 
                bool(self._overlay_hwnd and user32.IsWindowVisible(self._overlay_hwnd))))
            print("[鐑敭] 鍊嶇巼鏍″噯 (F11)")
            self._start_auto_calibration()
        elif vk == VK_F12:
            if self._running or self._random_running:
                self._running = False
                self._release_combat_move()  # 閲婃斁鎴樻枟涓寔缁寜浣忕殑鏂瑰悜閿?
                if self._random_running:
                    self._release_all_keys()
                    self._reset_climb()
                    self._random_running = False
                    self._random_state = "idle"
                if self._monster_overlay_running:
                    self._stop_monster_overlay()
                print("[鍋滄] 鑴氭湰宸插仠姝?(F12)")
                self._add_log("鑴氭湰宸插仠姝?F12")

    def _on_mouse(self, event, x, y, flags, param):
        """榧犳爣鐐瑰嚮鍥炶皟锛氭爣绛鹃〉鍒囨崲 + 璺嚎椤垫寜閽?""
        # 鏉惧紑鎸夐挳锛氭竻闄ゆ寜涓嬬姸鎬?
        if event == cv2.EVENT_LBUTTONUP:
            self._pressed_btn = None
        if event == cv2.EVENT_LBUTTONDOWN:
            _debug_log("[榧犳爣] 鐐瑰嚮 tab=%s pos=(%d,%d)" % (self._current_tab, x, y))
        # 1. 椤堕儴鏍囩椤靛垏鎹?
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
                        print("[鏍囩椤礭 鍒囨崲鍒?", tab)
                    return

        if self._current_tab in ("fight", "potion"):
            if event == cv2.EVENT_LBUTTONDOWN:
                self._handle_input_mouse(x, y)
            return

        if self._current_tab != "route":
            return

        # 璺嚎椤佃緭鍏ユ锛圶/Y鍋忕Щ锛夎仛鐒﹀鐞?
        if event == cv2.EVENT_LBUTTONDOWN:
            self._handle_input_mouse(x, y)

        # 浜虹墿鐗瑰緛涓嬫媺闈㈡澘锛堝悜涓嬪脊鍑猴級
        dd_top = BTN_CHAR[1] + BTN_CHAR[3]
        dd_bottom = dd_top + CHAR_DD_VISIBLE * CHAR_DD_ITEM_H
        dd_main_x2 = CHAR_DD_X + CHAR_DD_W
        dd_scroll_x2 = dd_main_x2 + CHAR_DD_SCROLL_W
        in_dd_main = (dd_top <= y < dd_bottom and CHAR_DD_X <= x < dd_main_x2)
        in_dd_scroll = (dd_top <= y < dd_bottom and dd_main_x2 <= x < dd_scroll_x2)
        in_dd = in_dd_main or in_dd_scroll
        on_char_btn = (BTN_CHAR[1] <= y < BTN_CHAR[1] + BTN_CHAR[3] and BTN_CHAR[0] <= x < BTN_CHAR[0] + BTN_CHAR[2])

        if self._char_dropdown:
            # 鍙抽敭锛氬垹闄ゅ崟涓壒寰?
            if event == cv2.EVENT_RBUTTONDOWN and in_dd_main:
                row = (y - dd_top) // CHAR_DD_ITEM_H
                if row >= 1:  # row0鏄垹闄ゅ叏閮?
                    slot_idx = self._char_scroll + (row - 1)
                    if 0 <= slot_idx < len(self._char_templates):
                        self._delete_char_template(slot_idx)
                return
            # 宸﹂敭
            if event == cv2.EVENT_LBUTTONDOWN:
                if in_dd_main:
                    row = (y - dd_top) // CHAR_DD_ITEM_H
                    if row == 0:
                        # 鍒犻櫎鍏ㄩ儴
                        self._clear_character_features()
                        self._char_scroll = 0
                    else:
                        slot_idx = self._char_scroll + (row - 1)
                        if 0 <= slot_idx < len(self._char_templates):
                            self._char_dropdown = False
                            print("[榧犳爣] 閫変腑浜虹墿鐗瑰緛#%d" % self._char_templates[slot_idx]["id"])
                        elif slot_idx < CHAR_DD_ITEMS:
                            self._char_dropdown = False
                            self._capture_character_feature()
                    return
                elif in_dd_scroll:
                    # 缈婚〉绠ご
                    mid_y = dd_top + (dd_bottom - dd_top) // 2
                    if y < mid_y:
                        self._char_scroll = max(0, self._char_scroll - 1)
                    else:
                        max_scroll = CHAR_DD_ITEMS - CHAR_DD_FEAT_PER_PAGE
                        self._char_scroll = min(max_scroll, self._char_scroll + 1)
                    return
                elif not on_char_btn:
                    # 鐐瑰嚮鑿滃崟澶栨敹璧?
                    self._char_dropdown = False
                    return

        # 鏃ュ織婊氬姩鏉★細鎷栨嫿+婊氳疆
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

        # 榧犳爣婊氳疆锛堝湪鏃ュ織鍖哄煙鍐呮粴鍔?琛岋級
        if event == cv2.EVENT_MOUSEWHEEL:
            if UI_LOG_X <= x < UI_LOG_X + UI_LOG_W and UI_LOG_Y <= y < UI_LOG_Y + UI_LOG_H:
                if flags > 0:  # 鍚戜笂婊?
                    self._log_scroll = _clamp_scroll(self._log_scroll - 3)
                else:  # 鍚戜笅婊?
                    self._log_scroll = _clamp_scroll(self._log_scroll + 3)
                return

        # 鐐瑰嚮婊氬姩鏉★細寮€濮嬫嫋鎷?
        if event == cv2.EVENT_LBUTTONDOWN:
            if sb_x <= x < sb_x + sb_w and sb_y <= y < sb_y + sb_h:
                self._dragging_log_scroll = True
                # 鐩存帴璺冲埌鐐瑰嚮浣嶇疆
                if max_scroll > 0 and sb_h > 0:
                    rel = (y - sb_y) / sb_h
                    self._log_scroll = _clamp_scroll(int(rel * max_scroll))
                return

        # 鎷栨嫿婊氬姩鏉?
        if event == cv2.EVENT_MOUSEMOVE and getattr(self, '_dragging_log_scroll', False):
            if max_scroll > 0 and sb_h > 0:
                rel = max(0.0, min(1.0, (y - sb_y) / sb_h))
                self._log_scroll = _clamp_scroll(int(rel * max_scroll))
            return

        # 鏉惧紑鎷栨嫿
        if event == cv2.EVENT_LBUTTONUP and getattr(self, '_dragging_log_scroll', False):
            self._dragging_log_scroll = False
            return

        # 2. 鎵嬪姩妗嗛€夋ā寮忥紙灏忓湴鍥惧悎鎴愬尯鍩熷唴鎷栨嫿锛?
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
                    if getattr(self, '_was_random_running', False) and self.route_mode == "闅忔満":
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

        # 鍙抽敭锛氬凡缁戠獥鍙ｄ笅鎷夊垪琛ㄩ」瑙ｇ粦锛堝悜涓婂脊鍑猴紝鏈€澶?0椤癸級
        if event == cv2.EVENT_RBUTTONDOWN:
            if self._bound_dropdown and self._bound_windows:
                item_h = 20
                show_count = min(len(self._bound_windows), 10)
                menu_y2 = UI_BOUND_Y  # 鑿滃崟搴曢儴鍦ㄦ寜閽《閮?
                menu_y1 = menu_y2 - show_count * item_h
                if UI_BOUND_X <= x < UI_BOUND_X + UI_BOUND_W and menu_y1 <= y < menu_y2:
                    idx = (y - menu_y1) // item_h
                    if 0 <= idx < show_count:
                        w = self._bound_windows.pop(idx)
                        self._add_log("宸茶В缁? %s" % w["title"][:20])
                        print("[宸茬粦绐楀彛] 瑙ｇ粦:", w["title"])
                        # 濡傛灉瑙ｇ粦鐨勬槸褰撳墠娲诲姩绐楀彛锛岃嚜鍔ㄥ垏鎹㈠埌鍒楄〃涓殑涓嬩竴涓?
                        if self.hwnd == w["hwnd"]:
                            if self._bound_windows:
                                next_w = self._bound_windows[0]
                                self.hwnd = next_w["hwnd"]
                                self._update_window_rect()
                                self._detect_minimap()
                                self._add_log("鍒囨崲鍒? %s" % next_w["title"][:20])
                            else:
                                self.hwnd = None
                                self._auto_refresh = False
                                self._stop_random()
                        if not self._bound_windows:
                            self._bound_dropdown = False
                    return
            # 娉ㄦ剰锛氳繖閲屼笉鑳絩eturn锛屽惁鍒欏叾浠栧尯鍩熺殑鍙抽敭鐐瑰嚮锛堝鍧愭爣娴嬮噺锛変細琚嫤鎴?

        # 宸茬粦绐楀彛涓嬫媺鑿滃崟锛氬乏閿偣鍑诲叾浠栧湴鏂瑰垯鍏抽棴
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

        # 3. 涓嬫媺鑿滃崟浼樺厛锛堝悜涓嬪脊鍑猴紝鍦ㄥ皬鍦板浘妫€娴嬩箣鍓嶏級
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

        # 4. 宸ュ叿鏍忥紙灏忓湴鍥句笂鏂癸紝甯у潗鏍囷級
        def _in(rect, x, y):
            return rect[0] <= x < rect[0]+rect[2] and rect[1] <= y < rect[1]+rect[3]

        # 鎸夐挳鎸変笅鐗规晥锛氬懡涓换鎰忔寜閽椂璁板綍鎸変笅鐘舵€?闂厜
        _EFFECT_BTNS = [BTN_REFRESH, BTN_MANUAL, BTN_PLATFORM, BTN_LADDER, BTN_SAVE, BTN_PLAN,
                        BTN_PLATFORM_CLR, BTN_LADDER_CLR, BTN_MODE, BTN_PLAN_CLR,
                        BTN_RUN, BTN_STOP, BTN_CHAR, BTN_MONSTER]
        for _br in _EFFECT_BTNS:
            if _in(_br, x, y):
                self._pressed_btn = _br
                break

        if _in(BTN_REFRESH, x, y):
            print("[榧犳爣] 鍒锋柊")
            self._auto_refresh = True
            self._detect_minimap()
            self.frame_count = 0
            self.last_player_pos = None
            return
        if _in(BTN_MANUAL, x, y):
            print("[榧犳爣] 鎵嬪姩妗嗛€?)
            self.manual_select_region()
            return
        # BTN_PLAN_TOOLBAR 浠呮樉绀烘柟妗堝悕/鑷姩锛屼笉澶勭悊鐐瑰嚮
        # 銆愭ā鍧桞銆戣嚜鍔ㄦ牎鍑嗘寜閽偣鍑伙紙鍚屽睆涓夌偣鏍″噯锛氬熀鐐?鍙?00+涓?00锛?
        if _in(BTN_CALIB_AUTO, x, y):
            print("[榧犳爣] 鑷姩鏍″噯")
            self._calib_auto_pressed = 3  # 鎸変笅鐗规晥锛氭樉绀?甯ч槾褰?
            self._start_auto_calibration()
            return

        # 5. 灏忓湴鍥惧尯鍩熷唴鐐瑰嚮
        if UI_MAP_X <= x < UI_MAP_X + UI_MAP_W and UI_MAP_Y <= y < UI_MAP_Y + UI_MAP_H:
            # UI鍧愭爣杞皬鍦板浘鍘熷鍒嗚鲸鐜囧潗鏍?
            map_w = getattr(self, '_last_map_w', FIXED_W)
            map_h = getattr(self, '_last_map_h', MAP_H)
            map_x = int((x - UI_MAP_X) / UI_MAP_W * map_w)
            map_y = int((y - UI_MAP_Y) / UI_MAP_H * map_h)
            # 銆愭ā鍧桞銆戝彴瀛愰€夋嫨鎸夐挳鐐瑰嚮锛堝皬鍦板浘宸︿笂鏂癸級
            if self._btn_platform_selector and _in(self._btn_platform_selector, x, y):
                self._show_platform_selector = not self._show_platform_selector
                print("[鍙板瓙閫夋嫨] 鎵撳紑闈㈡澘" if self._show_platform_selector else "[鍙板瓙閫夋嫨] 鍏抽棴闈㈡澘")
                return
            # 銆愭ā鍧桞銆戝彴瀛愰€夋嫨闈㈡澘涓殑鐐瑰嚮
            if self._show_platform_selector and self.platforms:
                panel_x, panel_y = UI_MAP_X + 10, UI_MAP_Y + 30
                panel_w = UI_MAP_W - 20
                # 鍏抽棴鎸夐挳X
                if self._btn_platform_selector_close and _in(self._btn_platform_selector_close, x, y):
                    self._show_platform_selector = False
                    print("[鍙板瓙閫夋嫨] 鍏抽棴闈㈡澘")
                    return
                # 骞冲彴缂栧彿鐐瑰嚮锛堝垏鎹㈤€変腑鐘舵€侊細鐐逛竴涓嬮€夋嫨锛屽啀鐐逛竴涓嬪彇娑堬級
                per_row = 5
                for idx, pf in enumerate(self.platforms):
                    pf_num = idx + 1
                    row = idx // per_row
                    col = idx % per_row
                    item_x = panel_x + 10 + col * 36
                    item_y = panel_y + 28 + row * 22
                    # 鐐瑰嚮鍖哄煙锛氬渾褰㈠懆鍥达紙姣斿渾褰㈢◢澶т竴鐐规柟渚跨偣鍑伙級
                    if item_x <= x < item_x + 18 and item_y <= y < item_y + 18:
                        if pf_num in self._selected_platforms:
                            self._selected_platforms.remove(pf_num)
                            print("[鍙板瓙閫夋嫨] 鍙栨秷閫夋嫨骞冲彴%d" % pf_num)
                        else:
                            self._selected_platforms.append(pf_num)
                            print("[鍙板瓙閫夋嫨] 閫夋嫨骞冲彴%d" % pf_num)
                        return
            return
        if _in(BTN_PLATFORM, x, y):
            print("[榧犳爣] 骞冲彴"); self._handle_hotkey(VK_F5); return
        if _in(BTN_LADDER, x, y):
            print("[榧犳爣] 姊瓙"); self._handle_hotkey(VK_F6); return
        if _in(BTN_SAVE, x, y):
            self._dropdown = "save" if self._dropdown != "save" else None; return
        if _in(BTN_PLAN, x, y):
            self._dropdown = "route" if self._dropdown != "route" else None; return

        # 6. 绗簩鎺掓寜閽紙娓呴櫎骞冲彴/娓呴櫎姊瓙/妯″紡鈻?娓呴櫎鏂规鈻硷級
        if _in(BTN_PLATFORM_CLR, x, y):
            self._pop_platform(); return
        if _in(BTN_LADDER_CLR, x, y):
            self._pop_ladder(); return
        if _in(BTN_MODE, x, y):
            self._dropdown = "mode" if self._dropdown != "mode" else None; return
        if _in(BTN_PLAN_CLR, x, y):
            self._dropdown = "clear_route" if self._dropdown != "clear_route" else None; return

        # 7. 杩愯/鍋滄
        if _in(BTN_RUN, x, y):
            print("[榧犳爣] 杩愯")
            if self.route_mode == "闅忔満":
                self._start_random()
            elif self.hwnd is not None:
                # 鎵嬪姩妯″紡锛氭湁褰曞埗璺嚎灏卞惎鍔ㄨ矾绾胯窡闅忥紙鐢ㄥ綋鍓嶆柟妗堬級锛屾病璺嚎鍙惎鍔ㄦ垬鏂?
                if self._route_has_file(self.current_route):
                    self._start_random()
                    self._add_log("璺嚎%d宸插惎鍔紙鎵嬪姩锛? % self.current_route)
                else:
                    self._running = True
                    self._add_log("鎴樻枟宸插惎鍔紙鏃犺矾绾匡級")
                    _debug_log("[杩愯] 鎵嬪姩妯″紡鏃犺矾绾匡紝浠呭惎鍔ㄦ垬鏂?)
            else:
                self._add_log("鏈粦瀹氱獥鍙ｏ紝鏃犳硶鍚姩")
                _debug_log("[杩愯] 鏈粦瀹氱獥鍙?)
            return
        if _in(BTN_STOP, x, y):
            print("[榧犳爣] 鍋滄")
            if self._random_running:
                self._stop_random()
            elif self._running:
                # 鎵嬪姩妯″紡锛氬彧鍋滄垬鏂?钂欐澘
                self._running = False
                self._release_combat_move()  # 閲婃斁鎸佺画鎸変綇鐨勬柟鍚戦敭
                if self._monster_overlay_running:
                    self._stop_monster_overlay()
                self._add_log("鎴樻枟宸插仠姝?)
                _debug_log("[鍋滄] 鎵嬪姩妯″紡宸插仠姝?)
            return

        # 8. 瀛愭爣绛鹃〉锛堜汉鐗╃壒寰佷笅鎷?鎬墿鏁版嵁锛屽亸绉绘宸茬敱杈撳叆妗嗗鐞嗭級
        if _in(BTN_CHAR, x, y):
            self._char_dropdown = not self._char_dropdown
            self._bound_dropdown = False
            self._char_scroll = 0
            print("[榧犳爣] 浜虹墿鐗瑰緛涓嬫媺:", "灞曞紑" if self._char_dropdown else "鏀惰捣")
            return
        if _in(BTN_MONSTER, x, y):
            _debug_log("[榧犳爣] 鐐瑰嚮鎬墿鏁版嵁鎸夐挳")
            print("[榧犳爣] 鎬墿鏁版嵁 - 閫夋嫨YOLO妯″瀷"); self._select_yolo_model(); return

        # 9. 鍙嫋鎷藉噯鏄燂紙鎸変綇鎷栧埌娓告垙绐楀彛閲婃斁鍗崇粦瀹氬墠鍙扮獥鍙ｏ級
        chx, chy = self._crosshair_pos
        half = self._crosshair_size // 2
        if chx - half <= x < chx + half and chy - half <= y < chy + half:
            print("[榧犳爣] 鍑嗘槦鎷栨嫿寮€濮?- 鎷栧埌娓告垙绐楀彛閲婃斁")
            self._drag_crosshair = True
            self._add_log("鎷栧埌娓告垙绐楀彛閲婃斁")
            return

        # 10. 宸茬粦绐楀彛涓嬫媺鎸夐挳
        if UI_BOUND_X <= x < UI_BOUND_X + UI_BOUND_W and UI_BOUND_Y <= y < UI_BOUND_Y + UI_BOUND_H:
            self._bound_dropdown = not self._bound_dropdown
            print("[榧犳爣] 宸茬粦绐楀彛涓嬫媺:", "灞曞紑" if self._bound_dropdown else "鏀惰捣")
            return


    def draw(self, map_area, player_pos):
        frame = self._ui_bg.copy()

        if self._current_tab in ("fight", "potion"):
            self._draw_input_fields(frame)
            return frame

        if self._current_tab != "route":
            return frame

        # === 娓叉煋灏忓湴鍥惧唴瀹?===
        display = map_area.copy()
        h, w = display.shape[:2]
        # 瀛樺偍褰撳墠灏忓湴鍥惧師濮嬪昂瀵革紝渚涢紶鏍囨嫋鍔ㄦ椂鍧愭爣杞崲鐢?
        self._last_map_w = w
        self._last_map_h = h
        # 銆愭ā鍧桞銆戝湪灏忓湴鍥句笂鐢昏嚜鍔ㄦ牎鍑嗙偣锛堝熀鐐圭孩銆佺豢鐐广€佽摑鐐归兘鐢伙紝鏂逛究纭浣嶇疆锛?
        auto_base = getattr(self, '_auto_calib_base', None)
        auto_stage = getattr(self, '_auto_calib_stage', 0)
        auto_green = getattr(self, '_auto_calib_green_map', None)
        auto_blue = getattr(self, '_auto_calib_blue_map', None)
        # 鍦嗙偣鍗婂緞锛氭寜浜虹墿鍏夌偣澶у皬锛堝師濮嬪皬鍦板浘鍧愭爣涓嬪崐寰?锛岀缉鏀惧悗绾?px锛屽拰娓告垙鑷甫榛勭偣宸笉澶氾級
        CALIB_DOT_R = 3
        # 绾㈢偣锛堝熀鐐癸級锛歴tage>=1鏃舵樉绀猴紝鍜屼汉鐗╅粍鑹插厜鐐归噸鍚?
        if auto_base and len(auto_base) >= 4 and auto_stage >= 1:
            bx, by = int(auto_base[2]), int(auto_base[3])  # 鍩虹偣灏忓湴鍥惧潗鏍?
            if 0 <= bx < w and 0 <= by < h:
                cv2.circle(display, (bx, by), CALIB_DOT_R, (0, 0, 255), -1)  # 绾㈣壊瀹炲績鍦?
        # 缁跨偣锛歴tage=3锛堝凡璁板綍缁跨偣锛夊拰stage=4锛堝凡璁板綍钃濈偣锛夋椂鏄剧ず
        if auto_green and auto_stage in (3, 4):
            gx, gy = int(auto_green[0]), int(auto_green[1])
            if 0 <= gx < w and 0 <= gy < h:
                cv2.circle(display, (gx, gy), CALIB_DOT_R, (0, 255, 0), -1)  # 缁胯壊瀹炲績鍦?
        # 钃濈偣锛歴tage=4锛堝凡璁板綍钃濈偣锛夋椂鏄剧ず
        if auto_blue and auto_stage == 4:
            blx, bly = int(auto_blue[0]), int(auto_blue[1])
            if 0 <= blx < w and 0 <= bly < h:
                cv2.circle(display, (blx, bly), CALIB_DOT_R, (255, 0, 0), -1)  # 钃濊壊瀹炲績鍦?
        # 褰曞埗涓殑骞冲彴/姊瓙锛堥粍鑹诧級
        if self.recording_platform and len(self.platform_points) > 1:
            cv2.polylines(display, [np.array(self.platform_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        if self.recording_ladder and len(self.ladder_points) > 1:
            cv2.polylines(display, [np.array(self.ladder_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        map_display = cv2.resize(display, (FIXED_W, MAP_H), interpolation=cv2.INTER_NEAREST)

        # 銆愭ā鍧桞銆戝湪缂╂斁鍚庣殑map_display涓婄敾鎬墿绱壊鐐癸紙鍗婂緞6锛屾竻鏅板彲瑙侊級
        scale_x = FIXED_W / w if w > 0 else 1.0
        scale_y = MAP_H / h if h > 0 else 1.0
        if self._monsters and self._player_map_pos and self._player_screen_pos:
            COLOR_MONSTER_MAP = (255, 0, 255)  # 绱壊BGR
            for (x1, y1, x2, y2, score) in self._monsters:
                mcx = (x1 + x2) // 2
                mcy = y2
                mpos = self._get_monster_map_pos_verified(mcx, mcy)
                if mpos:
                    dx_s = int(mpos[0] * scale_x)
                    dy_s = int(mpos[1] * scale_y)
                    if 0 <= dx_s < FIXED_W and 0 <= dy_s < MAP_H:
                        cv2.circle(map_display, (dx_s, dy_s), 6, COLOR_MONSTER_MAP, -1)

        # 骞冲彴缂栧彿锛堢缉鏀惧悗鐢伙紝绾㈣壊鐧芥弿杈癸級
        for p in self.platforms:
            pts = self._platform_points(p)
            if len(pts) >= 2:
                pf_id = p.get('id', 0) + 1
                xs = [pt[0] for pt in pts]
                ys = [pt[1] for pt in pts]
                cx = int(sum(xs) / len(xs) * scale_x)
                cy_top = int(min(ys) * scale_y) - 8
                if 0 <= cx < FIXED_W and 0 <= cy_top < MAP_H:
                    cv2.putText(map_display, str(pf_id), (cx, cy_top),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 3, cv2.LINE_AA)
                    cv2.putText(map_display, str(pf_id), (cx, cy_top),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1, cv2.LINE_AA)

        # 姊瓙钃濈嚎锛堝湪缂栧彿涓婃柟锛岀缉鏀惧悗鐢伙紝绾垮2锛?
        for l in self.ladders:
            lx = int(l["x"] * scale_x)
            ly1 = int(l["y_top"] * scale_y)
            ly2 = int(l["y_bottom"] * scale_y)
            lx = max(0, min(lx, FIXED_W - 1))
            ly1 = max(0, min(ly1, MAP_H - 1))
            ly2 = max(0, min(ly2, MAP_H - 1))
            cv2.line(map_display, (lx, ly1), (lx, ly2), COLOR_LADDER, 2)

        # 骞冲彴缁跨嚎锛堟渶鍚庣敾锛屽缁堝湪鏈€涓婂眰锛岀缉鏀惧悗鐢伙紝绾垮1锛?
        for p in self.platforms:
            pts = self._platform_points(p)
            if len(pts) >= 2:
                scaled_pts = [(int(pt[0] * scale_x), int(pt[1] * scale_y)) for pt in pts]
                cv2.polylines(map_display, [np.array(scaled_pts, np.int32).reshape(-1, 1, 2)],
                              False, COLOR_PLATFORM, 2)

        # 浜虹墿鍏夌偣锛氬彧淇濈暀娓告垙鑷甫鐨勫師濮嬪厜鐐癸紝涓嶈嚜宸辩敾锛坒ind_player_dot璐熻矗妫€娴嬪厜鐐逛綅缃級

        # 闅忔満妯″紡杩愯鐘舵€侊紙宸茶鍊嶇巼鏄剧ず鏇夸唬锛?
        # if self._random_running:
        #     state_text = {"idle": "閫夋柟妗堜腑", "moving": "绉诲姩涓?, "attacking": "鏀诲嚮涓?, "returning": "杩斿洖璧风偣"}.get(self._random_state, self._random_state)
        #     progress = "%d/%d" % (min(self._random_platform_idx + 1, len(self.platforms)), len(self.platforms)) if self.platforms else "0/0"
        #     status = "闅忔満: %s 骞冲彴%s" % (state_text, progress)
        #     cv2.rectangle(map_display, (0, MAP_H - 20), (FIXED_W, MAP_H), (25, 25, 25), -1)
        #     cv2.putText(map_display, status, (6, MAP_H - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1)

        # 銆愭ā鍧桞銆戣嚜鍔ㄦ牎鍑嗗€嶇巼鏄剧ず锛堥粦鑹插瓧锛屽皬鍦板浘宸︿笅瑙掞紝鏃犺儗鏅潯绾癸級
        calib_sx = getattr(self, '_calibrated_scale_x', 0)
        calib_sy = getattr(self, '_calibrated_scale_y', 0)
        if calib_sx > 0 and calib_sy > 0:
            scale_text = "X:%.4f Y:%.4f" % (calib_sx, calib_sy)
            # 绾㈣壊瀛楋紝鏀惧湪灏忓湴鍥惧乏涓嬭锛屾棤鑳屾櫙鏉＄汗锛屽瓧浣?.5锛岀嚎瀹?涓嶅姞绮?
            cv2.putText(map_display, scale_text, (4, MAP_H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        # 鎵嬪姩妗嗛€夋嫋鎷界煩褰?
        if self._selecting and self._select_rect and self._select_dragging:
            x1, y1, x2, y2 = self._select_rect
            cv2.rectangle(map_display, (x1, y1), (x2, y2), (0, 255, 255), 1)

        # === 宸ュ叿鏍忥紙灏忓湴鍥句笂鏂癸級===
        draw_asset(frame, self._ui_refresh, *BTN_REFRESH)
        draw_asset(frame, self._ui_manual, *BTN_MANUAL)
        draw_asset(frame, self._ui_plan_toolbar, *BTN_PLAN_TOOLBAR)
        # 銆愭ā鍧桞銆戣嚜鍔ㄦ牎鍑嗘寜閽紙鍚屽睆涓夌偣鏍″噯锛?
        draw_asset(frame, self._ui_calib_auto, *BTN_CALIB_AUTO)
        # 銆愭ā鍧桞銆戞寜閽寜涓嬮槾褰辩壒鏁堬紙鍜屽墠闈㈡寜閽竴鏍风殑鏁堟灉锛?
        if getattr(self, '_calib_auto_pressed', 0) > 0:
            cv2.rectangle(frame, (BTN_CALIB_AUTO[0], BTN_CALIB_AUTO[1]),
                          (BTN_CALIB_AUTO[0]+BTN_CALIB_AUTO[2], BTN_CALIB_AUTO[1]+BTN_CALIB_AUTO[3]),
                          (0, 0, 0), -1)
            self._calib_auto_pressed -= 1
        # 绗笁涓鏄剧ず褰撳墠鏂规鍚嶆垨"闅忔満"
        plan_label = "闅忔満" if self.route_mode == "闅忔満" else "鏂规%d" % self.current_route
        (plw, plh), _ = cv2.getTextSize(plan_label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        plx = BTN_PLAN_TOOLBAR[0] + (BTN_PLAN_TOOLBAR[2] - plw) // 2
        ply = BTN_PLAN_TOOLBAR[1] + (BTN_PLAN_TOOLBAR[3] + plh) // 2 - 2
        cv2.putText(frame, plan_label, (plx, ply), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)

        # === 缂╂斁鍒癠I灏哄骞跺悎鎴愬埌鑳屾櫙 ===
        map_scaled = cv2.resize(map_display, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)  # 缂╂斁鍒癠I鏄剧ず灏哄
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H, UI_MAP_X:UI_MAP_X+UI_MAP_W] = map_scaled  # 鍚堟垚鍒拌儗鏅?

        # === 銆愭ā鍧桞銆戝彴瀛愰€夋嫨鎸夐挳锛堝皬鍦板浘宸︿笂鏂癸級===
        # 鐐瑰嚮寮瑰嚭閫夋嫨闈㈡澘锛屽彲澶氶€夊钩鍙帮紝閫夊畬鍏抽棴
        btn_sel_x, btn_sel_y, btn_sel_w, btn_sel_h = UI_MAP_X + 5, UI_MAP_Y + 5, 60, 20
        self._btn_platform_selector = (btn_sel_x, btn_sel_y, btn_sel_w, btn_sel_h)
        cv2.rectangle(frame, (btn_sel_x, btn_sel_y), (btn_sel_x+btn_sel_w, btn_sel_y+btn_sel_h), (60, 60, 60), -1)
        cv2.rectangle(frame, (btn_sel_x, btn_sel_y), (btn_sel_x+btn_sel_w, btn_sel_y+btn_sel_h), (150, 150, 150), 1)
        cv2.putText(frame, "鍙板瓙閫夋嫨", (btn_sel_x+5, btn_sel_y+14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
        # 鏄剧ず褰撳墠閫変腑鐨勫钩鍙版暟閲?
        if self._selected_platforms:
            sel_text = "宸查€?%d" % len(self._selected_platforms)
            cv2.putText(frame, sel_text, (btn_sel_x+btn_sel_w+5, btn_sel_y+14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1, cv2.LINE_AA)
        else:
            cv2.putText(frame, "鍏ㄩ儴", (btn_sel_x+btn_sel_w+5, btn_sel_y+14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (200, 200, 200), 1, cv2.LINE_AA)

        # === 銆愭ā鍧桞銆戝彴瀛愰€夋嫨闈㈡澘锛堢偣鍑?鍙板瓙閫夋嫨"鍚庡脊鍑猴級===
        if self._show_platform_selector and self.platforms:
            # 闈㈡澘浣嶇疆锛氬皬鍦板浘鍐呴儴锛岃鐩栧湪灏忓湴鍥句笂
            panel_x, panel_y = UI_MAP_X + 10, UI_MAP_Y + 30
            panel_w, panel_h = UI_MAP_W - 20, min(150, 30 + len(self.platforms) * 22)
            # 闈㈡澘鑳屾櫙
            cv2.rectangle(frame, (panel_x, panel_y), (panel_x+panel_w, panel_y+panel_h), (40, 40, 40), -1)
            cv2.rectangle(frame, (panel_x, panel_y), (panel_x+panel_w, panel_y+panel_h), (180, 180, 180), 1)
            # 鏍囬
            cv2.putText(frame, "閫夋嫨鎵撴€钩鍙帮紙鍙閫夛級", (panel_x+8, panel_y+16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
            # 鍏抽棴鎸夐挳X
            close_x, close_y = panel_x + panel_w - 20, panel_y + 4
            self._btn_platform_selector_close = (close_x, close_y, 16, 16)
            cv2.rectangle(frame, (close_x, close_y), (close_x+16, close_y+16), (80, 80, 80), -1)
            cv2.putText(frame, "X", (close_x+4, close_y+13),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
            # 骞冲彴缂栧彿鍒楄〃锛堟瘡琛?涓紝鍦嗗舰鏍峰紡锛氶€変腑=榛勫簳榛戝瓧锛屾湭閫変腑=鐧藉簳榛戝瓧锛?
            per_row = 5
            for idx, pf in enumerate(self.platforms):
                pf_num = idx + 1  # 缂栧彿浠?寮€濮?
                row = idx // per_row
                col = idx % per_row
                item_x = panel_x + 10 + col * 36
                item_y = panel_y + 28 + row * 22
                # 鍦嗗舰涓績鍜屽崐寰?
                circle_cx = item_x + 8
                circle_cy = item_y + 8
                circle_r = 8
                # 閫変腑=榛勫簳榛戝瓧锛屾湭閫変腑=鐧藉簳榛戝瓧
                checked = pf_num in self._selected_platforms
                bg_color = (0, 255, 255) if checked else (255, 255, 255)  # 榛勮壊/鐧借壊BGR
                text_color = (0, 0, 0)  # 榛戣壊
                cv2.circle(frame, (circle_cx, circle_cy), circle_r, bg_color, -1)
                cv2.circle(frame, (circle_cx, circle_cy), circle_r, (100, 100, 100), 1)
                # 缂栧彿鏂囧瓧锛堝眳涓級
                num_text = str(pf_num)
                (tw, th), _ = cv2.getTextSize(num_text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
                cv2.putText(frame, num_text, (circle_cx - tw//2, circle_cy + th//2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, text_color, 1, cv2.LINE_AA)
                # 璁板綍姣忎釜缂栧彿鐨勭偣鍑诲尯鍩燂紙鐢ㄤ簬榧犳爣鐐瑰嚮妫€娴嬶級
                # 瀛樺偍鍦ㄤ复鏃跺彉閲忎腑锛宱n_mouse鏃剁敤
        else:
            self._btn_platform_selector_close = None

        # === 鐑敭璺戦┈鐏睍绀哄尯鍩燂紙灏忓湴鍥句笅鏂广€佸钩鍙版寜閽笂鏂癸紝浠庡彸鍒板乏娴佸姩锛岀豢鑹查粦浣撳ぇ瀛楋級===
        _hk_x = UI_MAP_X          # 绾㈡宸=29
        _hk_y = 412                # 绾㈡椤禮
        _hk_w = UI_MAP_W           # 绾㈡瀹?403
        _hk_h = 36                 # 绾㈡楂?36
        _hk_text = self._hotkey_text  # 澶嶇敤棰勫畾涔夋枃瀛楋紝閬垮厤姣忓抚閲嶅瀹氫箟
        # 婊氬姩鍋忕Щ姣忓抚閫掑噺4鍍忕礌锛堜粠鍙冲埌宸︽祦鍔紝閫熷害閫備腑涓嶅崱椤匡級锛屾枃瀛楀畬鍏ㄧЩ鍑哄乏杈圭晫鍚庨噸缃埌鍙宠竟缂?
        self._hotkey_scroll_x -= 4
        try:
            _roi = frame[_hk_y:_hk_y+_hk_h, _hk_x:_hk_x+_hk_w].copy()
            _pil = Image.fromarray(cv2.cvtColor(_roi, cv2.COLOR_BGR2RGB))
            _draw = ImageDraw.Draw(_pil)
            _font = self._hotkey_font  # 澶嶇敤棰勫姞杞藉瓧浣擄紝閬垮厤姣忓抚鍔犺浇鍗￠】
            _tw = self._hotkey_text_w  # 澶嶇敤棰勮绠楁枃瀛楀搴︼紝閬垮厤姣忓抚textbbox璁＄畻鍗￠】
            _th = self._hotkey_text_h  # 澶嶇敤棰勮绠楁枃瀛楅珮搴?
            _ty = (_hk_h - _th) // 2  # 鍨傜洿灞呬腑
            # 鏂囧瓧绉诲嚭宸﹁竟鐣屽悗閲嶇疆
            if self._hotkey_scroll_x < -_tw:
                self._hotkey_scroll_x = _hk_w
            _dx = self._hotkey_scroll_x
            _draw.text((_dx, _ty), _hk_text, font=_font, fill=(0, 128, 0))  # 娣辩豢鑹?
            # 鏃犵紳寰幆锛氭枃瀛楀熬閮ㄨ繘鍏ョ孩妗嗗悗锛屽湪鍙宠竟琛ヤ竴浠?
            if _dx + _tw < _hk_w:
                _draw.text((_dx + _tw + 60, _ty), _hk_text, font=_font, fill=(0, 128, 0))
            _roi_out = cv2.cvtColor(np.array(_pil), cv2.COLOR_RGB2BGR)
            frame[_hk_y:_hk_y+_hk_h, _hk_x:_hk_x+_hk_w] = _roi_out
        except Exception:
            pass

        # === 璺嚎椤垫寜閽礌鏉愶紙鍙傝€冨浘绮剧‘鍧愭爣锛屾敮鎸侀€忔槑锛?==
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
        # 鍦ㄦ€墿鏁版嵁鎸夐挳鍙充晶鐧借壊鍖哄煙鏄剧ず鏂囦欢澶瑰悕+BEST.ONNX锛堣嚜鍔ㄦ崲琛岋紝鏈€澶?琛岋級
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
            # 鍏堣瘯鍗曡
            (mw, mh), _ = cv2.getTextSize(_full, cv2.FONT_HERSHEY_SIMPLEX, _base_scale, _thickness)
            if mw <= _right_w:
                _lines = [_full]
                _scale = _base_scale
            else:
                # 瓒呭嚭鍒欏湪 \ 澶勬崲琛岋紝鏈€澶?琛?
                if _folder and "\\" in _full:
                    _line1 = _folder + "\\"
                    _line2 = _fname
                else:
                    _line1 = _full
                    _line2 = ""
                # 娴嬬浜岃瀹藉害锛岃秴浜嗗氨缂?
                (mw2, _), _ = cv2.getTextSize(_line2, cv2.FONT_HERSHEY_SIMPLEX, _base_scale, _thickness)
                _scale = _base_scale
                if mw2 > _right_w:
                    _scale = max(0.38, _base_scale * _right_w / mw2)
                (mw1, mh), _ = cv2.getTextSize(_line1, cv2.FONT_HERSHEY_SIMPLEX, _scale, _thickness)
                if mw1 > _right_w:
                    # 绗竴琛屼篃瓒咃紝鎴柇
                    while _line1 and cv2.getTextSize(_line1, cv2.FONT_HERSHEY_SIMPLEX, _scale, _thickness)[0][0] > _right_w:
                        _line1 = _line1[:-2]
                    _line1 = _line1[:-1] + ".." if len(_line1) > 2 else _line1
                _lines = [_line1]
                if _line2:
                    _lines.append(_line2)
            # 缁樺埗锛堝瀭鐩村眳涓紝2琛屾椂鍚戜笂鍋忕Щ缁欑浜岃鑵剧┖闂达級
            _line_h = mh + 4
            _total_h = len(_lines) * _line_h - 4
            _start_y = BTN_MONSTER[1] + (BTN_MONSTER[3] - _total_h) // 2 + mh
            for _i, _line in enumerate(_lines):
                cv2.putText(frame, _line,
                            (_right_x + 4, _start_y + _i * _line_h),
                            cv2.FONT_HERSHEY_SIMPLEX, _scale, (40, 40, 40), _thickness, cv2.LINE_AA)
        draw_asset(frame, self._ui_winbind_bg, *BTN_WINBIND)
        # 宸茬粦瀹氱獥鍙ｄ笅鎷夋
        draw_asset(frame, self._ui_bound_dropdown, UI_BOUND_X, UI_BOUND_Y, UI_BOUND_W, UI_BOUND_H)

        # === 褰曞埗鐘舵€佺孩鑹查棯鐑佹寚绀哄櫒锛堝湪瀵瑰簲鎸夐挳宸︿笂瑙掞級===
        import time as _t
        if int(_t.time() * 3) % 2 == 0:
            if self.recording_platform:
                cv2.circle(frame, (BTN_PLATFORM[0] + 8, BTN_PLATFORM[1] + 8), 5, (0, 0, 255), -1)
                cv2.circle(frame, (BTN_PLATFORM[0] + 8, BTN_PLATFORM[1] + 8), 5, (0, 0, 180), 1)
            if self.recording_ladder:
                cv2.circle(frame, (BTN_LADDER[0] + 8, BTN_LADDER[1] + 8), 5, (0, 0, 255), -1)
                cv2.circle(frame, (BTN_LADDER[0] + 8, BTN_LADDER[1] + 8), 5, (0, 0, 180), 1)

        # === 涓嬫媺鑿滃崟 ===
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

        # === 杩愯鏃ュ織鍖哄煙锛堟棩蹇楀簳鏉?鍚戜笂娴佸姩+鍙充晶婊氬姩鏉★級===
        lx, ly, lw, lh = UI_LOG_X, UI_LOG_Y, UI_LOG_W, UI_LOG_H
        draw_asset(frame, self._ui_log_bg, lx, ly, lw, lh)
        # 鏃ュ織鍐呭锛堟柊淇℃伅鍦ㄥ簳閮紝鍚戜笂娴佸姩锛?
        log_content_y = UI_LOG_CONTENT_Y
        log_content_h = UI_LOG_H - (UI_LOG_CONTENT_Y - UI_LOG_Y) - 4
        line_h = 16
        max_lines = max(1, log_content_h // line_h)
        total = len(self._runtime_logs)
        # _log_scroll=0 鏄剧ず鏈€鏂帮紱>0 鍚戜笂婊氬姩鐪嬪巻鍙?
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
        # 鍙充晶婊氬姩鏉?
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

        # === 宸茬粦绐楀彛涓嬫媺鍒楄〃锛堝悜涓婂脊鍑猴紝鏈€澶?0椤癸級===
        if self._bound_dropdown and self._bound_windows:
            item_h = 20
            show_count = min(len(self._bound_windows), 10)
            menu_y2 = UI_BOUND_Y  # 鑿滃崟搴曢儴鍦ㄦ寜閽《閮?
            menu_y1 = menu_y2 - show_count * item_h
            # 鑳屾櫙
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
            # 鎻愮ず鍙抽敭瑙ｇ粦
            cv2.putText(frame, "RMB unbind", (UI_BOUND_X, menu_y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)
            if len(self._bound_windows) > 10:
                cv2.putText(frame, "...+%d more" % (len(self._bound_windows) - 10), (UI_BOUND_X, menu_y1 - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (180, 180, 180), 1)

        # === 鍙嫋鎷藉噯鏄燂紙绐楀彛缁戝畾锛岀敤绱犳潗锛屾敮鎸侀€忔槑锛?==
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

        # === 鍑嗘槦鎷栨嫿妯″紡鎻愮ず ===
        if self._drag_crosshair:
            cv2.putText(frame, "DRAG TO GAME WINDOW", (UI_W // 2 - 100, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # === 浜虹墿鐗瑰緛涓嬫媺闈㈡澘锛堝悜涓嬪脊鍑猴紝5琛岋細鍒犻櫎鍏ㄩ儴+4鐗瑰緛锛?==
        if self._char_dropdown:
            dd_top = BTN_CHAR[1] + BTN_CHAR[3]
            dd_bottom = dd_top + CHAR_DD_VISIBLE * CHAR_DD_ITEM_H
            dd_main_x2 = CHAR_DD_X + CHAR_DD_W
            dd_scroll_x2 = dd_main_x2 + CHAR_DD_SCROLL_W
            # 涓讳綋鑳屾櫙
            cv2.rectangle(frame, (CHAR_DD_X, dd_top), (dd_main_x2 - 1, dd_bottom - 1), (48, 48, 48), -1)
            cv2.rectangle(frame, (CHAR_DD_X, dd_top), (dd_main_x2 - 1, dd_bottom - 1), (100, 100, 100), 1)
            # 缈婚〉鏉¤儗鏅?
            cv2.rectangle(frame, (dd_main_x2, dd_top), (dd_scroll_x2 - 1, dd_bottom - 1), (58, 58, 58), -1)
            cv2.rectangle(frame, (dd_main_x2, dd_top), (dd_scroll_x2 - 1, dd_bottom - 1), (100, 100, 100), 1)
            # 缈婚〉绠ご
            mid_y = dd_top + (dd_bottom - dd_top) // 2
            cv2.putText(frame, "^", (dd_main_x2 + 5, mid_y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            cv2.putText(frame, "v", (dd_main_x2 + 5, dd_bottom - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            # 琛?锛氬垹闄ゅ叏閮?
            cv2.line(frame, (CHAR_DD_X + 2, dd_top + CHAR_DD_ITEM_H), (dd_main_x2 - 3, dd_top + CHAR_DD_ITEM_H), (80, 80, 80), 1)
            cv2.putText(frame, "[Delete All]", (CHAR_DD_X + 18, dd_top + 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, (0, 80, 255), 1)
            # 琛?-4锛氱壒寰佹Ы浣?
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
            # 婊氬姩浣嶇疆鎻愮ず
            cv2.putText(frame, "%d/%d" % (self._char_scroll + 1, CHAR_DD_ITEMS - CHAR_DD_FEAT_PER_PAGE + 1),
                        (dd_main_x2 + 1, dd_top + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.22, (160, 160, 160), 1)

        # === 璺嚎椤佃緭鍏ユ锛圶/Y鍋忕Щ锛屾爣绛句笅鏂癸級===
        self._draw_input_fields(frame)

        # === 鎸夐挳鐐瑰嚮鐗规晥锛堜粎鎸変笅鍙樻殫锛屽渾瑙掞級===
        now_ms = time.time() * 1000
        if self._pressed_btn is not None:
            bx, by, bw, bh = self._pressed_btn
            overlay = frame.copy()
            draw_rounded_rect(overlay, bx, by, bw, bh, 10, (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
        self._btn_flashes.clear()

        return frame


    def manual_select_region(self):
        """鎵嬪姩妗嗛€夛細OpenCV鐙珛绐楀彛1:1鏄剧ず娓告垙鎴浘锛屾嫋鎷芥閫夛紝鍧愭爣鍗虫父鎴忕獥鍙ｅ潗鏍?""
        self._was_random_running = self._random_running
        if self._random_running:
            self._stop_random()

        print("\n=== 鎵嬪姩妗嗛€?===")
        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]

        sel_win = "Select Minimap"
        cv2.namedWindow(sel_win, cv2.WINDOW_AUTOSIZE)  # 鑷姩閫傚簲鍥惧儚澶у皬锛岄伩鍏嶆爣棰樻爮杈规瀵艰嚧鏄剧ず鍖哄煙涓嶄竴鑷?
        # OpenCV绐楀彛瀵归綈娓告垙绐楀彛浣嶇疆锛岄伩鍏嶅亸绉?
        if self.window_rect:
            cv2.moveWindow(sel_win, self.window_rect["left"], self.window_rect["top"])
        else:
            cv2.moveWindow(sel_win, 0, 0)
        # 缃《锛氶伩鍏嶈娓告垙绐楀彛鎸′綇
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
        print("鍦ㄥ脊鍑虹殑绐楀彛涓婃嫋鎷芥閫夊皬鍦板浘锛屾澗寮€鑷姩纭锛屾寜 Esc 鍙栨秷")

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
                print("鍙栨秷妗嗛€?)
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
                    print("宸插簲鐢? (%d,%d) %dx%d锛堣嚜鍔ㄥ埛鏂板凡鍏抽棴锛岀偣鍒锋柊鍙噸鏂板紑鍚級" % (x1, y1, w, h))
                else:
                    print("閫夋嫨鍖哄煙澶皬")
                break
            if cv2.getWindowProperty(sel_win, cv2.WND_PROP_VISIBLE) < 1:
                break

        cv2.destroyWindow(sel_win)
        # F9缁撴潫鍚庡己鍒堕噸鏂板畾浣嶅拰缃《鎬墿钂欐澘锛堥伩鍏峅penCV绐楀彛褰卞搷钂欐澘缃《鍜屼綅缃級
        if getattr(self, '_overlay_hwnd', None) and self.hwnd and self.window_rect:
            try:
                wr = self.window_rect
                user32.SetWindowPos(self._overlay_hwnd, -1, wr['left'], wr['top'],
                                    wr['width'], wr['height'], 0x0050)
                _debug_log("[F9] 钂欐澘宸查噸鏂板畾浣嶇疆椤? %dx%d +%d+%d" % (wr['width'], wr['height'], wr['left'], wr['top']))
            except Exception as _e:
                _debug_log("[F9] 钂欐澘閲嶆柊瀹氫綅澶辫触: %s" % _e)
        if getattr(self, '_was_random_running', False) and self.route_mode == "闅忔満":
            self._start_random()

    def _stop_select_listener(self):
        pass

    def _confirm_select(self):
        """纭妗嗛€夛紙鏉惧紑榧犳爣鑷姩璋冪敤锛夛紝灏嗘樉绀哄潗鏍囨槧灏勫埌娓告垙绐楀彛鍧愭爣"""
        if not self._select_rect:
            return
        x1, y1, x2, y2 = self._select_rect
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        w = x2 - x1
        h = y2 - y1
        if w < 10 or h < 10:
            print("閫夋嫨鍖哄煙澶皬锛岃閲嶆柊鎷夊彇")
            self._select_rect = None
            return
        # 鏄剧ず鍧愭爣(FIXED_W x MAP_H)鏄犲皠鍒版父鎴忕獥鍙ｅ潗鏍?
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
        if getattr(self, '_was_random_running', False) and self.route_mode == "闅忔満":
            self._start_random()
        print("宸插簲鐢? (%d,%d) %dx%d锛堣嚜鍔ㄥ埛鏂板凡鍏抽棴锛岀偣鍒锋柊鍙噸鏂板紑鍚級" % (gx, gy, gw, gh))

    def _add_log(self, msg, color=None):
        """娣诲姞鏃ュ織锛宑olor涓哄彲閫夐鑹插弬鏁帮紙BGR鍏冪粍锛夛紝鐢ㄤ簬鍖哄垎鏃ュ織绫诲瀷"""
        self._logs.append(msg)
        if len(self._logs) > 20:
            self._logs = self._logs[-20:]

    def _rlog(self, msg, color=None):
        """娣诲姞杩愯鏃ュ織锛堟柊淇℃伅鍦ㄥ簳閮紝鍚戜笂娴佸姩锛?""
        if color is None:
            color = (40, 40, 40)
        t = time.strftime("%H:%M:%S")
        self._runtime_logs.append({"t": t, "msg": msg, "color": color})
        if len(self._runtime_logs) > self._log_max:
            self._runtime_logs = self._runtime_logs[-self._log_max:]
        # 鑷姩婊氬姩鍒板簳閮紙鏈€鏂帮級
        self._log_scroll = 0

    def _load_char_templates(self):
        """浠庣鐩樺姞杞藉凡淇濆瓨鐨勪汉鐗╃壒寰佹ā鏉?""
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
            print("[浜虹墿鐗瑰緛] 宸插姞杞?%d 濂楁ā鏉? % len(self._char_templates))
        except Exception as e:
            print("[浜虹墿鐗瑰緛] 鍔犺浇妯℃澘澶辫触:", e)

    def _save_char_meta(self):
        """淇濆瓨浜虹墿鐗瑰緛妯℃澘鍏冩暟鎹埌纾佺洏"""
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
            print("[浜虹墿鐗瑰緛] 淇濆瓨鍏冩暟鎹け璐?", e)

    def _capture_character_feature(self):
        """浜虹墿鐗瑰緛鎴浘锛氬湪娓告垙绐楀彛妗嗛€変汉鐗╄韩浣擄紝淇濆瓨涓虹壒寰佹ā鏉匡紙鏈€澶?0濂楋級
        浣跨敤 cv2.selectROI 鍐呯疆妗嗛€夛紝鍧愭爣鍙潬锛屾棤鏈€灏忓昂瀵搁檺鍒讹紙瓒婂皬瓒婄簿纭級"""
        if self.hwnd is None:
            self._add_log("璇峰厛缁戝畾娓告垙绐楀彛")
            print("[浜虹墿鐗瑰緛] 鏈粦瀹氱獥鍙?)
            return

        # 瓒呰繃涓婇檺鍒欐浛鎹㈡渶鏃╃殑涓€濂?
        if len(self._char_templates) >= CHAR_MAX_TEMPLATES:
            oldest = self._char_templates.pop(0)
            old_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % oldest["id"])
            if os.path.exists(old_path):
                os.remove(old_path)
            self._add_log("妯℃澘宸叉弧锛屾浛鎹㈡渶鏃╀竴濂?)

        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]
        if fh <= 0 or fw <= 0:
            self._add_log("鎴浘澶辫触")
            return

        print("[浜虹墿鐗瑰緛] 寮瑰嚭妗嗛€夌獥鍙ｏ紝鎷栨嫿妗嗛€変汉鐗╄韩浣擄紝鍥炶溅纭锛孍SC鍙栨秷")
        # cv2.selectROI 杩斿洖 (x, y, w, h)锛屽彇娑堣繑鍥炲叏0
        roi = cv2.selectROI("Select Character", frame, showCrosshair=False, fromCenter=False)
        cv2.destroyWindow("Select Character")

        x, y, w, h = roi
        if w <= 0 or h <= 0:
            print("[浜虹墿鐗瑰緛] 鍙栨秷妗嗛€?)
            return

        captured = frame[y:y + h, x:x + w].copy()

        # 鍒嗛厤鏂癐D锛堝彇鏈€澶D+1锛?
        existing_ids = [t["id"] for t in self._char_templates]
        new_id = (max(existing_ids) + 1) if existing_ids else 0
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")

        # 淇濆瓨鍒扮鐩?
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

        msg = "浜虹墿鐗瑰緛#%d宸蹭繚瀛?(%dx%d) 鍏?d濂? % (new_id, cw, ch, len(self._char_templates))
        self._add_log(msg)
        print("[浜虹墿鐗瑰緛]", msg)

    def _clear_character_features(self):
        """娓呴櫎鎵€鏈変汉鐗╃壒寰佹ā鏉?""
        count = len(self._char_templates)
        if count == 0:
            self._add_log("娌℃湁鍙竻闄ょ殑鐗瑰緛")
            return
        for t in self._char_templates:
            img_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % t["id"])
            if os.path.exists(img_path):
                os.remove(img_path)
        self._char_templates = []
        if os.path.exists(CHAR_TEMPLATE_META):
            os.remove(CHAR_TEMPLATE_META)
        self._add_log("宸叉竻闄?%d 濂椾汉鐗╃壒寰? % count)
        print("[鐗瑰緛娓呴櫎] 宸叉竻闄?%d 濂? % count)

    def _delete_char_template(self, index):
        """鍒犻櫎鎸囧畾绱㈠紩鐨勪汉鐗╃壒寰佹ā鏉?""
        if index < 0 or index >= len(self._char_templates):
            return
        t = self._char_templates.pop(index)
        img_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % t["id"])
        if os.path.exists(img_path):
            os.remove(img_path)
        self._save_char_meta()
        self._add_log("宸插垹闄や汉鐗╃壒寰?%d" % t["id"])
        print("[浜虹墿鐗瑰緛] 宸插垹闄?#%d" % t["id"])

    def _match_character(self, frame):
        """鍦ㄦ父鎴忕敾闈腑鐢ㄦā鏉垮尮閰嶆煡鎵句汉鐗╀綅缃?
        1. 鍏ㄥ浘鎼滅储锛堥槇鍊?.70锛?
        2. 鍏ㄥ浘澶辫触鏃跺湪涓婃浣嶇疆闄勮繎ROI鎼滅储锛堥槇鍊?.55锛夛紝閬垮厤鎴樻枟涓煭鏆備涪浜虹墿
        Returns:
            (center_x, center_y, confidence) 鎴?None
        """
        if not self._char_templates or frame is None:
            if not self._char_templates:
                _now = time.time()
                if not hasattr(self, '_last_no_tpl_log') or _now - self._last_no_tpl_log > 5:
                    self._last_no_tpl_log = _now
                    print("[浜虹墿鍖归厤] 娌℃湁浜虹墿鐗瑰緛妯℃澘锛岃鍏堝湪'浜虹墿鐗瑰緛'涓嬫媺涓坊鍔?)
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

        # === ROI鍥為€€锛氬湪涓婃鎴愬姛浣嶇疆闄勮繎160x160鑼冨洿鎼滅储锛岄槇鍊奸檷鍒?.55 ===
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
                    _debug_log("[浜虹墿鍖归厤] ROI鍥為€€鎴愬姛 %.2f (鍏ㄥ浘%.2f) 浣嶇疆(%d,%d)" % (roi_best, best_score, cx, cy))
                    return (cx, cy, roi_best)

        # 鍏ㄥ浘+ROI閮藉け璐ワ細鑺傛祦鏃ュ織
        _now = time.time()
        if not hasattr(self, '_last_lowscore_log') or _now - self._last_lowscore_log > 5:
            self._last_lowscore_log = _now
            _debug_log("[浜虹墿鍖归厤] 鍏ㄥ浘%.2f ROI澶辫触锛屼綆浜庨槇鍊?.2f" % (best_score, CHAR_MATCH_THRESHOLD))
        return None

    def _show_offset_feedback(self):
        """鍋忕Щ瑙嗚鍙嶉锛氳緭鍏ュ畬鎴?绉掑悗锛屽湪缁熶竴钂欐澘涓婅榛勭偣闂儊绾?绉?""
        if self._offset_feedback_done or self._offset_feedback_start == 0:
            return
        now_ms = time.time() * 1000
        elapsed = now_ms - self._offset_feedback_start
        if elapsed < 3000:
            return  # 绛?绉?
        # 鍙Е鍙戜竴娆?
        self._offset_feedback_done = True
        print("[鍋忕Щ鍙嶉] 鍋忕Щ榛勭偣灏嗗湪钂欐澘涓婇棯鐑?绉?)
        # 鍦ㄨ挋鏉挎暟鎹腑璁剧疆闂儊鎴鏃堕棿锛堣挋鏉夸富寰幆璐熻矗闂儊锛?
        if self._monster_overlay_data is not None:
            self._monster_overlay_data['blink_until'] = now_ms + 5000
        else:
            # 钂欐澘杩樻病鏁版嵁锛屽厛寤轰竴涓┖澹筹紝绛夎鑹插尮閰嶅埌浜嗚嚜鐒朵細闂儊
            self._monster_overlay_data = {'blink_until': now_ms + 5000}

    def _start_monster_overlay(self):
        """鍚姩鎬墿妫€娴嬮€忔槑钂欐澘锛堢疆椤堕€忔槑绐楀彛锛岀豢鑹茬嚎鏉′粠瑙掕壊鍋忕Щ鐐规寚鍚戞€墿锛?""
        if self._monster_overlay_running:
            return
        self._monster_overlay_running = True
        # 淇濈暀宸叉湁鏁版嵁锛堝鍋忕Щ闂儊blink_until锛夛紝涓嶉噸缃负None
        if self._monster_overlay_data is None:
            self._monster_overlay_data = {}
        t = threading.Thread(target=self._monster_overlay_loop, daemon=True)
        self._monster_overlay_thread = t
        t.start()
        _debug_log("[鎬墿钂欐澘] 宸插惎鍔紙浜虹墿妯℃澘%d濂楋紝闃堝€?.2f锛? % (len(self._char_templates), CHAR_MATCH_THRESHOLD))
        if not self._char_templates:
            self._add_log("钂欐澘宸插惎鍔紝浣嗘湭娣诲姞浜虹墿鐗瑰緛妯℃澘锛岄粍鐐逛笉浼氭樉绀?)

    def _stop_monster_overlay(self):
        """鍋滄鎬墿妫€娴嬮€忔槑钂欐澘"""
        self._monster_overlay_running = False
        self._monster_overlay_data = None
        # Force destroy the overlay window immediately (don't wait for thread loop)
        if self._overlay_hwnd:
            try:
                user32 = ctypes.windll.user32
                user32.DestroyWindow(self._overlay_hwnd)
                _debug_log("[鎬墿钂欐澘] 寮哄埗閿€姣佺獥鍙?hwnd=%s" % self._overlay_hwnd)
            except Exception as e:
                _debug_log("[鎬墿钂欐澘] DestroyWindow寮傚父: %s" % e)
            self._overlay_hwnd = None
        # Wait for overlay thread to exit (max 1 second)
        if self._monster_overlay_thread and self._monster_overlay_thread.is_alive():
            self._monster_overlay_thread.join(timeout=1.0)
            _debug_log("[鎬墿钂欐澘] 绾跨▼宸瞛oin")
        _debug_log("[鎬墿钂欐澘] 宸插仠姝?)

    def _monster_overlay_loop(self):
        """鍚庡彴绾跨▼锛氬垱寤虹疆椤堕€忔槑钂欐澘绐楀彛锛屾瘡100ms鏇存柊
        浼樺厛浣跨敤Win32鍘熺敓API锛堟墦鍖呭彲闈狅級锛屽け璐ュ洖閫€tkinter
        缁熶竴鏄剧ず锛氳鑹插亸绉婚粍鐐?+ 鎬墿缁挎/杩炵嚎 + 琛€鏉＄孩鐐?+ 钃濇潯钃濈偣"""
        try:
            self._win32_overlay_loop()
        except Exception as e:
            _debug_log("[鎬墿钂欐澘] Win32绐楀彛澶辫触: %s" % e)
            try:
                self._tkinter_overlay_loop()
            except Exception as e2:
                _debug_log("[鎬墿钂欐澘] tkinter涔熷け璐? %s" % e2)
        finally:
            # 绾跨▼閫€鍑烘椂閲嶇疆鏍囧織锛屽厑璁镐笅娆￠噸鍚?
            self._monster_overlay_running = False
            _debug_log("[鎬墿钂欐澘] 绾跨▼宸查€€鍑猴紝鏍囧織宸查噸缃?)

    def _win32_overlay_loop(self):
        """Win32鍘熺敓鍒嗗眰閫忔槑绐楀彛锛堜笉渚濊禆tkinter锛屾墦鍖呭悗鍙潬锛?""
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        kernel32 = ctypes.windll.kernel32
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

        # === 64浣嶅嚱鏁扮鍚嶏紙蹇呴』璁剧疆锛屽惁鍒欏彞鏌勮鎴柇鎴?2浣嶏級===
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

        # 鍥炶皟鍑芥暟绫诲瀷锛堝繀椤诲湪WNDCLASS涔嬪墠瀹氫箟锛屽瓧娈电被鍨嬬敤瀹冿級
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
                # === 鑷姩鏍″噯钂欐澘鎷栧姩锛堜粎stage=1鏃讹紝鎷栧姩缁跨偣钃濈偣瀹氱壒鑹蹭綅缃級===
                elif msg == 0x0201:  # WM_LBUTTONDOWN
                    if getattr(self, '_auto_calib_stage', 0) == 1:
                        # 鐢℅etCursorPos鍙栧睆骞曞潗鏍囷紙鏈€鍑嗭紝涓嶄緷璧栫獥鍙ｅ鎴峰尯锛?
                        cursor = wintypes.POINT()
                        user32.GetCursorPos(ctypes.byref(cursor))
                        mx, my = cursor.x, cursor.y
                        green_scr = getattr(self, '_auto_calib_green_screen', None)
                        blue_scr = getattr(self, '_auto_calib_blue_screen', None)
                        # 妫€娴嬫槸鍚︾偣涓豢鐐规垨钃濈偣锛埪?0px鑼冨洿锛屾柟渚跨偣鍑伙級
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
                                # 缁跨偣鍙兘姘村钩鎷栧姩锛孻淇濇寔鍩虹偣Y锛堟按骞筹級
                                self._auto_calib_green_screen = (mx, by)
                            elif self._auto_calib_dragging == 'blue':
                                # 钃濈偣鍙兘鍨傜洿鎷栧姩锛孹淇濇寔鍩虹偣X锛堝瀭鐩达級
                                self._auto_calib_blue_screen = (bx, my)
                        return 0
                elif msg == 0x0202:  # WM_LBUTTONUP
                    if getattr(self, '_auto_calib_dragging', None):
                        self._auto_calib_dragging = None
                        return 0
                elif msg == WM_PAINT:
                    _paint_count[0] += 1
                    if _paint_count[0] <= 3 or _paint_count[0] % 30 == 0:
                        _debug_log("[鎬墿钂欐澘] WM_PAINT 绗?d娆? % _paint_count[0])
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
                        # === 鑷姩鏍″噯鐐规爣璁帮紙浠卻tage=1鏃舵樉绀虹孩缁胯摑涓夌偣+杩炵嚎锛屾埅鍥惧悗闅愯棌锛屽彧鐣欑豢/钃濊窡韪渾锛?==
                        auto_base = getattr(self, '_auto_calib_base', None)
                        auto_stage = getattr(self, '_auto_calib_stage', 0)
                        if auto_base and len(auto_base) >= 4 and auto_stage == 1:
                            bx, by = auto_base[0], auto_base[1]  # 鍩虹偣灞忓箷鍧愭爣锛坰tage=1鏃跺疄鏃惰窡闅忎汉鐗╋級
                            # 缁跨偣钃濈偣鐢ㄧ浉瀵瑰亸绉昏绠楋紙stage=1鏃惰窡鐫€浜虹墿涓€璧风Щ鍔級
                            goff = getattr(self, '_auto_calib_green_offset', (400, 0))
                            boff = getattr(self, '_auto_calib_blue_offset', (0, -400))
                            rx, ry = bx + goff[0], by + goff[1]
                            tx, ty = bx + boff[0], by + boff[1]
                            # 瀹為檯璺濈锛堟嫋鍔ㄥ悗鐨勫€硷級
                            dx_real = rx - bx
                            dy_real = by - ty
                            # 鐢诲熀鐐癸紙绾㈣壊瀹炲績鍦嗭級
                            brush_calib = gdi32.CreateSolidBrush(0x0000FF)
                            if brush_calib:
                                gdi_objs.append(brush_calib)
                            old_brush_calib = gdi32.SelectObject(hdc, brush_calib)
                            gdi32.Ellipse(hdc, bx - 6, by - 6, bx + 7, by + 7)
                            gdi32.SelectObject(hdc, old_brush_calib)
                            gdi32.SetTextColor(hdc, 0x0000FF)
                            gdi32.SetBkMode(hdc, 1)
                            gdi32.TextOutW(hdc, bx + 8, by - 8, "鍩?, 1)
                            # 鐢荤豢鐐癸紙缁胯壊瀹炲績鍦嗭級
                            brush_g = gdi32.CreateSolidBrush(0x00FF00)
                            if brush_g:
                                gdi_objs.append(brush_g)
                            old_brush_g = gdi32.SelectObject(hdc, brush_g)
                            gdi32.Ellipse(hdc, rx - 6, ry - 6, rx + 7, ry + 7)
                            gdi32.SelectObject(hdc, old_brush_g)
                            gdi32.SetTextColor(hdc, 0x00FF00)
                            gdi32.TextOutW(hdc, rx + 8, ry - 8, "X", 1)
                            # 鐢昏摑鐐癸紙钃濊壊瀹炲績鍦嗭級
                            brush_b = gdi32.CreateSolidBrush(0xFF0000)
                            if brush_b:
                                gdi_objs.append(brush_b)
                            old_brush_b = gdi32.SelectObject(hdc, brush_b)
                            gdi32.Ellipse(hdc, tx - 6, ty - 6, tx + 7, ty + 7)
                            gdi32.SelectObject(hdc, old_brush_b)
                            gdi32.SetTextColor(hdc, 0xFF0000)
                            gdi32.TextOutW(hdc, tx + 8, ty - 8, "Y", 1)
                            # 鐢昏繛绾匡細鍩虹偣鈫掔豢鐐癸紙绾㈣壊锛夛紝鍩虹偣鈫掕摑鐐癸紙钃濊壊锛夛紝绾垮2鏇存槑鏄?
                            pen_r = gdi32.CreatePen(0, 2, 0x0000FF)
                            if pen_r:
                                gdi_objs.append(pen_r)
                            old_pen_r = gdi32.SelectObject(hdc, pen_r)
                            gdi32.MoveToEx(hdc, bx, by, None)
                            gdi32.LineTo(hdc, rx, ry)
                            gdi32.SelectObject(hdc, old_pen_r)
                            pen_b = gdi32.CreatePen(0, 2, 0xFF0000)
                            if pen_b:
                                gdi_objs.append(pen_b)
                            old_pen_b = gdi32.SelectObject(hdc, pen_b)
                            gdi32.MoveToEx(hdc, bx, by, None)
                            gdi32.LineTo(hdc, tx, ty)
                            gdi32.SelectObject(hdc, old_pen_b)
                            # 鏄剧ず瀹為檯璺濈锛堟嫋鍔ㄥ悗鐨勫€硷級
                            gdi32.SetTextColor(hdc, 0x00FFFF)
                            txt_x = "X:%d" % dx_real
                            txt_y = "Y:%d" % dy_real
                            gdi32.TextOutW(hdc, (bx + rx) // 2 - 20, (by + ry) // 2 - 10, txt_x, len(txt_x))
                            gdi32.TextOutW(hdc, (bx + tx) // 2 + 5, (by + ty) // 2, txt_y, len(txt_y))
                        # === 妯℃澘鍖归厤绌哄績鍦嗭紙stage>=2鏃讹紝鍦ㄥ尮閰嶄綅缃敾绌哄績鍦嗭紝鏍囪鐗硅壊浣嶇疆锛?==
                        # stage=2: 缁垮湀钃濆湀閮芥樉绀猴紱stage=3: 缁跨偣宸茶褰曪紝缁垮湀娑堝け锛屽彧鏄剧ず钃濆湀锛泂tage=4: 閮芥秷澶?
                        if auto_stage == 2 or auto_stage == 3:
                            # 缁胯壊鐗硅壊浣嶇疆缁垮厜鍦堬紙浠卻tage=2鏄剧ず锛宻tage=3缁跨偣宸茶褰曞悗娑堝け锛?
                            if auto_stage == 2:
                                gmatch = getattr(self, '_calib_green_match_pos', None)
                                if gmatch:
                                    green_pen = gdi32.CreatePen(0, 4, 0x00FF00)  # 缁胯壊BGR
                                    if green_pen:
                                        gdi_objs.append(green_pen)
                                    old_pen_g = gdi32.SelectObject(hdc, green_pen)
                                    gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 绌哄埛
                                    gx, gy = gmatch
                                    gdi32.Ellipse(hdc, gx - 20, gy - 20, gx + 21, gy + 21)
                                    gdi32.SelectObject(hdc, old_pen_g)
                            # 钃濊壊鐗硅壊浣嶇疆钃濆厜鍦堬紙stage=2鍜?閮芥樉绀猴紝stage=4钃濈偣宸茶褰曞悗娑堝け锛?
                            bmatch = getattr(self, '_calib_blue_match_pos', None)
                            if bmatch:
                                blue_pen = gdi32.CreatePen(0, 4, 0xFF0000)  # 钃濊壊BGR
                                if blue_pen:
                                    gdi_objs.append(blue_pen)
                                old_pen_b = gdi32.SelectObject(hdc, blue_pen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 绌哄埛
                                blx, bly = bmatch
                                gdi32.Ellipse(hdc, blx - 20, bly - 20, blx + 21, bly + 21)
                                gdi32.SelectObject(hdc, old_pen_b)
                        # === 鏍″噯姝ラ鏂囧瓧鎻愮ず锛堝睆骞曞乏涓婅锛屾槑鏄炬彁绀哄綋鍓嶇鍑犳锛?==
                        if auto_stage >= 1:
                            step_texts = {
                                1: "銆愮1姝?5銆戞嫋鍔ㄧ豢钃濆渾鍒扮壒鑹茶儗鏅綅缃紝瀹氬ソ鍚庣偣鍊嶇巼",
                                2: "銆愮2姝?5銆戜汉鐗╄蛋鍒扮豢鑹插渾涓婏紝绔欏ソ鍚庣偣鍊嶇巼",
                                3: "銆愮3姝?5銆戜汉鐗╄蛋鍒拌摑鑹插渾涓婏紝绔欏ソ鍚庣偣鍊嶇巼",
                                4: "銆愮4姝?5銆戝啀鐐逛竴娆″€嶇巼锛岃绠楀€嶇巼骞跺叧闂樉绀?,
                            }
                            step_txt = step_texts.get(auto_stage, "")
                            if step_txt:
                                gdi32.SetTextColor(hdc, 0x0000FF)  # 绾㈣壊鏂囧瓧
                                gdi32.SetBkMode(hdc, 1)  # 閫忔槑鑳屾櫙
                                # 鏂囧瓧鏄剧ず鍦ㄦ父鎴忕獥鍙ｆ渶椤朵笂锛堜笉鎸′綇璇嗗埆鍥剧墖锛?
                                txt_x = max(10, rect.right // 2 - 250)
                                txt_y = 10  # 鏈€椤朵笂
                                gdi32.TextOutW(hdc, txt_x, txt_y, step_txt, len(step_txt))
                        # === 钂欐澘涓存椂鎻愮ず鏂囧瓧锛堝鎴浘澶辫触鎻愮ず锛屾樉绀哄湪鏈€椤朵笂寮曞鏂囧瓧涓嬮潰锛?==
                        _ov_msg = getattr(self, '_calib_overlay_msg', None)
                        if _ov_msg:
                            _msg_txt, _msg_color, _msg_until = _ov_msg
                            if time.time() * 1000 < _msg_until:
                                gdi32.SetTextColor(hdc, _msg_color)
                                gdi32.SetBkMode(hdc, 1)
                                _msg_x = max(10, rect.right // 2 - 200)
                                _msg_y = 40  # 鏈€椤朵笂锛屽紩瀵兼枃瀛椾笅闈?
                                gdi32.TextOutW(hdc, _msg_x, _msg_y, _msg_txt, len(_msg_txt))
                            else:
                                self._calib_overlay_msg = None
                        data = self._monster_overlay_data
                        now_ms = time.time() * 1000
                        if data:
                            hp_marker = data.get('hp_marker')
                            if hp_marker:
                                hx, hy = hp_marker
                                pen = gdi32.CreatePen(0, 1, 0xFFFFFF)  # 鐧芥1px
                                if pen:
                                    gdi_objs.append(pen)
                                old_pen = gdi32.SelectObject(hdc, pen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 绌哄埛
                                gdi32.Rectangle(hdc, hx - 3, hy, hx + 3, hy + 10)
                                gdi32.SelectObject(hdc, old_pen)
                            mp_marker = data.get('mp_marker')
                            if mp_marker:
                                mx, my = mp_marker
                                pen = gdi32.CreatePen(0, 1, 0xFFFFFF)  # 鐧芥1px
                                if pen:
                                    gdi_objs.append(pen)
                                old_pen = gdi32.SelectObject(hdc, pen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 绌哄埛
                                gdi32.Rectangle(hdc, mx - 3, my, mx + 3, my + 10)
                                gdi32.SelectObject(hdc, old_pen)
                            char_pos = data.get('char_pos')
                            if char_pos:
                                if first_draw[0]:
                                    first_draw[0] = False
                                    _debug_log("[鎬墿钂欐澘] 棣栨缁樺埗榛勭偣 at %s" % (char_pos,))
                                cx, cy = char_pos
                                blink_until = data.get('blink_until', 0)
                                draw_dot = True
                                r = 6  # 缁熶竴鎸夌豢鐐瑰ぇ灏忥紙鍗婂緞6锛?
                                if blink_until > now_ms:
                                    if int(now_ms / 300) % 2 == 0:
                                        r = 7
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
                                # 鎬墿澶撮《琛€鏉＄豢鑹叉爣璁帮紙杩戞垬鎸′綇鎬椂鍑鏉″畾浣嶏級
                                for (bx, by, bw, bh) in data.get('monster_hp_bars', []):
                                    gdi32.Rectangle(hdc, bx, by, bx + bw, by + bh)
                    except Exception as e:
                        _debug_log("[鎬墿钂欐澘] 缁樺埗寮傚父: %s" % e)
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
                    _debug_log("[鎬墿钂欐澘] wnd_proc鏈崟鑾峰紓甯?msg=%d: %s" % (msg, _e))
                except Exception:
                    pass
                return 0

        wnd_proc_ref = WNDPROC(wnd_proc)
        # 淇濈暀鎵€鏈夊巻鍙插洖璋冨璞★紝闃叉琚獹C鍚庢棫绐楀彛娈嬩綑娑堟伅璋冪敤宸插洖鏀跺唴瀛?
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
        _debug_log("[鎬墿钂欐澘] RegisterClass atom=%s hinst=%s" % (atom, hinst))
        if not atom:
            _err = ctypes.get_last_error()
            _debug_log("[鎬墿钂欐澘] RegisterClass澶辫触 err=%d锛屽厛娉ㄩ攢鍐嶉噸璇? % _err)
            try:
                user32.UnregisterClassW(className, hinst)
            except Exception:
                pass
            atom = user32.RegisterClassW(ctypes.byref(wc))
            _debug_log("[鎬墿钂欐澘] RegisterClass閲嶈瘯 atom=%s" % atom)

        hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST,
            className, "Overlay", WS_POPUP | WS_VISIBLE,
            0, 0, 100, 100, None, None, hinst, None)
        _debug_log("[鎬墿钂欐澘] CreateWindow hwnd=%s" % hwnd)
        self._overlay_hwnd = hwnd
        if not hwnd:
            err = ctypes.get_last_error()
            _debug_log("[鎬墿钂欐澘] CreateWindowExW澶辫触, 閿欒鐮? %d" % err)
            raise RuntimeError("CreateWindowExW澶辫触, 閿欒鐮? %d" % err)

        user32.SetLayeredWindowAttributes(hwnd, COLOR_MAGENTA, 0, LWA_COLORKEY)
        user32.ShowWindow(hwnd, 5)  # SW_SHOW
        # 鍒涘缓鍚庣珛鍗冲畾浣嶅埌娓告垙绐楀彛锛堟暣涓獥鍙ｏ紝鍖呮嫭鏍囬鏍忥紝鍜宊capture_window鍧愭爣绯讳竴鑷达級
        if self.hwnd and self.window_rect:
            wr = self.window_rect
            _debug_log("[鎬墿钂欐澘] 绔嬪嵆瀹氫綅: %dx%d +%d+%d" % (wr['width'], wr['height'], wr['left'], wr['top']))
            user32.SetWindowPos(hwnd, -1, wr['left'], wr['top'],
                                wr['width'], wr['height'], 0x0050)
        else:
            # 鏃犳父鎴忕獥鍙ｅ潗鏍囨椂榛樿鏄剧ず鍦ㄥ睆骞曚腑澶紝纭繚绐楀彛鍙鐢ㄤ簬璇婃柇
            _sw = user32.GetSystemMetrics(0)
            _sh = user32.GetSystemMetrics(1)
            _dw, _dh = 800, 600
            _dx, _dy = (_sw - _dw) // 2, (_sh - _dh) // 2
            _debug_log("[鎬墿钂欐澘] 鏃犳父鎴忓潗鏍囷紝榛樿瀹氫綅: %dx%d +%d+%d" % (_dw, _dh, _dx, _dy))
            user32.SetWindowPos(hwnd, -1, _dx, _dy, _dw, _dh, 0x0050)
        user32.UpdateWindow(hwnd)
        user32.SetTimer(hwnd, IDT_TIMER, 100, None)
        _vis = user32.IsWindowVisible(hwnd)
        _style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        _debug_log("[鎬墿钂欐澘] 绐楀彛鐘舵€? visible=%s exstyle=0x%X" % (_vis, _style))
        _debug_log("[鎬墿钂欐澘] Win32绐楀彛宸插垱寤猴紝绛夊緟鏁版嵁...")

        msg = MSG()
        while self._monster_overlay_running:
            try:
                if self.hwnd and self.window_rect:
                    wr = self.window_rect
                    if first_draw[0]:
                        _debug_log("[鎬墿钂欐澘] 绐楀彛鍑犱綍: %dx%d +%d+%d" % (wr['width'], wr['height'], wr['left'], wr['top']))
                        first_draw[0] = False
                    user32.SetWindowPos(hwnd, -1, wr['left'], wr['top'],
                                        wr['width'], wr['height'], 0x0050)
                elif first_draw[0]:
                    _debug_log("[鎬墿钂欐澘] 璀﹀憡锛歨wnd鎴杦indow_rect鏃犳晥")
                    first_draw[0] = False
            except Exception as e:
                _debug_log("[鎬墿钂欐澘] SetWindowPos寮傚父: %s" % e)

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
        _debug_log("[鎬墿钂欐澘] Win32绐楀彛宸查攢姣?)

    def _tkinter_overlay_loop(self):
        """tkinter閫忔槑钂欐澘锛堝洖閫€鏂规锛?""
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        overlay = tk.Toplevel(root)
        overlay.overrideredirect(True)
        overlay.attributes('-topmost', True)
        overlay.attributes('-transparentcolor', 'magenta')
        canvas = tk.Canvas(overlay, bg='magenta', highlightthickness=0, bd=0)
        canvas.pack(fill='both', expand=True)
        print("[鎬墿钂欐澘] Tk绐楀彛宸插垱寤猴紝绛夊緟鏁版嵁...")
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
                            print("[鎬墿钂欐澘] 棣栨缁樺埗榛勭偣 at", char_pos)
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
                print("[鎬墿钂欐澘] 鏇存柊寮傚父:", e)
            overlay.after(100, update)

        overlay.after(100, update)
        root.mainloop()

    def _calc_character_monster_distance(self, char_pos, monster_bbox):
        """璁＄畻浜虹墿涓庢€墿涔嬮棿鐨勫儚绱犺窛绂?
        Args:
            char_pos: (x, y) 浜虹墿涓績鐐瑰潗鏍囷紙娓告垙绐楀彛鍍忕礌锛?
            monster_bbox: (x1, y1, x2, y2) 鎬墿妫€娴嬫锛堟父鎴忕獥鍙ｅ儚绱狅級
        Returns:
            float: 娆ф皬璺濈锛堝儚绱狅級锛屾垨 None 濡傛灉杈撳叆鏃犳晥
        """
        if char_pos is None or monster_bbox is None:
            return None
        cx, cy = char_pos[0], char_pos[1]
        mx1, my1, mx2, my2 = monster_bbox
        mcx = (mx1 + mx2) // 2
        mcy = (my1 + my2) // 2
        return float(np.sqrt((cx - mcx) ** 2 + (cy - mcy) ** 2))

    def _find_nearest_monster(self, char_pos, monster_bboxes):
        """浠庢€墿妫€娴嬪垪琛ㄤ腑鎵惧埌绂讳汉鐗╂渶杩戠殑鎬墿
        Args:
            char_pos: (x, y) 浜虹墿涓績鐐?
            monster_bboxes: [(x1,y1,x2,y2,conf,cls), ...] YOLO妫€娴嬬粨鏋?
        Returns:
            (index, distance) 鎴?(None, None)
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

    # ===== 鎵撴€?鑽搧 杈撳叆妗嗙郴缁?=====

    def _load_input_config(self):
        """鍔犺浇鎵撴€?鑽搧閰嶇疆鍒?_field_values锛堝彧鍔犺浇鐢ㄦ埛宸插綍鍏ョ殑鍊硷紝涓嶈榛樿鏄剧ず锛?""
        self._field_values = {}
        _debug_log("閰嶇疆鏂囦欢璺緞: %s 瀛樺湪=%s" % (INPUT_CONFIG_FILE, os.path.exists(INPUT_CONFIG_FILE)))
        if os.path.exists(INPUT_CONFIG_FILE):
            try:
                with open(INPUT_CONFIG_FILE, "r", encoding="utf-8") as fp:
                    saved = json.load(fp)
                for k, v in saved.items():
                    if v:
                        self._field_values[k] = str(v)
                _debug_log("鍔犺浇閰嶇疆: %s" % dict(self._field_values))
                print("[杈撳叆妗哴 宸插姞杞介厤缃紝鍏?%d 椤? % len(self._field_values))
            except Exception as e:
                _debug_log("鍔犺浇閰嶇疆澶辫触: %s" % e)
                print("[杈撳叆妗哴 鍔犺浇閰嶇疆澶辫触:", e)

    def _save_input_config(self):
        """淇濆瓨 _field_values 鍒扮鐩橈紙鍙繚瀛樺凡鐭ュ瓧娈典笖闈炵┖鐨勫€硷級"""
        known_ids = set(f[5] for f in FIGHT_FIELDS + POTION_FIELDS + ROUTE_FIELDS)
        to_save = {k: v for k, v in self._field_values.items() if k in known_ids and v}
        try:
            with open(INPUT_CONFIG_FILE, "w", encoding="utf-8") as fp:
                json.dump(to_save, fp, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[杈撳叆妗哴 淇濆瓨閰嶇疆澶辫触:", e)

    def _load_yolo_config(self):
        """鍔犺浇YOLO妯″瀷璺緞閰嶇疆"""
        try:
            if os.path.exists(YOLO_CONFIG_FILE):
                with open(YOLO_CONFIG_FILE, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                self._yolo_model_path = data.get("model_path")
                if self._yolo_model_path:
                    print("[YOLO] 宸查厤缃ā鍨?", self._yolo_model_path)
        except Exception as e:
            print("[YOLO] 鍔犺浇閰嶇疆澶辫触:", e)

    def _save_yolo_config(self):
        """淇濆瓨YOLO妯″瀷璺緞閰嶇疆"""
        try:
            with open(YOLO_CONFIG_FILE, "w", encoding="utf-8") as fp:
                json.dump({"model_path": self._yolo_model_path}, fp, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[YOLO] 淇濆瓨閰嶇疆澶辫触:", e)

    def _select_yolo_model(self):
        """寮瑰嚭鏂囦欢閫夋嫨妗嗭紝鎵嬪姩閫夋嫨YOLO onnx妯″瀷鏂囦欢
        浼樺厛浣跨敤Win32鍘熺敓瀵硅瘽妗嗭紙鎵撳寘鍚庡彲闈狅級锛屽け璐ュ垯鍥為€€tkinter"""
        path = self._win32_open_file(
            title="閫夋嫨YOLO妯″瀷鏂囦欢(.onnx)",
            filter_str="ONNX妯″瀷 (*.onnx)\0*.onnx\0鎵€鏈夋枃浠?(*.*)\0*.*\0",
            def_ext="onnx",
        )
        if path is None:
            return  # 鐢ㄦ埛鍙栨秷
        if path is False:
            self._add_log("鏂囦欢瀵硅瘽妗嗘墦寮€澶辫触锛岃鏌ョ湅鏃ュ織")
            print("[YOLO] 鏂囦欢瀵硅瘽妗嗘墦寮€澶辫触锛圵in32鍜宼kinter鍧囦笉鍙敤锛?)
            return
        if path:
            self._yolo_model_path = path
            self._yolo_net = None  # 閲嶇疆锛屽己鍒朵笅娆￠噸鏂板姞杞?
            self._save_yolo_config()
            if self._init_yolo():
                self._add_log("YOLO妯″瀷宸插姞杞? %s" % os.path.basename(path))
                print("[YOLO] 妯″瀷宸插姞杞?", path)
            else:
                self._add_log("YOLO妯″瀷鍔犺浇澶辫触")
                print("[YOLO] 妯″瀷鍔犺浇澶辫触")

    @staticmethod
    def _win32_open_file(title, filter_str, def_ext=""):
        """Win32鍘熺敓鎵撳紑鏂囦欢瀵硅瘽妗嗭紝杩斿洖璺緞瀛楃涓叉垨None锛堝彇娑堬級/False锛堝け璐ワ級"""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            comdlg32 = ctypes.windll.comdlg32

            # 姝ｇ‘璁剧疆64浣嶅嚱鏁扮鍚?
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
            # 鍙栬嚜韬玌I绐楀彛浣滀负鐖剁獥鍙?
            owner = user32.FindWindowW(None, "PLAY AND HAPPY")
            ofn.hwndOwner = owner if owner else None
            if owner:
                user32.SetForegroundWindow(owner)

            # CBT閽╁瓙锛氬璇濇婵€娲绘椂寮哄埗缃《锛堥槻姝㈣棌鍦ㄥ叾浠栫獥鍙ｅ悗闈級
            WH_CBT = 5
            HCBT_ACTIVATE = 5
            CBTProc = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int,
                                         wintypes.WPARAM, wintypes.LPARAM)
            hook_ref = [None]  # 淇濇寔寮曠敤闃叉GC

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
            _debug_log("[鏂囦欢閫夋嫨] CBT閽╁瓙=%s owner=%s structSize=%d" % (hook_ref[0], owner, ctypes.sizeof(OPENFILENAMEW)))

            result = comdlg32.GetOpenFileNameW(ctypes.byref(ofn))

            if hook_ref[0]:
                user32.UnhookWindowsHookEx(hook_ref[0])

            if result:
                _debug_log("[鏂囦欢閫夋嫨] 鎴愬姛: %s" % file_buf.value)
                return file_buf.value
            # 杩斿洖0锛氱敤鎴峰彇娑堟垨鍑洪敊
            try:
                err = comdlg32.CommDlgExtendedError()
            except Exception:
                err = 0
            if err != 0:
                _debug_log("[鏂囦欢閫夋嫨] GetOpenFileNameW閿欒鐮? 0x%X" % err)
            else:
                _debug_log("[鏂囦欢閫夋嫨] 鐢ㄦ埛鍙栨秷")
            return None  # 鐢ㄦ埛鍙栨秷
        except Exception as e:
            _debug_log("[鏂囦欢閫夋嫨] Win32瀵硅瘽妗嗗紓甯? %s" % e)
            # 鍥為€€鍒皌kinter
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                path = filedialog.askopenfilename(
                    title=title,
                    filetypes=[("ONNX妯″瀷", "*.onnx"), ("鎵€鏈夋枃浠?, "*.*")]
                )
                root.destroy()
                return path if path else None
            except Exception as e2:
                _debug_log("[鏂囦欢閫夋嫨] tkinter涔熷け璐? %s" % e2)
                return False

    def _get_fields_for_tab(self, tab):
        """杩斿洖鎸囧畾鏍囩椤电殑瀛楁鍒楄〃"""
        if tab == "fight":
            return FIGHT_FIELDS
        elif tab == "potion":
            return POTION_FIELDS
        elif tab == "route":
            return ROUTE_FIELDS
        return []

    def _find_field_at(self, x, y, tab):
        """鏌ユ壘 (x,y) 浣嶇疆鐨勫瓧娈碉紝杩斿洖瀛楁鍏冪粍鎴?None"""
        for f in self._get_fields_for_tab(tab):
            fx, fy, fw, fh, ftype, fid = f
            if fx <= x < fx + fw and fy <= y < fy + fh:
                return f
        return None

    def _handle_input_mouse(self, x, y):
        """鎵撴€?鑽搧椤电殑榧犳爣鐐瑰嚮澶勭悊锛氳仛鐒﹁緭鍏ユ鎴栧彇娑堣仛鐒?""
        field = self._find_field_at(x, y, self._current_tab)
        if field:
            _, _, _, _, ftype, fid = field
            self._focused_field = fid
            self._last_input_change = time.time() * 1000
            self._num_field_replace = (ftype == "num")  # 鏁板瓧妗嗚仛鐒﹀悗棣栨杈撳叆瑕嗙洊鏃у€?
            print("[杈撳叆妗哴 鑱氱劍:", fid, "绫诲瀷:", ftype)
        else:
            # 鐐瑰嚮鍏朵粬鍦版柟锛屼繚瀛樺苟鍙栨秷鑱氱劍
            if self._focused_field is not None:
                self._save_input_config()
                self._focused_field = None

    def _key_code_to_name(self, key):
        """灏?cv2.waitKey 杩斿洖鐨勯敭鐮佽浆涓洪敭鍚嶅瓧绗︿覆"""
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
            # 绗﹀彿閿洿鎺ョ敤瀛楃
            if ch in "`-=[]\\;',./":
                return ch
        return None

    def _handle_input_key(self, key):
        """鑱氱劍杈撳叆妗嗘椂鐨勯敭鐩樺鐞嗭紝杩斿洖 True 琛ㄧず宸叉秷璐硅鎸夐敭"""
        if self._focused_field is None:
            return False

        fid = self._focused_field
        # 鎵惧瓧娈电被鍨?
        ftype = "num"
        for f in FIGHT_FIELDS + POTION_FIELDS:
            if f[5] == fid:
                ftype = f[4]
                break

        if ftype == "key":
            # ESC娓呯┖閿€硷紝鍥炶溅鍙栨秷
            if key == 27:
                self._field_values[fid] = ""
                self._save_input_config()
                self._focused_field = None
                return True
            if key == 13:
                self._focused_field = None
                return True
            # 鎸夐敭褰曞叆锛氭崟鑾风涓€涓湁鏁堥敭鍚庤嚜鍔ㄥけ鐒?
            name = self._key_code_to_name(key)
            if name:
                self._field_values[fid] = name
                print("[杈撳叆妗哴 鎸夐敭褰曞叆:", fid, "=", name)
                self._focused_field = None
                self._save_input_config()
            return True

        elif ftype == "num":
            # 鏁板瓧褰曞叆
            _is_offset = fid in ("char_x_offset", "char_y_offset")
            if 48 <= key <= 57:  # 0-9
                cur = self._field_values.get(fid, "")
                if getattr(self, '_num_field_replace', False):
                    new_val = chr(key)  # 鑱氱劍鍚庨娆¤緭鍏ヨ鐩栨棫鍊?
                    self._num_field_replace = False
                else:
                    new_val = cur + chr(key)
                # HP/MP闃堝€肩櫨鍒嗘瘮涓婇檺100
                if fid in ("hp_value", "mp_value") and int(new_val) > 100:
                    return True
                if len(new_val) <= 10:
                    self._field_values[fid] = new_val
                    self._last_input_change = time.time() * 1000
            elif _is_offset and key == 45:  # 璐熷彿锛堜粎鍋忕Щ瀛楁鍏佽锛?
                cur = self._field_values.get(fid, "")
                if getattr(self, '_num_field_replace', False):
                    new_val = "-"
                    self._num_field_replace = False
                elif not cur.startswith("-"):
                    new_val = "-" + cur  # 鍦ㄥ紑澶村姞璐熷彿
                else:
                    new_val = cur[1:]  # 宸叉湁璐熷彿鍒欏幓鎺?
                if len(new_val) <= 10:
                    self._field_values[fid] = new_val
                    self._last_input_change = time.time() * 1000
            elif key == 8:  # 閫€鏍?
                cur = self._field_values.get(fid, "")
                if cur:
                    self._field_values[fid] = cur[:-1]
                    self._last_input_change = time.time() * 1000
                self._num_field_replace = False  # 閫€鏍煎悗鍙栨秷瑕嗙洊鐘舵€?
            elif key in (13, 27):  # 鍥炶溅鎴朎SC纭
                # 鍥炶溅鏃跺啀鍋氫竴娆′笂闄愭牎楠?
                if key == 13 and fid in ("hp_value", "mp_value"):
                    val = self._field_values.get(fid, "")
                    if val:
                        max_val = self._max_hp if fid == "hp_value" else self._max_mp
                        if max_val > 0 and int(val) > max_val:
                            print("[鏍￠獙] %s闃堝€?%s 瓒呭嚭涓婇檺 %d锛屽凡娓呯┖" % (fid, val, max_val))
                            self._field_values[fid] = ""
                self._focused_field = None
                self._save_input_config()
            return True

        return False

    def _draw_input_fields(self, frame):
        """鍦?frame 涓婄粯鍒惰緭鍏ユ鑱氱劍杈规鍜岀敤鎴峰凡褰曞叆鐨勫€硷紙涓嶇敾浠讳綍榛樿/鍗犱綅鏂囧瓧锛?""
        fields = self._get_fields_for_tab(self._current_tab)
        for f in fields:
            fx, fy, fw, fh, ftype, fid = f
            val = self._field_values.get(fid, "")
            is_focused = (self._focused_field == fid)

            # 鍋忕Щ瀛楁浣跨敤瀹為檯缁樺埗鍖哄煙鐢昏仛鐒︽
            if fid == "char_x_offset":
                fx, fy, fw, fh = OFFSET_X_DRAW
            elif fid == "char_y_offset":
                fx, fy, fw, fh = OFFSET_Y_DRAW

            # 鑱氱劍鏃剁敾姗欒壊杈规
            if is_focused:
                cv2.rectangle(frame, (fx, fy), (fx + fw - 1, fy + fh - 1),
                              INPUT_FOCUS_COLOR, 2)

            # 鍙湪鐢ㄦ埛宸插綍鍏ユ椂鐢诲€?
            if val:
                if fid in ("char_x_offset", "char_y_offset"):
                    # 鍋忕Щ鏁板瓧锛氬皬涓€鍙枫€佷笉鍔犵矖
                    fscale = 0.6
                    fthick = 1
                    (tw, th), _ = cv2.getTextSize(val, INPUT_FONT, fscale, fthick)
                    tx = fx + (fw - tw) // 2
                    ty = fy + (fh + th) // 2 - 1 + 2  # 鍚戜笅寰皟
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
                # 绌烘鏄剧ず鍗犱綅鏂囧瓧
                ph = "鐧惧垎姣旇缃?
                (tw, th), _ = cv2.getTextSize(ph, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
                tx = fx + (fw - tw) // 2
                ty = fy + (fh + th) // 2 - 1
                cv2.putText(frame, ph, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                            (150, 150, 150), 1, cv2.LINE_AA)

    def _get_fight_config(self):
        """鑾峰彇鎵撴€厤缃紙渚涙垬鏂楅€昏緫璋冪敤锛?
        skill_random: 鎶€鑳介殢鏈烘椂闂?+-ms)锛屽奖鍝嶄富鏀?缇ゆ敾瑙﹀彂
        buff_random: BUFF鎶€鑳介殢鏈烘椂闂?+-ms)锛屽奖鍝岯UFF瑙﹀彂"""
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
        """鑾峰彇鑽搧閰嶇疆锛堜緵鑽搧閫昏緫璋冪敤锛?""
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

    # ===== HP/MP鑷姩鍚冭嵂 =====

    def _is_key_field(self, fid):
        """鍒ゆ柇瀛楁鏄惁涓烘寜閿綍鍏ョ被鍨?""
        for f in FIGHT_FIELDS + POTION_FIELDS:
            if f[5] == fid:
                return f[4] == "key"
        return False

    def _poll_key_capture(self):
        """鐢℅etAsyncKeyState杞鎹曡幏鎸夐敭锛堟敮鎸丗1-F12/Ctrl/Shift/Home/End绛夋墍鏈夐敭锛?
        鍙崟鑾锋柊鎸変笅鐨勯敭锛堜笉鎹曡幏鎸変綇涓嶆斁鐨勶級"""
        if self._focused_field is None or not self._is_key_field(self._focused_field):
            return
        current_pressed = set()
        for vk in VK_POLL_LIST:
            if user32.GetAsyncKeyState(vk) & 0x8000:
                current_pressed.add(vk)
        # 鎵惧嚭鏂版寜涓嬬殑閿紙鏈鎸変笅浣嗕笂娆℃病鎸変笅锛?
        new_keys = current_pressed - self._prev_key_states
        self._prev_key_states = current_pressed
        if new_keys:
            # 鍙栫涓€涓柊鎸変笅鐨勯敭
            vk = min(new_keys)
            name = VK_TO_NAME.get(vk, "vk_%d" % vk)
            self._field_values[self._focused_field] = name
            print("[鎸夐敭褰曞叆] %s = %s (vk=0x%02X)" % (self._focused_field, name, vk))
            self._focused_field = None
            self._save_input_config()
            self._prev_key_states = set()
            self._last_input_change = time.time() * 1000

    def _poll_num_input(self):
        """鐢℅etAsyncKeyState杞鎹曡幏鏁板瓧杈撳叆锛堝叏灞€鏈夋晥锛屼笉渚濊禆UI绐楀彛鐒︾偣锛?
        鏀寔涓婚敭鐩?-9銆佸皬閿洏0-9銆侀€€鏍笺€佸洖杞︺€丒SC
        鍙崟鑾锋柊鎸変笅鐨勯敭锛堜笉鎹曡幏鎸変綇涓嶆斁鐨勶級"""
        if self._focused_field is None or self._is_key_field(self._focused_field):
            return
        fid = self._focused_field
        if not hasattr(self, '_prev_num_states'):
            self._prev_num_states = set()
        # 杞锛氫富閿洏0-9(0x30-0x39) + 灏忛敭鐩?-9(0x60-0x69) + 閫€鏍?0x08) + 鍥炶溅(0x0D) + ESC(0x1B)
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
        # 瑙ｆ瀽鎸夐敭
        if 0x30 <= vk <= 0x39:
            digit = chr(vk)
        elif 0x60 <= vk <= 0x69:
            digit = chr(vk - 0x60 + 0x30)  # 灏忛敭鐩樿浆鏁板瓧瀛楃
        elif vk == 0x08:
            # 閫€鏍?
            cur = self._field_values.get(fid, "")
            if cur:
                self._field_values[fid] = cur[:-1]
                self._last_input_change = time.time() * 1000
            self._num_field_replace = False
            return
        elif vk == 0x0D:
            # 鍥炶溅纭锛圚P/MP涓婇檺鏍￠獙锛?
            val = self._field_values.get(fid, "")
            if val and fid in ("hp_value", "mp_value"):
                max_val = self._max_hp if fid == "hp_value" else self._max_mp
                if max_val > 0 and int(val) > max_val:
                    print("[鏍￠獙] %s闃堝€?%s 瓒呭嚭涓婇檺 %d锛屽凡娓呯┖" % (fid, val, max_val))
                    self._field_values[fid] = ""
            self._focused_field = None
            self._save_input_config()
            self._prev_num_states = set()
            return
        elif vk == 0x1B:
            # ESC鍙栨秷
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
        # 鏁板瓧杈撳叆锛氶娆¤鐩栵紝鍚庣画杩藉姞
        cur = self._field_values.get(fid, "")
        if getattr(self, '_num_field_replace', False):
            new_val = digit
            self._num_field_replace = False
        else:
            new_val = cur + digit
        # HP/MP闃堝€肩櫨鍒嗘瘮涓婇檺100
        if fid in ("hp_value", "mp_value") and int(new_val) > 100:
            return
        if len(new_val) <= 10:
            self._field_values[fid] = new_val
            self._last_input_change = time.time() * 1000
            if fid in ("char_x_offset", "char_y_offset"):
                self._offset_feedback_start = time.time() * 1000
                self._offset_feedback_done = False

    def _key_to_vk(self, key_name):
        """閿悕杞櫄鎷熼敭鐮?""
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
        """SendInput鎵弿鐮佸彂閿?+ AttachThreadInput寮哄埗鍓嶅彴銆俤uration涓烘寜閿繚鎸乵s锛岄粯璁ら殢鏈?0-180"""
        vk = self._key_to_vk(key_name)
        if vk is None:
            _debug_log("鎸夐敭鏈煡: %s" % key_name)
            return
        if not self.hwnd:
            _debug_log("鏃犵獥鍙ｅ彞鏌?)
            return
        if duration is None:
            duration = random.randint(80, 180)
        kernel32 = ctypes.windll.kernel32
        scan = user32.MapVirtualKeyW(vk, 0)
        EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0xA3, 0xA5}
        ext = 0x0001 if vk in EXTENDED_VKS else 0
        old_fg = user32.GetForegroundWindow()
        _debug_log("鍙戦敭 %s vk=0x%02X scan=0x%02X ext=%d dur=%d" % (key_name, vk, scan, ext, duration))

        # === 寮哄埗鎶婃父鎴忕獥鍙ｆ媺鍒板墠鍙?===
        game_thread = user32.GetWindowThreadProcessId(self.hwnd, None)
        cur_thread = kernel32.GetCurrentThreadId()
        attached = False
        if game_thread != 0 and game_thread != cur_thread:
            attached = user32.AttachThreadInput(cur_thread, game_thread, True)

        # 鍏堟ā鎷熸寜涓€涓婣lt閿紝缁曡繃Windows SetForegroundWindow闄愬埗
        user32.keybd_event(0x12, 0, 0, 0)  # Alt down
        user32.keybd_event(0x12, 0, 0x0002, 0)  # Alt up
        user32.BringWindowToTop(self.hwnd)
        fg_ret = user32.SetForegroundWindow(self.hwnd)
        # 濡傛灉杩樻病鎴愬姛锛屽啀璇曚竴娆★紙甯︽渶灏忓寲鎭㈠锛?
        if user32.GetForegroundWindow() != self.hwnd:
            if user32.IsIconic(self.hwnd):
                user32.ShowWindow(self.hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(self.hwnd)
        time.sleep(0.05)
        fg_now = user32.GetForegroundWindow()
        fg_ok = (fg_now == self.hwnd)
        if not fg_ok:
            _debug_log("[鍙戦敭璀﹀憡] 鍓嶅彴鍒囨崲澶辫触! fg_ret=%d 褰撳墠鍓嶅彴hwnd=%s 鐩爣hwnd=%s attached=%d" % (
                fg_ret, fg_now, self.hwnd, attached))

        # === 鐢?SendInput 鍙戦€佹寜閿紙姣?keybd_event 鏇村彲闈狅級===
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
            inp.ki.wVk = 0  # 鎵弿鐮佹ā寮忎笅wVk璁?
            inp.ki.wScan = scan_code
            inp.ki.dwFlags = flags | 0x0008  # KEYEVENTF_SCANCODE锛孌irectInput鍏煎
            inp.ki.time = 0
            inp.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        # 娓呴櫎鍙兘鍗′綇鐨勪慨楗伴敭锛圓lt/Ctrl/Shift锛夛紝閬垮厤Alt+Key缁勫悎
        for mod_vk in (0x12, 0x11, 0x10):  # Alt, Ctrl, Shift
            if user32.GetAsyncKeyState(mod_vk) & 0x8000:
                mod_scan = user32.MapVirtualKeyW(mod_vk, 0)
                send_key(mod_vk, mod_scan, 0x0002)  # KEYEVENTF_KEYUP
                _debug_log("娓呴櫎鍗′綇鐨勪慨楗伴敭 vk=0x%02X" % mod_vk)

        send_key(vk, scan, ext)  # keydown
        time.sleep(duration / 1000.0)
        send_key(vk, scan, ext | 0x0002)  # keyup (KEYEVENTF_KEYUP)
        # keybd_event鍙屽彂鍏滃簳锛圖irectInput娓告垙鏈夋椂鍙keybd_event锛?
        user32.keybd_event(vk, scan, ext, 0)
        time.sleep(duration / 1000.0 * 0.5)
        user32.keybd_event(vk, scan, ext | 0x0002, 0)
        _debug_log("SendInput(鎵弿鐮?+keybd_event鍙屽彂宸插彂閫?fg_ok=%d attached=%d dur=%d" % (fg_ok, attached, duration))
        time.sleep(0.05)

        # 鎭㈠鍘熷墠鍙扮獥鍙ｅ苟鍒嗙绾跨▼
        if attached:
            if old_fg and old_fg != self.hwnd:
                user32.SetForegroundWindow(old_fg)
            user32.AttachThreadInput(cur_thread, game_thread, False)

    def _detect_hp_mp_bars(self, frame):
        """妫€娴婬P/MP琛€鏉★細鎼滃簳閮?0px锛堣鏉″湪y=770~778锛岃窛搴曢儴绾?0px锛夛紝HSV棰滆壊锛孒P鍦ㄥ乏MP鍦ㄥ彸"""
        if frame is None:
            return None, None
        h, w = frame.shape[:2]
        y_start = max(0, h - 50)  # 鍘焗-25澶皬锛岃鏉″湪y=770璺濆簳閮?7px锛岄渶瑕佹悳鍒板簳閮?0px
        roi = frame[y_start:, :]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # HP绾㈣壊
        hp_mask1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([12, 255, 255]))
        hp_mask2 = cv2.inRange(hsv, np.array([168, 80, 80]), np.array([180, 255, 255]))
        hp_mask = (hp_mask1 | hp_mask2) > 0
        # MP钃濈传鑹诧紙鏍峰搧鑹睭鈮?60锛岃寖鍥存斁瀹借鐩栬摑鍒扮传钃濓級
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

        # === 浣庤閲忓厹搴曪細绾㈣壊/钃濊壊濉厖<20px鏃禵find_longest_hbar杩斿洖None ===
        # 鐢ㄤ笂娆＄ǔ瀹氫綅缃厹搴曪紙鏉＄殑y鍧愭爣鍩烘湰涓嶅彉锛?
        if hp_bar is None and getattr(self, '_hp_bar_stable', None):
            hp_bar = self._hp_bar_stable
            _debug_log("HP棰滆壊妫€娴嬪け璐?<20px)锛屼娇鐢ㄧǔ瀹氱紦瀛?y=%d" % hp_bar[1])
        if mp_bar is None and getattr(self, '_mp_bar_stable', None):
            mp_bar = self._mp_bar_stable
            _debug_log("MP棰滆壊妫€娴嬪け璐?<20px)锛屼娇鐢ㄧǔ瀹氱紦瀛?y=%d" % mp_bar[1])
        # 棣栨灏变綆琛€閲忥細鎵弿搴曢儴25px浠绘剰绾㈣壊鍍忕礌鎵緔鍧愭爣
        if hp_bar is None:
            for row in range(hp_mask.shape[0]):
                if hp_mask[row].sum() >= 1:
                    hp_bar = (0, y_start + row, 0)  # 鍗犱綅锛屼笅闈㈡浛鎹负鍥哄畾浣嶇疆
                    _debug_log("HP棣栨浣庤閲忥紝鎵弿鍒扮孩鑹茶 y=%d" % (y_start + row))
                    break
        if mp_bar is None and hp_bar:
            for row in range(mp_mask.shape[0]):
                if mp_mask[row].sum() >= 1:
                    mp_bar = (0, y_start + row, 0)
                    _debug_log("MP棣栨浣庤閲忥紝鎵弿鍒拌摑鑹茶 y=%d" % (y_start + row))
                    break

        # 鍥哄畾琛€鏉′綅缃拰瀹藉害锛堢獥鍙ｅぇ灏忓浐瀹?382x807锛屽潗鏍囦笉鍙橈級
        # HP鏉★細宸?510锛屽=107锛汳P鏉★細宸?619锛屽=107锛堝拰HP涓€鏍烽暱锛?
        # Y鍧愭爣鍥哄畾鎴愭鍊硷紝涓嶉殢妫€娴嬪彉鍖栵紝閬垮厤姣忔鍚姩Y鍊间笉涓€鏍?
        FIXED_HP_LEFT = 510
        FIXED_MP_LEFT = 619
        FIXED_BAR_WIDTH = 107
        FIXED_BAR_Y = 782  # HP/MP鏉″浐瀹歒鍧愭爣锛堟鍊硷紝濡傞渶璋冩暣鏀硅繖涓暟瀛楋級
        if hp_bar:
            hp_bar = (FIXED_HP_LEFT, FIXED_BAR_Y, FIXED_BAR_WIDTH)
        if mp_bar:
            mp_bar = (FIXED_MP_LEFT, FIXED_BAR_Y, FIXED_BAR_WIDTH)
        elif hp_bar:
            # MP棰滆壊妫€娴嬪け璐ワ紙MP涓嶆弧鏃惰摑鑹插皯锛夛紝鐢ㄥ浐瀹歒鍧愭爣
            mp_bar = (FIXED_MP_LEFT, FIXED_BAR_Y, FIXED_BAR_WIDTH)
        # Y宸插浐瀹氭垚姝诲€硷紝涓嶉渶瑕佺ǔ瀹氭€х紦瀛橈紝閬垮厤瑕嗙洊鍥哄畾Y鍊煎鑷村弻妫€娴嬫
        _debug_log("琛€鏉℃娴? hp=%s mp=%s" % (hp_bar, mp_bar))
        return hp_bar, mp_bar

    def _measure_bar_total_width(self, frame, x, y, color_type):
        """浠庢潯鐨勫乏杈圭晫鍚戝彸鎵弿锛屾壘鍒版潯鐨勫彸杈圭紭锛堥潪鏉″唴棰滆壊锛夛紝杩斿洖鎬诲搴?
        MP鏉″唴=B>180(浜摑+鏆楄摑), HP鏉″唴=R>100(浜孩+鏆楃孩)"""
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
                # 绾㈣壊鍗犱紭鎵嶇畻鏉″唴锛堟帓闄ょ伆鑹茬┖鐧借儗鏅級
                in_bar = ri > 80 and ri - gi > 10 and ri - bi > 10
            else:
                # 钃濊壊鍗犱紭鎵嶇畻鏉″唴锛堟帓闄ょ伆鑹茬┖鐧借儗鏅級
                in_bar = bi > 100 and bi - ri > 10 and bi - gi > 10
            if in_bar:
                out_count = 0
            else:
                out_count += 1
                if out_count >= 5:
                    return i - 4
        return None

    def _find_longest_hbar(self, mask, y_offset, x_min=0, x_max=99999, y_center=None, y_tol=8, max_w=200):
        """璺ㄦ墍鏈夎鎵炬渶闀挎按骞宠繛缁锛屽彲闄愬埗x鑼冨洿鍜寉涓績锛岃繑鍥?x,y,w)鎴朜one"""
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

    # HP/MP鏉″弬鑰冭壊锛堜粠鏍峰搧鍥惧彇鑹诧紝BGR鏍煎紡锛?
    HP_REF_COLOR = (0, 0, 238)    # 绾㈣壊
    MP_REF_COLOR = (222, 111, 0)  # 钃濋潚鑹?
    COLOR_MATCH_DIST = 50         # 娆ф皬璺濈闃堝€硷紝灏忎簬姝ゅ€肩畻鍚岃壊

    def _is_bar_blank_at(self, frame, bar, pct, color_type):
        """绔栨妫€娴嬶細鍦╬ct%浣嶇疆鍙栧尯鍩燂紝鐢ㄧ伆鑹叉ā鏉垮尮閰嶏紝鍖归厤鍒?绌虹櫧=鍔犺嵂銆?
        妯℃澘鏄敤鎴锋埅鍙栫殑琛€鏉＄┖鐧界伆鑹查儴鍒?gray_bar.png)锛岀洿鎺atchTemplate銆?""
        if bar is None or frame is None or self._gray_bar_template is None:
            return False
        x, y, bw = bar
        check_x = x + int(bw * pct / 100.0)
        if check_x >= frame.shape[1] or check_x < 0:
            return False
        th, tw = self._gray_bar_template.shape[:2]
        # 鍦╟heck_x鍛ㄥ洿鍙栨瘮妯℃澘澶х殑ROI
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
        _debug_log("绔栨鍖归厤 %s: x=%d pct=%d 鍖归厤搴?%.3f -> %s" % (
            color_type, check_x, pct, max_val, match_ok))
        return match_ok

    def _init_digit_templates(self):
        """鐢熸垚0-9鏁板瓧妯℃澘锛堢敤cv2缁樺浘锛屼笉渚濊禆澶栭儴OCR锛?""
        if self._digit_templates:
            return
        for d in range(10):
            img = np.zeros((26, 16), dtype=np.uint8)
            cv2.putText(img, str(d), (1, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 2, cv2.LINE_AA)
            self._digit_templates[d] = img

    def _recognize_digits(self, crop):
        """浠庤鍓尯鍩熻瘑鍒暟瀛楋紝杩斿洖鏁板瓧瀛楃涓诧紙鍚?锛?""
        if crop is None or crop.size == 0:
            return ""
        self._init_digit_templates()
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # 鐧藉瓧闃堝€硷紙娓告垙鏁板瓧鏄寒鐧借壊锛?
        _, thresh = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # 鎸墄鍧愭爣鎺掑簭
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
                # 缁嗙珫绾垮彲鑳芥槸 / 鎴?|
                result += "/"
        return result

    def _detect_hp_mp_max(self, frame):
        """鐢ㄦ暟瀛楁ā鏉垮尮閰嶈鍙朒P/MP鐨?current/max锛屾洿鏂颁笂闄?""
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
            # 瑁佸壀琛€鏉′笂鏂圭殑鏂囧瓧鍖哄煙锛堟暟瀛楀湪鏉′笂鏂癸級
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
                            print("[涓婇檺妫€娴媇 %s=%d (璇嗗埆:%s)" % (attr, max_val, text))
                            # 闃堝€间负绌烘椂榛樿璁炬垚涓婇檺鐨勪竴鍗?
                            fid = "hp_value" if attr == "_max_hp" else "mp_value"
                            if not self._field_values.get(fid, ""):
                                half = max_val // 2
                                self._field_values[fid] = str(half)
                                self._save_input_config()
                                print("[涓婇檺妫€娴媇 %s 榛樿闃堝€?%d" % (fid, half))
            except Exception as e:
                print("[涓婇檺妫€娴媇 鍑洪敊:", e)

    def _init_yolo(self):
        """鍔犺浇YOLO onnx妯″瀷锛坈v2.dnn锛屼笉渚濊禆onnxruntime锛?""
        if self._yolo_net is not None:
            return True
        # 浼樺厛浣跨敤鎵嬪姩閫夋嫨鐨勬ā鍨嬭矾寰?
        model_path = self._yolo_model_path
        if not model_path or not os.path.exists(model_path):
            model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best.onnx")
        if not os.path.exists(model_path):
            model_path = "best.onnx"
        if not os.path.exists(model_path):
            print("[YOLO] 鏈壘鍒版ā鍨嬫枃浠讹紝璇风偣鍑?鎬墿鏁版嵁'閫夋嫨.onnx妯″瀷")
            return False
        try:
            self._yolo_net = cv2.dnn.readNetFromONNX(model_path)
            self._yolo_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            print("[YOLO] 妯″瀷鍔犺浇鎴愬姛:", model_path)
            return True
        except Exception as e:
            print("[YOLO] 鍔犺浇澶辫触:", e)
            return False

    def _detect_monsters(self, frame):
        """YOLO妫€娴嬫€墿锛岃繑鍥?[(x1,y1,x2,y2,score), ...]"""
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
                # 澶у皬杩囨护锛氭€€氬父瀹?0-110锛岄珮40-140锛屽お澶х殑鏄缓绛戣妫€
                if 20 <= bw <= 130 and 30 <= bh <= 160:
                    detections.append((x1, y1, x2, y2, float(score)))
        # NMS鍘婚噸
        if detections:
            boxes = [[d[0], d[1], d[2]-d[0], d[3]-d[1]] for d in detections]
            scores = [d[4] for d in detections]
            indices = cv2.dnn.NMSBoxes(boxes, scores, self._yolo_conf, self._yolo_nms)
            detections = [detections[i] for i in indices] if len(indices) > 0 else []
        return detections

    def _detect_monster_hp_bars(self, frame, search_areas=None):
        """妫€娴嬫€墿澶撮《琛€鏉★紝杩斿洖 [(x, y, w, h), ...]
        search_areas: 闄愬畾鎼滅储鍖哄煙 [(x1,y1,x2,y2),...]锛孨one鍒欏叏灞忔悳绱?
        鐢ㄤ簬杩戞垬浜虹墿鎸′綇鎬墿韬綋鏃讹紝鍑鏉″畾浣嶆€墿"""
        if frame is None:
            return []
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        # 鎬墿琛€鏉￠鑹诧紙鏍锋湰鍙栬壊锛氱豢鑹蹭负涓?H:35-80 S:90-255 V:80-255锛?
        m_g = cv2.inRange(hsv, np.array([35, 90, 80]), np.array([80, 255, 255]))
        # 绾㈣壊锛堜綆琛€閲忔椂鍙兘鍙樼孩锛屼繚鐣欏吋瀹癸級
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
                # 琛€鏉＄壒寰侊細瀹?楂?2锛屽搴?5-80px锛岄珮搴?-8px
                if bw > bh * 2 and 15 <= bw <= 80 and 2 <= bh <= 8:
                    bars.append((sx1 + x, sy1 + y, bw, bh))
        # 鍘婚噸锛氫綅缃帴杩戠殑鍙繚鐣欎竴涓?
        if bars:
            filtered = []
            for b in sorted(bars, key=lambda x: x[2] * x[3], reverse=True):
                if not any(abs(b[0] - f[0]) < 25 and abs(b[1] - f[1]) < 12 for f in filtered):
                    filtered.append(b)
            bars = filtered
        return bars

    def _detect_damage_number(self, target_cx, target_cy):
        """銆愭ā鍧桝-闇€姹?銆戞娴嬬洰鏍囧ご椤朵笂鏂规槸鍚︽湁浼ゅ鏁板瓧锛堢孩鈫掗粍娓愬彉+榛戞弿杈癸級
        鐢ㄩ€旓細鏀诲嚮鎬墿鏃跺ご椤朵細椋樺嚭绾⑩啋榛勬笎鍙樼殑浼ゅ鏁板瓧(濡?22/484)锛屾湁鏁板瓧=鎬繕娲荤潃
        鍙傛暟锛歵arget_cx=鐩爣涓績X, target_cy=鐩爣鑴氬簳Y
        鍘熺悊锛?
          1. 浠嶻OLO璇嗗埆鐨勬€墿bbox涓壘鍒板搴旂洰鏍囷紝鍙栧ご椤秠1浣滃熀鍑嗭紙涓嶅悓鎬墿楂樺害涓嶅悓锛?
          2. 鍦ㄥご椤朵笂鏂?0px鍖哄煙鍐呮悳绱㈢孩鈫掗粍娓愬彉鑹?H:0-35, 楗卞拰搴︹墺70, 浜害鈮?0)
          3. 鍍忕礌鈮?5涓笖鏈夎繛閫氬尯鍩熲墺10鍍忕礌 鈫?鍒ゅ畾鏈変激瀹虫暟瀛?
        杩斿洖锛歍rue=鏈変激瀹虫暟瀛?鎬椿鐫€), False=娌℃湁"""
        # 姝ラ1锛氫粠宸叉娴嬫€墿鍒楄〃涓壘鍒扮鐩爣涓績鏈€杩戠殑鎬墿锛岃幏鍙栧叾澶撮《y1
        target_y1 = None
        best_d = 999
        for (x1, y1, x2, y2, _) in self._monsters:
            cx = (x1 + x2) // 2  # 鎬墿涓績X
            cy = y2               # 鎬墿鑴氬簳Y
            d = abs(cx - target_cx) + abs(cy - target_cy)  # 鏇煎搱椤胯窛绂?
            if d < best_d:
                best_d = d
                target_y1 = y1  # 璁板綍鎬墿澶撮《Y
        if target_y1 is None:
            return False  # 娌℃壘鍒板搴旀€墿锛屾棤娉曟娴?

        # 姝ラ2锛氭埅鍙栨父鎴忕敾闈紝鍦ㄧ洰鏍囧ご椤朵笂鏂瑰尯鍩熸悳绱?
        frame = self._capture_window()
        if frame is None:
            return False
        h, w = frame.shape[:2]
        # 鎼滅储鍖哄煙锛氬ご椤秠1涓婃柟60px锛屾按骞充腑蹇兟?5px锛堣鐩栦激瀹虫暟瀛楅鍔ㄨ寖鍥达級
        rx1 = max(0, target_cx - 45)
        rx2 = min(w, target_cx + 45)
        ry1 = max(0, target_y1 - 60)  # 澶撮《涓婃柟60px
        ry2 = min(h, target_y1 + 5)   # 鍖呭惈澶撮《浣嶇疆
        if rx2 <= rx1 or ry2 <= ry1:
            return False
        roi = frame[ry1:ry2, rx1:rx2]  # 鎴彇鎼滅储鍖哄煙

        # 姝ラ3锛欻SV棰滆壊绌洪棿妫€娴嬬孩鈫掗粍娓愬彉鑹?
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # H:0-35瑕嗙洊绾?0)銆佹(15)銆侀粍(30)锛涢ケ鍜屽害鈮?0鎺掗櫎鐏拌壊锛涗寒搴︹墺70鎺掗櫎鏆楄壊
        mask = cv2.inRange(hsv, np.array([0, 70, 70]), np.array([35, 255, 255]))
        if np.sum(mask > 0) < 25:
            return False  # 绾⑩啋榛勫儚绱犲お灏戯紝涓嶆槸浼ゅ鏁板瓧

        # 姝ラ4锛氳繛閫氬尯鍩熸娴嬶紝鎺掗櫎闆舵暎鍣偣
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            if cv2.contourArea(cnt) >= 10:  # 鏈夐潰绉墺10鐨勮繛閫氬尯鍩?鏁板瓧
                return True
        return False

    def _get_player_screen_pos(self, frame):
        """鑾峰彇浜虹墿鍦ㄦ父鎴忕敾闈腑鐨勫潗鏍囷紙澶嶇敤_match_character鍐呭瓨妯℃澘+X/Y鍋忕Щ锛?
        鍖归厤澶辫触鏃讹細1.5绉掑闄愭湡鍐呯敤涓婃鎴愬姛浣嶇疆锛岃秴杩囨墠杩斿洖None"""
        match = self._match_character(frame)
        if match:
            mx, my, _ = match
            x_off = int(self._field_values.get("char_x_offset", "0") or "0")
            y_off = int(self._field_values.get("char_y_offset", "0") or "0")
            return (mx + x_off, my + y_off)
        # 鍖归厤澶辫触锛?.5绉掑闄愭湡鍐呯敤涓婃鎴愬姛浣嶇疆锛堟垬鏂椾腑鐭殏涓㈡ā鏉夸笉绔嬪嵆鍋滄墜锛?
        last_pos = getattr(self, '_last_char_match_pos', None)
        last_time = getattr(self, '_last_char_match_time', 0)
        now_ms = time.time() * 1000
        if last_pos and now_ms - last_time < 1500:
            mx, my = last_pos
            x_off = int(self._field_values.get("char_x_offset", "0") or "0")
            y_off = int(self._field_values.get("char_y_offset", "0") or "0")
            if not hasattr(self, '_last_grace_log') or now_ms - self._last_grace_log > 1000:
                self._last_grace_log = now_ms
                _debug_log("[浜虹墿瀹氫綅] 瀹介檺鏈熶娇鐢ㄤ笂娆′綅缃?(%d,%d) 涓㈠け%.0fms" % (mx + x_off, my + y_off, now_ms - last_time))
            return (mx + x_off, my + y_off)
        # 瓒呰繃瀹介檺鏈燂細杩斿洖None
        _now = time.time()
        if not hasattr(self, '_last_posfail_log') or _now - self._last_posfail_log > 5:
            self._last_posfail_log = _now
            _debug_log("[浜虹墿瀹氫綅] 鏈尮閰嶅埌瑙掕壊锛堟ā鏉?d濂楋紝闃堝€?.2f锛夛紝瀹介檺鏈熷凡杩? % (len(self._char_templates), CHAR_MATCH_THRESHOLD))
        return None

    def _draw_monster_overlay(self, frame, player_pos):
        """鍦ㄦ父鎴忕敾闈笂鐢绘€墿妗嗐€佷汉鐗╀綅缃€佽繛绾裤€佽窛绂汇€佸亸绉讳俊鎭紙璋冭瘯鐢紝宸茬敱閫忔槑钂欐澘鍙栦唬锛?""
        disp = frame.copy()
        px, py = player_pos
        x_off = int(self._field_values.get("char_x_offset", "0") or "0")
        y_off = int(self._field_values.get("char_y_offset", "0") or "0")
        # 浜虹墿鍙傝€冪偣锛堥粍鑹插疄蹇冨渾锛?
        cv2.circle(disp, (px, py), 6, (0, 255, 255), -1)
        cv2.circle(disp, (px, py), 9, (0, 255, 255), 1)
        cv2.putText(disp, "PLAYER(%d,%d) X%+d Y%+d" % (px, py, x_off, y_off),
                    (px + 12, py - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        # 鎬墿妗?+ 杩炵嚎 + 璺濈
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
        # 宸︿笂瑙掔姸鎬佹爮
        cv2.putText(disp, "Monsters:%d  Offset X:%d Y:%d" % (len(self._monsters), x_off, y_off),
                    (5, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        return disp

    def _is_mp_label_visible(self, frame):
        """妯℃澘鍖归厤妫€娴婱P鏍囩鏄惁鍙锛堝叏绐楀彛妫€娴嬪師鍥撅級銆?
        鍙=True => 娌¤閬尅锛屽彲浠ュ悆鑽?
        涓嶅彲瑙?False => 琚尅浣忥紝璺宠繃鍚冭嵂"""
        if self._mp_label_template is None or frame is None:
            return True  # 鏃犳ā鏉挎椂涓嶆嫤鎴?
        th, tw = self._mp_label_template.shape[:2]
        h, w = frame.shape[:2]
        if h < th or w < tw:
            return True
        # 鍏ㄧ獥鍙ｇ洿鎺ユ娴嬪師鍥撅紝涓嶅仛ROI瑁佸壀
        result = cv2.matchTemplate(frame, self._mp_label_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        visible = max_val >= 0.35
        if not visible:
            _debug_log("[MP閬尅] 鍏ㄧ獥鍙ｅ尮閰嶅害%.3f<0.35, 鍒ゅ畾琚伄鎸? % max_val)
        return visible

    def _check_auto_potion(self):
        """鑷姩鍚冭嵂妫€娴嬶細HP/MP浣庝簬璁惧畾鐧惧垎姣旀椂鎸夐敭锛屽甫鍐峰嵈鍜岄殢鏈鸿宸?""
        if self.hwnd is None:
            return
        now = time.time() * 1000
        # 鍚姩鍚?绉掑唴涓嶆娴嬪悆鑽紙閬垮厤绐楀彛鍒氬姞杞芥埅鍥句笉鍑嗗鑷磋鍔犺摑锛?
        if not hasattr(self, '_pot_start_time'):
            self._pot_start_time = now
        if now - self._pot_start_time < 3000:
            return
        # 姣?00ms妫€娴嬩竴娆★紝閬垮厤澶绻?
        if now - self._last_pot_check < 500:
            return
        self._last_pot_check = now

        cfg = self._get_potion_config()

        frame = self._capture_window()
        if frame is None:
            return

        # 鑷姩妫€娴嬭鏉★紙姣忓抚閮芥娴嬶紝閫傚簲绐楀彛绉诲姩锛?
        hp_bar, mp_bar = self._detect_hp_mp_bars(frame)
        if hp_bar:
            self._hp_bar = hp_bar
        if mp_bar:
            self._mp_bar = mp_bar

        # 妫€娴婬P/MP涓婇檺锛堟瘡3绉掍竴娆★紝鐢ㄤ簬杈撳叆鏍￠獙锛屼笉褰卞搷鍚冭嵂閫昏緫锛?
        self._detect_hp_mp_max(frame)

        # 閬尅鍒ゅ畾锛氭父鎴忕獥鍙ｄ笉鍦ㄥ墠鍙帮紙琚叾浠栫獥鍙ｆ尅浣?鏈€灏忓寲锛夋椂璺宠繃鍚冭嵂
        import ctypes
        fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
        occluded = (fg_hwnd != self.hwnd)
        hp_thresh = min(int(self._field_values.get("hp_value", "30") or "30"), 100)
        mp_thresh = min(int(self._field_values.get("mp_value", "30") or "30"), 100)

        if occluded:
            # 姣?绉掓彁绀轰竴娆★紝閬垮厤鍒峰睆
            if now - getattr(self, '_last_occluded_log', 0) > 2000:
                self._last_occluded_log = now
                self._rlog("琛€鏉¤閬尅锛屾殏涓嶈嚜鍔ㄥ姞琛€鍔犺摑", (200, 100, 0))
                print("[鍚冭嵂] MP鏍囩琚伄鎸★紝璺宠繃鍚冭嵂")
        elif getattr(self, '_was_occluded', False):
            # 閬尅瑙ｉ櫎鏃舵彁绀轰竴娆?
            self._rlog("閬尅瑙ｉ櫎锛屾仮澶嶈嚜鍔ㄥ悆鑽?, (0, 180, 0))
        self._was_occluded = occluded

        if not occluded:
            # HP妫€娴?鈥?灏忕珫妗嗗唴娌＄孩鑹?浣庝簬闃堝€?鍚冪孩
            hp_blank = self._is_bar_blank_at(frame, self._hp_bar, hp_thresh, "hp")
            _debug_log("HP妫€娴? blank=%s thresh=%d key=%s bar=%s" % (hp_blank, hp_thresh, cfg.get("hp_key"), self._hp_bar))
            if hp_blank and cfg.get("hp_key"):
                if self._hp_pot_wait_until == 0:
                    self._hp_pot_wait_until = now + random.randint(0, 500)  # 瑙﹀彂鍚庣瓑寰呭欢鏃?-500ms
                if now >= self._hp_pot_wait_until and now - self._last_hp_pot > self._hp_pot_delay:
                    self._press_game_key(cfg["hp_key"])
                    self._last_hp_pot = now
                    self._hp_pot_delay = random.randint(800, 1000)  # 鍚冭嵂鍚庡喎鍗村欢鏃?00-1000ms
                    self._hp_pot_wait_until = 0
                    self._rlog("鍔犺 %s" % cfg["hp_key"], (0, 0, 200))
                    print("[鑷姩鍚冭嵂] HP浣庝簬%d%%, 鎸?%s" % (hp_thresh, cfg["hp_key"]))
            else:
                self._hp_pot_wait_until = 0

            # MP妫€娴?鈥?灏忕珫妗嗗唴娌¤摑鑹?浣庝簬闃堝€?鍚冭摑
            mp_blank = self._is_bar_blank_at(frame, self._mp_bar, mp_thresh, "mp")
            _debug_log("MP妫€娴? blank=%s thresh=%d key=%s bar=%s" % (mp_blank, mp_thresh, cfg.get("mp_key"), self._mp_bar))
            if mp_blank and cfg.get("mp_key"):
                if self._mp_pot_wait_until == 0:
                    self._mp_pot_wait_until = now + random.randint(0, 500)  # 瑙﹀彂鍚庣瓑寰呭欢鏃?-500ms
                if now >= self._mp_pot_wait_until and now - self._last_mp_pot > self._mp_pot_delay:
                    self._press_game_key(cfg["mp_key"])
                    self._last_mp_pot = now
                    self._mp_pot_delay = random.randint(800, 1000)  # 鍚冭嵂鍚庡喎鍗村欢鏃?00-1000ms
                    self._mp_pot_wait_until = 0
                    self._rlog("鍔犺摑 %s" % cfg["mp_key"], (200, 100, 0))
                    print("[鑷姩鍚冭嵂] MP浣庝簬%d%%, 鎸?%s" % (mp_thresh, cfg["mp_key"]))
            else:
                self._mp_pot_wait_until = 0

            # 鍚冭嵂璇婃柇鏃ュ織锛堟瘡绉掍竴娆★紝鏃犳潯浠惰緭鍑猴紝渚夸簬鎺掓煡锛?
            if now - getattr(self, '_last_pot_diag_log', 0) > 1000:
                self._last_pot_diag_log = now
                hp_info = "鏃犳潯" if not self._hp_bar else "x=%d,w=%d" % (self._hp_bar[0], self._hp_bar[2])
                mp_info = "鏃犳潯" if not self._mp_bar else "x=%d,w=%d" % (self._mp_bar[0], self._mp_bar[2])
                overlay = "寮€" if self._monster_overlay_running else "鍏?
                mp_tpl = "鏃? if self._mp_label_template is None else "%dx%d" % self._mp_label_template.shape[:2]
                print("[鍚冭嵂璇婃柇] 钂欐澘=%s 閬尅=%s MP妯℃澘=%s HP鏉?%s HP绌?%s MP鏉?%s MP绌?%s" % (
                    overlay, occluded, mp_tpl, hp_info, hp_blank, mp_info, mp_blank))

        # 瀹犵墿椋熷搧 鈥?鎸夊喎鍗村懆鏈熻嚜鍔ㄥ杺锛堜笉鍙楄繍琛岀姸鎬佹帶鍒讹紝涓嶅彈閬尅褰卞搷锛岃剼鏈紑浜嗗氨鐢熸晥锛?
        pet_key = cfg.get("pet_key", "")
        pet_cd = cfg.get("pet_cd", 0)
        if pet_key and pet_cd > 0:
            last = self._potion_last.get("pet", 0)
            if now - last > pet_cd:
                self._press_game_key(pet_key)
                self._potion_last["pet"] = now
                self._rlog("瀹犵墿椋?%s" % pet_key, (0, 200, 0))
                print("[瀹犵墿椋焆 %s 閲婃斁" % pet_key)

        # 灏嗚鏉?钃濇潯妫€娴嬬偣浼犵粰缁熶竴閫忔槑钂欐澘鏄剧ず
        if self._monster_overlay_running:
            if self._monster_overlay_data is None:
                self._monster_overlay_data = {}
            # 淇濈暀宸叉湁瀛楁锛坈har_pos/monsters/blink_until锛?
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
        """鎸佺画鎸変綇涓€涓敭锛堝鏋滄病鎸変綇鐨勮瘽锛?""
        if vk not in self._combat_held_keys:
            scan = user32.MapVirtualKeyW(vk, 0)
            ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
            user32.keybd_event(vk, scan, ext, 0)
            self._combat_held_keys.add(vk)

    def _release_combat_key(self, vk):
        """閲婃斁涓€涓寔缁寜浣忕殑閿?""
        if vk in self._combat_held_keys:
            scan = user32.MapVirtualKeyW(vk, 0)
            ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
            user32.keybd_event(vk, scan, ext | 0x0002, 0)
            self._combat_held_keys.discard(vk)

    def _release_combat_move(self):
        """閲婃斁鎵€鏈夋寔缁寜浣忕殑绉诲姩閿?""
        for vk in list(self._combat_held_keys):
            self._release_combat_key(vk)
        self._combat_move_dir = None

    def _set_combat_move(self, direction):
        """璁剧疆鎸佺画绉诲姩鏂瑰悜锛宒irection='left'/'right'/None銆傛祦鐣呭垏鎹笉鍗￠】銆?""
        if direction == self._combat_move_dir:
            return
        # 鍏堟澗寮€鎵€鏈夋柟鍚戦敭
        self._release_combat_key(VK_LEFT)
        self._release_combat_key(VK_RIGHT)
        # 鎸夋柊鏂瑰悜
        if direction == "left":
            self._hold_combat_key(VK_LEFT)
        elif direction == "right":
            self._hold_combat_key(VK_RIGHT)
        self._combat_move_dir = direction

    def _get_current_platform(self):
        """鏍规嵁灏忓湴鍥剧帺瀹跺潗鏍囧垽鏂綋鍓嶅湪鍝釜骞冲彴涓婏紙鐐瑰埌鎶樼嚎鏈€杩戣窛绂烩墹10锛夈€?""
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
        """杩囨护鍑哄拰鐜╁鍚屼竴骞冲彴鐨勬€紙鎬敤鑴歒锛屼汉鐢ㄦ墜Y锛屽悓骞冲彴宸害30-50px锛?""
        if not player_screen_pos or not monsters:
            return monsters
        _, py = player_screen_pos
        same_platform = []
        for m in monsters:
            x1, y1, x2, y2, score = m
            if abs(y2 - py) <= 50:  # 鎬剼 vs 浜烘墜
                same_platform.append(m)
        return same_platform

    def _is_monster_on_platform(self, monster_cx, monster_cy):
        """鍒ゆ柇鎬槸鍚﹀湪鐜╁褰撳墠骞冲彴涓婏紙宸叉帴鍏ユ柊鐨刜get_monster_platform閫昏緫锛?
        1. 鏈夊钩鍙版暟鎹細鐢ㄦ柊鍑芥暟鍒ゅ畾鎬湪鍝釜骞冲彴锛屽拰浜虹墿褰撳墠骞冲彴ID姣旇緝
        2. 鏃犲钩鍙版暟鎹細鍥為€€鍒板睆骞晊宸垽鏂紙鎬剼vs浜烘墜鈮?0锛?""
        # 璋冪敤鏂板嚱鏁帮細鎬睆骞曞潗鏍?鈫?浼扮畻灏忓湴鍥惧潗鏍?鈫?鍒扮豢绾胯窛绂绘渶灏忕殑骞冲彴
        monster_pf = self._get_monster_platform(monster_cx, monster_cy)
        player_pf = self._get_current_platform()
        if monster_pf and player_pf:
            # 骞冲彴ID鐩稿悓 = 鍚屽钩鍙?
            return monster_pf.get('id') == player_pf.get('id')
        # 鏃犲钩鍙版暟鎹椂鍥為€€鍒板睆骞晊宸垽鏂紙鍏煎鏃х増鏈級
        if self._player_screen_pos:
            return abs(monster_cy - self._player_screen_pos[1]) <= 50
        return False

    def _combat_tick(self):
        """浜烘€у寲鎴樻枟锛氬弽搴斿欢杩熲啋杞韩鈫掕蛋浣嶁啋鏀诲嚮锛岀兢鏀?鍙捣锛屽甫闅忔満瀹归敊"""
        if not self._running or self.hwnd is None:
            return
        now = time.time() * 1000
        fight_cfg = self._get_fight_config()
        pot_cfg = self._get_potion_config()

        # === 銆愭ā鍧桞銆戞墜鍔ㄥ綍鍒跺钩鍙拌竟鐣屾娴?+ 鍥為€€ ===
        # 浜虹墿鍒颁簡骞冲彴杈圭紭锛屼笉绠″湪鎵撴€繕鏄仛浠€涔堬紝閮藉洖閫€骞冲彴瀹藉害鐨?0%
        # 鍥為€€瀹屾垚鍚庣户缁甯告墦鎬?
        boundary_dir = self._check_platform_boundary()
        if boundary_dir and not getattr(self, '_platform_retreat_active', False):
            # 瑙﹀彂鍥為€€锛氳绠楀洖閫€鐩爣锛堝钩鍙板搴︾殑20%锛?
            pf = self._get_current_manual_platform()
            if pf and self._player_map_pos:
                x_min, x_max = self._platform_x_range(pf)
                platform_width = x_max - x_min
                retreat_dist = platform_width * 0.2  # 鍥為€€骞冲彴瀹藉害鐨?0%
                px = self._player_map_pos[0]
                if boundary_dir == 'right':
                    # 瓒呭嚭宸﹁竟鐣岋紝寰€鍙冲洖閫€
                    self._platform_retreat_target_x = px + retreat_dist
                    self._platform_retreat_dir = 'right'
                else:
                    # 瓒呭嚭鍙宠竟鐣岋紝寰€宸﹀洖閫€
                    self._platform_retreat_target_x = px - retreat_dist
                    self._platform_retreat_dir = 'left'
                self._platform_retreat_active = True
                self._release_combat_move()  # 閲婃斁褰撳墠绉诲姩閿?
                _debug_log("[骞冲彴杈圭晫] 瑙﹀彂鍥為€€ 鏂瑰悜=%s 鐩爣X=%.1f 鍥為€€璺濈=%.1f" % (
                    boundary_dir, self._platform_retreat_target_x, retreat_dist))
        # 鍥為€€杩囩▼涓細鎸変綇鏂瑰悜閿線鍥炶蛋锛屼笉鏀诲嚮
        if getattr(self, '_platform_retreat_active', False) and self._player_map_pos:
            px = self._player_map_pos[0]
            target = self._platform_retreat_target_x
            rdir = self._platform_retreat_dir
            reached = (rdir == 'right' and px >= target) or (rdir == 'left' and px <= target)
            if reached:
                # 鍒拌揪鍥為€€鐩爣锛屾仮澶嶆甯?
                self._platform_retreat_active = False
                self._release_combat_move()
                _debug_log("[骞冲彴杈圭晫] 鍥為€€瀹屾垚 鍒拌揪X=%.1f" % px)
            else:
                # 缁х画鍥為€€锛氭寜浣忔柟鍚戦敭
                self._set_combat_move(rdir)
                return  # 鍥為€€杩囩▼涓笉鏀诲嚮锛岀洿鎺ヨ繑鍥?

        # === 閲婃斁鍒版湡鐨勫畾鏃舵寜閿紙璧颁綅鐢紝涓嶉樆濉炰富寰幆锛?==
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

        # === YOLO鎬墿妫€娴?+ 琛€鏉℃娴嬶紙姣?0ms涓€娆★紝鍙屾娴嬪悎骞讹級===
        if now - self._last_yolo_check > 20:
            self._last_yolo_check = now
            frame = self._capture_window()
            if frame is not None:
                yolo_monsters = self._detect_monsters(frame)
                self._player_screen_pos = self._get_player_screen_pos(frame)
                _has_pos = self._player_screen_pos is not None
                if _has_pos != getattr(self, '_last_player_pos_ok', None):
                    self._last_player_pos_ok = _has_pos
                    if _has_pos:
                        _debug_log("[浜虹墿瀹氫綅] 鎴愬姛锛岄粍鐐逛綅缃? %s" % (self._player_screen_pos,))
                    else:
                        _debug_log("[浜虹墿瀹氫綅] 涓㈠け锛岄粍鐐归殣钘?)

                # 琛€鏉℃悳绱㈠尯鍩燂細YOLO妫€娴嬪埌鐨勬€ご椤?+ 涓婁竴娆℃敾鍑荤洰鏍囧ご椤讹紙杩戞垬鎸¤韩浣撴椂YOLO妫€娴嬩笉鍒颁絾琛€鏉¤繕鍦級
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

                # 琛€鏉′綅缃浆鎬墿鍧愭爣锛堣鏉℃涓嬫柟灏辨槸鎬殑浣嶇疆锛?
                hp_monsters = []
                for (bx, by, bw, bh) in self._monster_hp_bars:
                    hp_monsters.append((bx, by+bh+5, bx+bw, by+bh+55, 0.4))

                # YOLO缁撴灉鎸夌疆淇″害杩囨护锛堜綆缃俊搴?鍩庨噷寤虹瓚璇锛?
                conf_thresh = getattr(self, '_yolo_conf_thresh', 0.5)
                filtered_yolo = [m for m in yolo_monsters if m[4] >= conf_thresh]

                # 鍚堝苟鍘婚噸锛歒OLO缁撴灉 + 琛€鏉″崟鐙娴嬬殑鎬?
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
                    self._rlog("鍙戠幇鎬墿%d鍙?YOLO%d+琛€鏉?d,闃堝€?.1f)" % (
                        _mc, len(filtered_yolo), len(hp_monsters), conf_thresh), (0, 100, 200))
                    self._last_logged_mc = _mc
                elif _mc == 0:
                    self._last_logged_mc = 0

        # === 鍙嶅簲寤惰繜 / 杞韩 閿佸畾锛堝悗鎽囬攣宸插幓鎺夛紝杩炵画鏀诲嚮锛?==
        if now < self._combat_react_until:
            return
        if now < self._combat_turn_until:
            return
        if now < self._combat_busy_until:
            return

        # === 涓嶈繃婊ゆ€墿锛氫繚鐣欐墍鏈夋娴嬪埌鐨勬€紝鐩爣閫夋嫨鏃跺悓骞冲彴浼樺厛 ===
        current_platform = self._get_current_platform()
        has_target = bool(self._monsters and self._player_screen_pos)

        # === 瀹屽叏鏃犵洰鏍囷紙涓€鍙€兘娌℃娴嬪埌锛夛細鏉惧紑绉诲姩锛岀敱璺嚎绯荤粺鎺ョ ===
        if not has_target:
            self._combat_had_target = False
            self._combat_target_idx = 0
            self._combat_last_target_pos = None
            self._combat_locked_target = None
            # 銆愭ā鍧桝銆戞棤鎬椂閲嶇疆鎵€鏈夋垬鏂楃姸鎬侊紝鎭㈠宸¤矾
            self._combat_active = False          # 鍙栨秷鎴樻枟娲昏穬锛屽贰璺仮澶嶇Щ鍔?
            self._combat_range_clear = False     # 閫€鍑鸿寖鍥存竻鎬ā寮?
            self._combat_target_lock_x = None    # 娓呴櫎閿佸畾X鍩哄噯
            self._combat_target_alive = False    # 娓呴櫎瀛樻椿鐘舵€?
            self._release_combat_move()
            return

        # === 鏈夌洰鏍囷紙褰撳墠骞冲彴涓婃湁鎬級===
        px, py = self._player_screen_pos

        # 棣栨鍙戠幇鐩爣锛氬弽搴斿欢杩?
        if not self._combat_had_target:
            self._combat_had_target = True
            self._combat_react_until = now + random.randint(80, 250)
            return

        # 璁＄畻鎬墿璺濈骞舵帓搴忥紙鍚屽钩鍙颁紭鍏堬紝璺濈鐩歌繎鏃跺乏杈瑰厛鎵擄級
        # 鎬殑Y鐢╞box搴曢儴锛堣剼鐨勪綅缃級锛屽拰浜虹墿鐐癸紙鎵嬬殑浣嶇疆锛夊熀鍑嗗榻?
        # 銆愭ā鍧桞銆戞墜鍔ㄥ綍鍒跺钩鍙癤鑼冨洿杩囨护锛氭湁鎵嬪姩褰曞埗骞冲彴鏃跺彧鎵揦鑼冨洿鍐呯殑鎬?
        # 銆愭ā鍧桞銆戝钩鍙伴€夋嫨杩囨护锛氬彧鎵撻€変腑骞冲彴涓婄殑鎬紙绌哄垪琛?鍏ㄩ儴骞冲彴锛?
        has_manual_pf = self._get_current_manual_platform() is not None
        has_platform_select = len(self._selected_platforms) > 0
        monster_dists = []
        for (x1, y1, x2, y2, score) in self._monsters:
            cx = (x1 + x2) // 2
            cy = y2  # 鑴氱殑浣嶇疆
            # 鏈夋墜鍔ㄥ綍鍒跺钩鍙版椂锛屽彧鎵揦鑼冨洿鍐呯殑鎬?
            if has_manual_pf and not self._is_monster_in_manual_platform(cx, cy):
                continue
            # 骞冲彴閫夋嫨杩囨护锛氬彧鎵撻€変腑骞冲彴涓婄殑鎬?
            if has_platform_select:
                monster_pf = self._get_monster_platform(cx, cy)
                if monster_pf:
                    pf_num = monster_pf.get('id', 0) + 1  # 缂栧彿浠?寮€濮?
                    if pf_num not in self._selected_platforms:
                        continue
                else:
                    # 鎬笉鍦ㄤ换浣曞綍鍒跺钩鍙颁笂锛屼笉鎵?
                    continue
            dist = int(np.sqrt((cx - px) ** 2 + (cy - py) ** 2))
            same_platform = self._is_monster_on_platform(cx, cy)
            # 璺濈20px涓轰竴妗ｏ紝鍚屾。鍐呮寜cx鍗囧簭锛堝乏杈瑰厛鎵擄級锛岄伩鍏嶅乏鍙虫檭鍔?
            dist_bucket = dist // 20
            monster_dists.append((0 if same_platform else 1, dist_bucket, cx, dist, cy))
        monster_dists.sort()
        # 鍚屽钩鍙版湁鎬墠鎵擄紝娌℃湁灏遍噴鏀剧Щ鍔ㄧ瓑璺嚎绯荤粺鍒囨崲骞冲彴
        if monster_dists[0][0] != 0:
            self._release_combat_move()
            self._combat_locked_target = None
            # 銆愭ā鍧桝銆戝悓骞冲彴鏃犳€紝閲嶇疆鎴樻枟鐘舵€?
            self._combat_active = False
            self._combat_range_clear = False
            return
        monster_dists = [(d, cx, cy) for (prio, db, cx, d, cy) in monster_dists if prio == 0]

        # === 銆愭ā鍧桝銆戞妧鑳借寖鍥村唴娓呮€ā寮忥紙绾閲忥細鑼冨洿鍐呮湁鎬紭鍏堟墦锛屼笉鏀瑰彉杩滃绉诲姩閫昏緫锛?==
        # 鍘熺悊锛氭妧鑳芥敾鍑昏窛绂?榛樿150px)鍐呯殑鎬紭鍏堝叏閮ㄦ墦瀹岋紝鎵撳畬涓€鍙帴涓嬩竴鍙紝鍏ㄩ儴娓呭畬鎵嶈蛋
        atk_dist = fight_cfg.get("atk1_distance", 150)  # 璇诲彇閰嶇疆鐨勬敾鍑昏窛绂?
        in_range = [(d, cx, cy) for d, cx, cy in monster_dists if d <= atk_dist]  # 绛涢€夎寖鍥村唴鐨勬€?
        if in_range:
            # 鑼冨洿鍐呮湁鎬細杩涘叆娓呮€ā寮忥紝鍙€冭檻鑼冨洿鍐呯殑鎬?
            if not self._combat_range_clear:
                self._combat_range_clear = True  # 鏍囪杩涘叆鑼冨洿娓呮€ā寮?
                _debug_log("[鎵撴€猐 杩涘叆鎶€鑳借寖鍥存竻鎬ā寮忥紝鑼冨洿鍐?d鍙€? % len(in_range))
            self._combat_active = True  # 鎴樻枟娲昏穬锛屾殏鍋滃贰璺Щ鍔?
            monster_dists = in_range  # 鍙墦鑼冨洿鍐呯殑鎬紝鎵撳畬涓€鍙嚜鍔ㄩ€変笅涓€鍙?
        else:
            # 鑼冨洿鍐呮棤鎬細缁撴潫娓呮€ā寮忥紝浣嗕笉return锛岀户缁師鏈夎繙澶勭Щ鍔ㄩ€昏緫锛堢函澧為噺涓嶆敼鍙樻棫琛屼负锛?
            if self._combat_range_clear:
                self._combat_range_clear = False
                _debug_log("[鎵撴€猐 鎶€鑳借寖鍥村唴宸叉竻瀹岋紝缁х画鍘熸湁绉诲姩閫昏緫")
            self._combat_active = False  # 鍙栨秷鎴樻枟娲昏穬锛屽贰璺彲绉诲姩

        # === 鐩爣閿佸畾瑙勫垯锛氶攣涓€鍙墦姝诲啀鎹紝涓嶄腑閫斿垏鎹?===
        target = None
        if self._combat_locked_target:
            lcx, lcy = self._combat_locked_target
            # 閿佸畾鐩爣杩樺湪妫€娴嬪垪琛ㄤ腑锛堜綅缃帴杩戯級灏辩户缁墦
            for d, cx, cy in monster_dists:
                if abs(cx - lcx) <= 40 and abs(cy - lcy) <= 50:
                    target = (d, cx, cy)
                    break
            if target is None:
                # 閿佸畾鐩爣娑堝け浜嗭紙鎬浜嗭級锛岃В閿侀€変笅涓€鍙?
                self._combat_locked_target = None
                _debug_log("[鎵撴€猐 閿佸畾鐩爣宸叉秷澶憋紝閫変笅涓€鍙?)

        if target is None:
            # 閫夊綋鍓嶅钩鍙颁笂鏈€杩戠殑鎬綔涓烘柊閿佸畾鐩爣
            target = monster_dists[0]
            self._combat_locked_target = (target[1], target[2])
            self._combat_target_hp_confirmed = False  # 鏂扮洰鏍囬噸缃鏉＄‘璁ょ姸鎬?
            # 銆愭ā鍧桝-闇€姹?0銆戣褰曟柊鐩爣鐨勯娆鍜岄攣瀹氭椂闂达紝鐢ㄤ簬1绉掓棤鍙樺寲妫€娴?
            self._combat_target_lock_x = target[1]    # 璁板綍閿佸畾鏃剁洰鏍囩殑X鍧愭爣
            self._combat_target_lock_time = now         # 璁板綍閿佸畾鏃堕棿(姣)
            self._combat_target_alive = False           # 鏂扮洰鏍囧瓨娲荤姸鎬佸緟纭
            _debug_log("[鎵撴€猐 閿佸畾鏂扮洰鏍? 璺濈%dpx 浣嶇疆(%d,%d)" % (
                target[0], target[1], target[2]))

        t_dist, t_cx, t_cy = target
        # 鏇存柊閿佸畾浣嶇疆锛堟€細绉诲姩锛?
        self._combat_locked_target = (t_cx, t_cy)
        # 璁板綍鐩爣浣嶇疆锛岀敤浜庝笅涓€杞鏉℃悳绱?
        self._combat_last_target_pos = (t_cx, t_cy)

        # === 銆愭ā鍧桝-闇€姹?0銆?绉扻鏃犲彉鍖栨娴嬶細鎬?绉掑唴X娌″彉鍖栤啋鏀惧純閿佸畾锛堝彲鑳芥槸姝绘€?寤虹瓚璇锛?==
        # 鍘熺悊锛氱湡鎬細宸﹀彸绉诲姩锛屽缓绛?鐭冲ご涓嶄細鍔ㄣ€傞攣瀹?绉掑悗X鍙樺寲<5px灏卞垽瀹氫负鍋囩洰鏍?
        if self._combat_target_lock_x is not None and now - self._combat_target_lock_time > 1000:
            x_change = abs(t_cx - self._combat_target_lock_x)  # 璁＄畻1绉掑唴X鍙樺寲閲?
            if x_change < 5:
                # X鍙樺寲<5px锛屽垽瀹氫负鍋囩洰鏍囷紙寤虹瓚/姝绘€級锛屾斁寮冮攣瀹氶€変笅涓€鍙?
                _debug_log("[鎵撴€猐 鐩爣1绉扻鏃犲彉鍖?鍙樺寲%dpx<5)锛屾斁寮冮攣瀹? % x_change)
                self._combat_locked_target = None   # 娓呴櫎閿佸畾
                self._combat_target_lock_x = None    # 娓呴櫎X鍩哄噯
                self._combat_target_alive = False    # 娓呴櫎瀛樻椿鐘舵€?
                return  # 鐩存帴杩斿洖锛屼笅涓€甯ч噸鏂伴€夌洰鏍?
            else:
                # X鏈夊彉鍖栵紝鏇存柊鍩哄噯鏃堕棿鍜孹锛岀户缁洃娴?
                self._combat_target_lock_x = t_cx
                self._combat_target_lock_time = now

        # === 銆愭ā鍧桝-闇€姹?銆戞€墿瀛樻椿妫€娴嬶細琛€鏉?OR 浼ゅ鏁板瓧锛屽嚭鐜颁竴绉嶅氨璇存槑鎬繕鍦?===
        # 鍘熺悊锛氭€鏀诲嚮鏃跺ご椤朵細鍑虹幇缁胯壊琛€鏉″拰绾⑩啋榛勬笎鍙樼殑浼ゅ鏁板瓧锛屼换鎰忎竴绉嶅嚭鐜?鎬湭姝?
        target_has_hp = False  # 鏍囪鏄惁妫€娴嬪埌琛€鏉?
        for (bx, by, bw, bh) in self._monster_hp_bars:
            bcx = bx + bw // 2  # 琛€鏉′腑蹇僗
            bcy = by + bh // 2  # 琛€鏉′腑蹇僘
            if abs(bcx - t_cx) < 55 and abs(bcy - t_cy) < 65:
                target_has_hp = True  # 鐩爣闄勮繎鏈夎鏉?
                break
        # 浼ゅ鏁板瓧妫€娴嬶細鐩爣澶撮《涓婃柟鏈夌孩鈫掗粍娓愬彉鍍忕礌鑱氶泦锛堟敾鍑诲悗鐭殏鍑虹幇锛?
        target_has_dmg = self._detect_damage_number(t_cx, t_cy)
        # 琛€鏉?OR 浼ゅ鏁板瓧锛屼换鎰忎竴绉?鎬繕娲荤潃
        self._combat_target_alive = target_has_hp or target_has_dmg
        # 鏀诲嚮鎴愬姛纭锛氶娆℃娴嬪埌琛€鏉?鏀诲嚮鍛戒腑
        if target_has_hp and not getattr(self, '_combat_target_hp_confirmed', False):
            self._combat_target_hp_confirmed = True
            _debug_log("[鎵撴€猐 鏀诲嚮鎴愬姛纭锛氱洰鏍囪鏉″凡鍑虹幇 浣嶇疆(%d,%d)" % (t_cx, t_cy))
            self._rlog("鍛戒腑鐩爣(琛€鏉＄‘璁?", (0, 200, 0))

        # 闈㈠悜鍒ゆ柇锛氭€湪鍙虫寜鍙抽敭锛屾€湪宸︽寜宸﹂敭
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

        # === 鏂滃潯妫€娴嬶細鐩爣Y宸?25px鍒ゅ畾涓哄湪鏂滃潯涓婏紝闇€瑕佽竟璧拌竟璺虫墠鑳芥墦鍒版€?===
        y_diff = abs(t_cy - py)
        on_slope = y_diff > 25
        jump_key = fight_cfg.get("jump_key", "")

        # === 杩滃鎬湞鎬Щ鍔ㄩ潬杩?===
        atk_dist = fight_cfg.get("atk1_distance", 150)
        aoe_dist = fight_cfg.get("aoe_distance", 200)
        effective_range = max(atk_dist, aoe_dist)
        if t_dist > effective_range:
            move_dir = "right" if t_cx > px else "left"
            # 骞冲彴杈圭晫锛氬埌杈圭紭鍋滄
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
            # 銆愭ā鍧桟銆戣烦璺冭Е鍙戯細鏂滃潯(鎬猋宸?25) OR 鍓嶆柟缁跨嚎鏈夋尝鍔?鏂眰/涓婂潯/涓嬪潯)锛岄兘瑕佽烦鐫€璺?
            slope_ahead = self._check_platform_slope_ahead(move_dir)
            if (on_slope or slope_ahead) and jump_key and now - self._combat_last_jump > 400:
                self._press_game_key(jump_key, duration=80)
                self._combat_last_jump = now
            self._combat_last_move = now
            return

        # 杩涘叆鏀诲嚮鑼冨洿
        move_dir = "right" if t_cx > px else "left"
        # 銆愭ā鍧桟銆戣烦璺冭Е鍙戯細鏂滃潯(鎬猋宸?25) OR 鍓嶆柟缁跨嚎鏈夋尝鍔?鏂眰/涓婂潯/涓嬪潯)锛岄兘瑕佽烦鐫€璺?鏀诲嚮
        slope_ahead = self._check_platform_slope_ahead(move_dir)
        if on_slope or slope_ahead:
            # 鏂滃潯/娉㈠姩鏀诲嚮锛氫繚鎸佹湞鐩爣X鏂瑰悜绉诲姩 + 鍛ㄦ湡鎬ц烦璺?+ 鏀诲嚮锛堢珯鐫€鎵撲笉鍒版尝鍔ㄥ湴褰笂鐨勬€級
            self._set_combat_move(move_dir)
            if jump_key and now - self._combat_last_jump > 350:
                self._press_game_key(jump_key, duration=70)
                self._combat_last_jump = now
            _debug_log("[鎵撴€猐 鏂滃潯/娉㈠姩鏀诲嚮 y_diff=%d 缁跨嚎娉㈠姩=%s 鏂瑰悜=%s" % (y_diff, slope_ahead, move_dir))
        else:
            # 骞冲湴锛氱珯瀹氭敾鍑?
            self._release_combat_move()

        skill_rand = fight_cfg.get("skill_random", 50)
        skill_cast = False

        # --- 缇ゆ敾锛氳寖鍥村唴>=3鍙€紝80%姒傜巼鏀?---
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
                    self._rlog("缇ゆ敾 %s 鑼冨洿鍐?d鍙? % (aoe_key, in_range), (0, 165, 255))
                    print("[缇ゆ敾] %s 閲婃斁 (鑼冨洿鍐?d鍙€?" % (aoe_key, in_range))

        # --- 涓绘敾锛氱洰鏍囧湪璺濈鍐咃紝5%鎸夐敊 ---
        atk_key = fight_cfg.get("atk1_key", "")
        if not skill_cast and atk_key:
            atk_dist = fight_cfg.get("atk1_distance", 150)
            atk_cd = fight_cfg.get("atk1_interval", 300)
            last = self._attack_last.get("atk1", 0)
            if t_dist <= atk_dist and now - last > atk_cd + random.randint(-skill_rand, skill_rand):
                if random.random() < 0.05 and aoe_key:
                    self._press_game_key(aoe_key)
                    self._rlog("涓绘敾(鎸夐敊) %s" % aoe_key, (0, 200, 0))
                else:
                    self._press_game_key(atk_key)
                    self._rlog("涓绘敾 %s 璺濈%d" % (atk_key, t_dist), (0, 200, 0))
                self._attack_last["atk1"] = now
                skill_cast = True
                print("[涓绘敾] %s 閲婃斁 (鐩爣%dpx)" % (atk_key, t_dist))

        # === BUFF 1-6锛?0%姒傜巼鏅氳ˉ2-5绉掞級===
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
                    print("[BUFF%d] %s 閲婃斁" % (i, key))
                    break

        # === 鑽搧1-5锛堝懆鏈熸€э紝鍔犻殢鏈猴級===
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
                print("[鑽搧%d] %s 閲婃斁" % (i, key))


    def _bind_window(self):
        """閲嶆柊缁戝畾娓告垙绐楀彛锛堟ā绯婂尮閰嶆爣棰橈級"""
        hwnd = _find_game_window()
        if hwnd:
            self.hwnd = hwnd
            self._update_window_rect()
            self._detect_minimap()
            self._save_target_window_size()
            self._add_log("绐楀彛宸茬粦瀹?)
            print("[绐楀彛缁戝畾] 宸茬粦瀹?)
        else:
            self._add_log("鏈壘鍒版父鎴忕獥鍙?)
            print("[绐楀彛缁戝畾] 鏈壘鍒版父鎴忕獥鍙?)

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
            # 銆愯皟璇?蹇冭烦銆戞瘡绉掕緭鍑轰竴娆★紝纭涓诲惊鐜槸鍚﹀湪杩愯
            if self.frame_count % 30 == 0:
                self._rlog("銆愬績璺炽€戜富寰幆杩愯涓?frame=%d stage=%d" % (self.frame_count, self._auto_calib_stage))
            if self._auto_refresh and self.frame_count % 30 == 0:
                self._detect_minimap(debug=False)
            # 绐楀彛澶у皬鍥哄畾锛氭瘡30甯ф娴嬩竴娆★紝鍙樺姩鍒欐媺鍥?
            if self.frame_count % 30 == 0:
                self._ensure_window_size()
            if self.frame_count % 2 == 0 or self.last_player_pos is None:
                player_pos = self.find_player_dot(map_area)
            else:
                player_pos = self.last_player_pos
            self._player_map_pos = player_pos  # 淇濆瓨灏忓湴鍥惧潗鏍囦緵鎴樻枟閫昏緫鍒ゆ柇骞冲彴
            # 銆愭ā鍧桞銆戠嫭绔嬫娴嬩汉鐗╁睆骞曚綅缃?鎬墿锛堜笉渚濊禆杩愯鐘舵€侊紝鑴氭湰鍚姩灏卞伐浣滐級
            if self.hwnd and (not getattr(self, '_player_screen_pos', None) or self.frame_count % 2 == 0):
                try:
                    _frame = self._capture_window()
                    if _frame is not None:
                        self._player_screen_pos = self._get_player_screen_pos(_frame)
                        # 涓嶈繍琛屾椂涔熸娴嬫€墿锛堟瘡2甯т竴娆★紝绾?0ms锛岃窡鎵嬩笉鍗★紝纭繚绱壊鐐逛笉杩愯涔熸樉绀猴級
                        if not self._running and self.frame_count % 2 == 0:
                            self._monsters = self._detect_monsters(_frame)
                except Exception:
                    pass
            # 銆愭ā鍧桞銆戣嚜鍔ㄦ牎鍑唖cale姣斾緥锛堜汉鐗╃Щ鍔ㄦ椂璁板綍灞忓箷鍜屽皬鍦板浘鍙樺寲锛岃秺璺戣秺鍑嗭級
            self._update_scale_calibration()
            # 銆愭ā鍧桞銆戣嚜鍔ㄨ褰曠鐐瑰凡鍙栨秷锛屾敼鐢ㄦ墜鍔ㄥ悓灞忎笁鐐规牎鍑嗭紙涓嶈法鐢婚潰鏇村噯锛?
            # self._auto_calibrate_edges()

            # 銆愭ā鍧桞銆戣挋鏉挎嫋鍔ㄦ娴嬶紙浠卻tage=1鏃讹紝绾㈢豢钃濅笁鐐硅窡闅忎汉鐗╃Щ鍔紝鍙嫋鍔ㄧ豢鐐硅摑鐐硅皟鍋忕Щ锛?
            if self._auto_calib_stage == 1:
                # 瀹炴椂鏇存柊鍩虹偣浣嶇疆锛堢孩鑹插熀鐐硅鐩栦汉鐗╃壒寰侊紝璺熼殢浜虹墿绉诲姩锛?
                if self._player_screen_pos:
                    psx, psy = self._player_screen_pos[0], self._player_screen_pos[1]
                    pmx, pmy = (self._player_map_pos[0], self._player_map_pos[1]) if self._player_map_pos else (0, 0)
                    self._auto_calib_base = (psx, psy, pmx, pmy)
                # 缁跨偣钃濈偣灞忓箷鍧愭爣 = 鍩虹偣 + 鐩稿鍋忕Щ锛堣窡鐫€浜虹墿涓€璧峰姩锛?
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
                # 榧犳爣鎷栧姩妫€娴嬶紙鍏ㄥ眬GetAsyncKeyState锛屼笉渚濊禆钂欐澘绐楀彛娑堟伅锛?
                left_down = user32.GetAsyncKeyState(0x01) & 0x8000  # VK_LBUTTON
                cursor = POINT()
                user32.GetCursorPos(ctypes.byref(cursor))
                # 鍏ㄥ眬鍧愭爣杞獥鍙ｅ潗鏍囷紙鍑忕獥鍙ｅ乏涓婅锛屽拰钂欐澘缁樺埗/_capture_window涓€鑷达級
                if self.window_rect:
                    mx = cursor.x - self.window_rect['left']
                    my = cursor.y - self.window_rect['top']
                else:
                    mx, my = cursor.x, cursor.y
                if left_down and not self._auto_calib_dragging:
                    # 宸﹂敭鍒氭寜涓嬶紝妫€娴嬫槸鍚︾偣涓豢鐐规垨钃濈偣锛埪?2px鑼冨洿锛?
                    if green_scr and abs(mx - green_scr[0]) <= 18 and abs(my - green_scr[1]) <= 18:
                        self._auto_calib_dragging = 'green'
                    elif blue_scr and abs(mx - blue_scr[0]) <= 18 and abs(my - blue_scr[1]) <= 18:
                        self._auto_calib_dragging = 'blue'
                elif left_down and self._auto_calib_dragging:
                    # 鎷栧姩涓紝鏇存柊鐩稿鍋忕Щ锛堢豢鐐瑰彧姘村钩锛岃摑鐐瑰彧鍨傜洿锛屽熀鐐硅窡闅忎汉鐗╋級
                    if base:
                        bx, by = base[0], base[1]
                        if self._auto_calib_dragging == 'green':
                            self._auto_calib_green_offset = (mx - bx, 0)  # 鍙按骞?
                        elif self._auto_calib_dragging == 'blue':
                            self._auto_calib_blue_offset = (0, my - by)  # 鍙瀭鐩?
                elif not left_down and self._auto_calib_dragging:
                    # 宸﹂敭鏉惧紑锛岀粨鏉熸嫋鍔?
                    self._auto_calib_dragging = None

            # 銆愭ā鍧桞銆戞ā鏉垮尮閰嶈窡韪紙stage>=2鏃讹紝姣?甯у尮閰嶄竴娆★紝璺熻釜鐗硅壊浣嶇疆鐢荤豢/钃濆渾锛?
            if self._auto_calib_stage >= 2 and self.frame_count % 5 == 0:
                self._match_calib_templates()

            if self.recording_platform and player_pos:
                # 鍚屼竴X浣嶇疆(宸€?3px)鐨勬柊鐐硅鐩栨棫鐐癸紝浠ュ悗鐢荤殑涓哄噯
                if self.platform_points and abs(self.platform_points[-1][0] - player_pos[0]) < 3:
                    self.platform_points[-1] = player_pos
                else:
                    self.platform_points.append(player_pos)
            if self.recording_ladder and player_pos:
                self.ladder_points.append(player_pos)

            self._random_step(player_pos)
            self._check_hotkeys()

            # === 鑷姩鍚冭嵂妫€娴嬶紙HP/MP浣庝簬闃堝€硷級 ===
            try:
                self._check_auto_potion()
            except Exception as e:
                print("[鑷姩鍚冭嵂] 寮傚父:", e)
            try:
                self._combat_tick()
            except Exception as e:
                print("[鎴樻枟] 寮傚父:", e)

            # === 鍋忕Щ瑙嗚鍙嶉锛堟父鎴忕敾闈腑瑙掕壊鍖归厤鐐?鍋忕Щ鐐癸級===
            try:
                self._show_offset_feedback()
            except Exception as e:
                print("[鍋忕Щ鍙嶉] 寮傚父:", e)

            # === 閫忔槑钂欐澘锛堟€墿/榛勭偣/琛€鏉＄孩鐐?钃濇潯钃濈偣缁熶竴鏄剧ず锛?==
            # 妫€娴嬬粨鏋滅敱 _combat_tick 姣?50ms鏇存柊鍒?self._monsters / self._player_screen_pos
            # 钂欐澘鍙绐楀彛缁戝畾鎴愬姛灏卞惎鍔紙涓嶄緷璧朹running锛夛紝纭繚鍔犺嵂绔栨濮嬬粓鍙
            if self.hwnd and not self._monster_overlay_running:
                self._start_monster_overlay()
            if self._running:
                try:
                    if self._monster_overlay_data is None:
                        self._monster_overlay_data = {}
                    # 鍚屾鎬墿鍜屼汉鐗╀綅缃埌钂欐澘
                    self._monster_overlay_data["monsters"] = self._monsters
                    self._monster_overlay_data["monster_hp_bars"] = self._monster_hp_bars
                    if self._player_screen_pos:
                        self._monster_overlay_data["char_pos"] = self._player_screen_pos
                except Exception as e:
                    print("[钂欐澘] 鍚屾寮傚父:", e)

            # === 鍑嗘槦鎷栨嫿缁戝畾妫€娴?===
            if self._drag_crosshair:
                left_down = user32.GetAsyncKeyState(0x01) & 0x8000  # VK_LBUTTON
                if left_down:
                    # 璺熼殢鍏ㄥ眬榧犳爣浣嶇疆锛堜笉闄愬埗鍦║I绐楀彛鍐咃紝鍙嫋鍒板叾浠栫獥鍙ｏ級
                    cursor = POINT()
                    user32.GetCursorPos(cursor)
                    hwnd_ui = user32.FindWindowW(None, "PLAY AND HAPPY")
                    if hwnd_ui:
                        user32.ScreenToClient(hwnd_ui, ctypes.byref(cursor))
                        self._crosshair_pos = (cursor.x, cursor.y)
                else:
                    # 宸﹂敭閲婃斁锛岀粦瀹氶紶鏍囨寚鍚戠殑椤跺眰绐楀彛
                    cursor = POINT()
                    user32.GetCursorPos(cursor)
                    hwnd = user32.WindowFromPoint(cursor)
                    # GetAncestor鍙栫湡姝ｉ《灞傜獥鍙?GA_ROOT=2)
                    hwnd = user32.GetAncestor(hwnd, 2)
                    _debug_log("璺ㄧ嚎閲婃斁缁戝畾 hwnd=%s" % hwnd)
                    _debug_log("鍓嶅彴缁戝畾 hwnd=%s" % hwnd)
                    if hwnd:
                        length = user32.GetWindowTextLengthW(hwnd)
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        title = buf.value or "鏈煡绐楀彛"
                        _debug_log("鍓嶅彴缁戝畾鏍囬: %s" % title)
                        self.hwnd = hwnd
                        self._update_window_rect()
                        self._detect_minimap()
                        self._save_target_window_size()
                        if not any(w["hwnd"] == hwnd for w in self._bound_windows):
                            self._bound_windows.append({"hwnd": hwnd, "title": title})
                        self._add_log("宸茬粦瀹? %s" % title[:20])
                        print("[绐楀彛缁戝畾] 鍓嶅彴绐楀彛宸茬粦瀹?", title)
                    else:
                        self._add_log("缁戝畾澶辫触")
                    self._drag_crosshair = False
                    self._crosshair_pos = self._crosshair_home

            try:
                frame = self.draw(map_area, player_pos)
                cv2.imshow(win, frame)
            except Exception as e:
                print("draw error:", e)
                cv2.imshow(win, self._ui_bg)

            key = cv2.waitKey(10) & 0xFF
            # 杈撳叆妗嗚嚜鍔ㄥけ鐒︼細3绉掓棤鍙樺寲锛堝叏灞€杞杈撳叆涓嶄緷璧朥I鍓嶅彴锛屾晠涓嶆鏌ュ墠鍙扮獥鍙ｏ級
            if self._focused_field is not None:
                now_ms = time.time() * 1000
                if now_ms - self._last_input_change > 3000:
                    self._save_input_config()
                    self._focused_field = None
            # 杈撳叆妗嗚仛鐒︽椂浼樺厛澶勭悊閿洏
            if self._focused_field is not None:
                if self._is_key_field(self._focused_field):
                    # BACKSPACE娓呯┖閿€硷紝ESC鍙栨秷鑱氱劍锛堜笉鍙備笌鎸夐敭鎹曡幏锛?
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
            # 浠绘剰鎸夐敭鍏抽棴鎵€鏈変笅鎷夎彍鍗?
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
    # === 绠＄悊鍛樻潈闄愭鏌?===
    # 娓告垙(鍐掗櫓宀涙€€鏃ф湇)浠ョ鐞嗗憳鏉冮檺杩愯锛孶IPI浼氶樆姝㈡櫘閫氭潈闄愯繘绋嬪悜绠＄悊鍛樿繘绋嬪彂閫佹ā鎷熻緭鍏?
    # 蹇呴』浠ョ鐞嗗憳鏉冮檺鍚姩bot锛屽惁鍒欐寜閿?鍔犺嵂鍏ㄩ儴鏃犳晥
    import ctypes as _ctypes, sys as _sys
    def _is_admin():
        try:
            return _ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False
    if False and not _is_admin():
        print("[鏉冮檺] 妫€娴嬪埌闈炵鐞嗗憳鏉冮檺锛屾父鎴忎互绠＄悊鍛樿繍琛屾椂蹇呴』浠ョ鐞嗗憳鍚姩bot")
        print("[鏉冮檺] 姝ｅ湪鑷姩浠ョ鐞嗗憳鏉冮檺閲嶅惎...")
        try:
            _params = " ".join(['"%s"' % a for a in _sys.argv[1:]]) if len(_sys.argv) > 1 else ""
            _ctypes.windll.shell32.ShellExecuteW(None, "runas", _sys.executable, _params, None, 1)
        except Exception as _e:
            print("[鏉冮檺] 鑷姩鎻愬崌澶辫触: %s" % _e)
            print("[鏉冮檺] 璇峰彸閿?MapleBot.exe 閫夋嫨'浠ョ鐞嗗憳韬唤杩愯'")
            try:
                input("鎸夊洖杞﹂€€鍑?..")
            except:
                pass
        _sys.exit()
    print("[鏉冮檺] 宸蹭互绠＄悊鍛樻潈闄愯繍琛岋紝妯℃嫙杈撳叆鍙甯稿彂閫佸埌娓告垙")
    MinimapRouteRecorder().run()

