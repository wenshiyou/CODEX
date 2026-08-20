"""
键鼠控制模块
使用 Win32 SendInput + 扫描码（Scan Code）进行底层键鼠模拟。
方向键等扩展键自动添加 KEYEVENTF_EXTENDEDKEY 标志，兼容 DirectInput 游戏。
支持: 按键按下/释放/单击、组合键、鼠标点击、按住方向键移动。
"""
import time
import ctypes
from ctypes import wintypes

# Windows API 常量
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

# 虚拟键码映射（保留用于参考，实际发送用扫描码）
VK_MAP = {
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
    "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
    "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
    "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
    "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59,
    "z": 0x5A,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "space": 0x20,
    "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "backspace": 0x08,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
}

# PS/2 扫描码（Set 1）映射表
SCAN_MAP = {
    # 字母
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12,
    "f": 0x21, "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24,
    "k": 0x25, "l": 0x26, "m": 0x32, "n": 0x31, "o": 0x18,
    "p": 0x19, "q": 0x10, "r": 0x13, "s": 0x1F, "t": 0x14,
    "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D, "y": 0x15,
    "z": 0x2C,
    # 数字
    "0": 0x0B, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05,
    "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A,
    # 功能键
    "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F,
    "f6": 0x40, "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44,
    "f11": 0x57, "f12": 0x58,
    # 控制键
    "ctrl": 0x1D, "alt": 0x38, "shift": 0x2A, "space": 0x39,
    "enter": 0x1C, "esc": 0x01, "tab": 0x0F, "backspace": 0x0E,
    # 方向键（扩展键，扫描码相同但需 EXTENDEDKEY 标志）
    "up": 0x48, "down": 0x50, "left": 0x4B, "right": 0x4D,
    # 编辑键（扩展键）
    "insert": 0x52, "delete": 0x53, "home": 0x47, "end": 0x4F,
    "pageup": 0x49, "pagedown": 0x51,
}

# 需要 EXTENDEDKEY 标志的键（方向键、编辑键等）
EXTENDED_KEYS = {"up", "down", "left", "right",
                 "insert", "delete", "home", "end",
                 "pageup", "pagedown"}


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [("ki", KeyBdInput), ("mi", MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", InputUnion)]


class InputController:
    """键鼠控制器 - 扫描码模式，兼容 DirectInput 游戏"""

    def __init__(self):
        self._pressed_keys = set()

    def _get_scan(self, key):
        """获取键的扫描码"""
        key_lower = key.lower()
        if key_lower not in SCAN_MAP:
            raise ValueError(f"不支持的按键: {key}，可用按键: {list(SCAN_MAP.keys())}")
        return SCAN_MAP[key_lower]

    def _is_extended(self, key):
        """判断是否为扩展键"""
        return key.lower() in EXTENDED_KEYS

    def key_down(self, key):
        """按下一个键（扫描码模式）"""
        scan = self._get_scan(key)
        flags = KEYEVENTF_SCANCODE
        if self._is_extended(key):
            flags |= KEYEVENTF_EXTENDEDKEY
        inp = Input(type=INPUT_KEYBOARD)
        inp.union.ki = KeyBdInput(wVk=0, wScan=scan, dwFlags=flags,
                                  time=0, dwExtraInfo=None)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        self._pressed_keys.add(key.lower())

    def key_up(self, key):
        """释放一个键（扫描码模式）"""
        scan = self._get_scan(key)
        flags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
        if self._is_extended(key):
            flags |= KEYEVENTF_EXTENDEDKEY
        inp = Input(type=INPUT_KEYBOARD)
        inp.union.ki = KeyBdInput(wVk=0, wScan=scan, dwFlags=flags,
                                  time=0, dwExtraInfo=None)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        self._pressed_keys.discard(key.lower())

    def press_key(self, key, duration=0.05):
        """单击一个键（按下+释放）"""
        self.key_down(key)
        time.sleep(duration)
        self.key_up(key)

    def press_combo(self, *keys, duration=0.05):
        """按组合键，如 press_combo('ctrl', 'c')"""
        for key in keys:
            self.key_down(key)
            time.sleep(0.02)
        time.sleep(duration)
        for key in reversed(keys):
            self.key_up(key)
            time.sleep(0.02)

    def hold_key(self, key, duration):
        """按住一个键指定时长"""
        self.key_down(key)
        time.sleep(duration)
        self.key_up(key)

    def release_all(self):
        """释放所有按住的键"""
        for key in list(self._pressed_keys):
            self.key_up(key)
        self._pressed_keys.clear()

    def move_left(self, duration=0.1):
        """向左移动"""
        self.hold_key("left", duration)

    def move_right(self, duration=0.1):
        """向右移动"""
        self.hold_key("right", duration)

    def jump(self, jump_key="alt"):
        """跳跃"""
        self.press_key(jump_key, duration=0.1)

    def attack(self, attack_key="x"):
        """攻击"""
        self.press_key(attack_key, duration=0.05)

    def use_skill(self, skill_key):
        """使用技能"""
        self.press_key(skill_key, duration=0.05)

    def climb_up(self, duration=0.1):
        """向上爬（需要先在梯子上）"""
        self.hold_key("up", duration)

    def climb_down(self, duration=0.1):
        """向下爬（需要先在梯子上）"""
        self.hold_key("down", duration)

    def mouse_click(self, x=None, y=None, button="left"):
        """鼠标点击，可指定坐标"""
        if x is not None and y is not None:
            ctypes.windll.user32.SetCursorPos(x, y)
            time.sleep(0.02)

        flag_down = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
        flag_up = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP

        inp_down = Input(type=INPUT_MOUSE)
        inp_down.union.mi = MouseInput(dx=0, dy=0, mouseData=0, dwFlags=flag_down,
                                       time=0, dwExtraInfo=None)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(inp_down))

        time.sleep(0.02)

        inp_up = Input(type=INPUT_MOUSE)
        inp_up.union.mi = MouseInput(dx=0, dy=0, mouseData=0, dwFlags=flag_up,
                                     time=0, dwExtraInfo=None)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(inp_up))
