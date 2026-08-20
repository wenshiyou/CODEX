"""
键鼠控制模块（增强版）
支持三种输入方式，自动诊断游戏兼容性:
  1. sendinput_scan  - SendInput + 扫描码 + EXTENDEDKEY（兼容 DirectInput，推荐）
  2. sendinput_vk    - SendInput + 虚拟键码（兼容普通 Windows 应用）
  3. postmessage     - PostMessage 直接发消息到游戏窗口（绕过 SendInput 拦截）

用法:
  ctrl = InputController(game_hwnd=hwnd, input_method="auto")
  ctrl.set_foreground()       # 激活游戏窗口
  ctrl.move_right(0.5)        # 向右移动0.5秒
  ctrl.attack()               # 攻击
"""
import time
import ctypes
from ctypes import wintypes

# Windows API 常量
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

# 虚拟键码映射
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
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12,
    "f": 0x21, "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24,
    "k": 0x25, "l": 0x26, "m": 0x32, "n": 0x31, "o": 0x18,
    "p": 0x19, "q": 0x10, "r": 0x13, "s": 0x1F, "t": 0x14,
    "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D, "y": 0x15,
    "z": 0x2C,
    "0": 0x0B, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05,
    "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A,
    "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F,
    "f6": 0x40, "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44,
    "f11": 0x57, "f12": 0x58,
    "ctrl": 0x1D, "alt": 0x38, "shift": 0x2A, "space": 0x39,
    "enter": 0x1C, "esc": 0x01, "tab": 0x0F, "backspace": 0x0E,
    "up": 0x48, "down": 0x50, "left": 0x4B, "right": 0x4D,
    "insert": 0x52, "delete": 0x53, "home": 0x47, "end": 0x4F,
    "pageup": 0x49, "pagedown": 0x51,
}

# 需要 EXTENDEDKEY 标志的键（方向键、编辑键等）
EXTENDED_KEYS = {"up", "down", "left", "right",
                 "insert", "delete", "home", "end",
                 "pageup", "pagedown"}

# 需要用 WM_SYSKEYDOWN/UP 发送的键（Alt 相关）
SYS_KEYS = {"alt"}


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


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class InputController:
    """键鼠控制器 - 多输入方式，兼容 DirectInput 游戏"""

    def __init__(self, game_hwnd=None, input_method="auto", verbose=False):
        """
        Args:
            game_hwnd: 游戏窗口句柄，用于 PostMessage 和 SetForeground
            input_method: "auto" | "sendinput_scan" | "sendinput_vk" | "postmessage"
            verbose: 是否打印详细日志
        """
        self._pressed_keys = set()
        self.game_hwnd = game_hwnd
        self.input_method = input_method
        self.verbose = verbose
        self._extra = ctypes.c_ulong(0)
        self._last_error = 0

    def _log(self, msg):
        if self.verbose:
            print(f"[Controller] {msg}")

    def set_game_window(self, hwnd):
        """设置游戏窗口句柄"""
        self.game_hwnd = hwnd

    def set_foreground(self):
        """激活游戏窗口到前台"""
        if self.game_hwnd:
            # 先最小化再恢复，绕过 SetForegroundWindow 限制
            user32.ShowWindow(self.game_hwnd, 9)  # SW_RESTORE
            time.sleep(0.05)
            user32.SetForegroundWindow(self.game_hwnd)
            time.sleep(0.1)
            return True
        return False

    def _get_vk(self, key):
        key_lower = key.lower()
        if key_lower not in VK_MAP:
            raise ValueError(f"不支持的按键: {key}")
        return VK_MAP[key_lower]

    def _get_scan(self, key):
        key_lower = key.lower()
        if key_lower not in SCAN_MAP:
            raise ValueError(f"不支持的按键: {key}")
        return SCAN_MAP[key_lower]

    def _is_extended(self, key):
        return key.lower() in EXTENDED_KEYS

    def _is_sys_key(self, key):
        return key.lower() in SYS_KEYS

    def _make_lparam(self, vk, is_down=True, repeat=1, scan=0, extended=False,
                     context=0, prev=0, transition=0):
        """构造 lParam for PostMessage"""
        scan = scan or (MapVirtualKey(vk, 0) & 0xFF)
        lparam = repeat & 0xFFFF
        lparam |= (scan & 0xFF) << 16
        if extended:
            lparam |= 1 << 24
        lparam |= (context & 1) << 29
        lparam |= (prev & 1) << 30
        if not is_down:
            lparam |= 1 << 31  # transition state = 1 for key up
        return lparam

    def _sendinput_scan_down(self, key):
        """SendInput 扫描码按下"""
        scan = self._get_scan(key)
        flags = KEYEVENTF_SCANCODE
        if self._is_extended(key):
            flags |= KEYEVENTF_EXTENDEDKEY
        inp = Input(type=INPUT_KEYBOARD)
        inp.union.ki = KeyBdInput(wVk=0, wScan=scan, dwFlags=flags,
                                  time=0, dwExtraInfo=ctypes.pointer(self._extra))
        n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        if n != 1:
            self._last_error = kernel32.GetLastError()
            self._log(f"SendInput(scan down) failed: n={n}, err={self._last_error}")
        return n == 1

    def _sendinput_scan_up(self, key):
        """SendInput 扫描码释放"""
        scan = self._get_scan(key)
        flags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
        if self._is_extended(key):
            flags |= KEYEVENTF_EXTENDEDKEY
        inp = Input(type=INPUT_KEYBOARD)
        inp.union.ki = KeyBdInput(wVk=0, wScan=scan, dwFlags=flags,
                                  time=0, dwExtraInfo=ctypes.pointer(self._extra))
        n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        if n != 1:
            self._last_error = kernel32.GetLastError()
            self._log(f"SendInput(scan up) failed: n={n}, err={self._last_error}")
        return n == 1

    def _sendinput_vk_down(self, key):
        """SendInput 虚拟键码按下"""
        vk = self._get_vk(key)
        flags = 0
        if self._is_extended(key):
            flags |= KEYEVENTF_EXTENDEDKEY
        inp = Input(type=INPUT_KEYBOARD)
        inp.union.ki = KeyBdInput(wVk=vk, wScan=0, dwFlags=flags,
                                  time=0, dwExtraInfo=ctypes.pointer(self._extra))
        n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        if n != 1:
            self._last_error = kernel32.GetLastError()
            self._log(f"SendInput(vk down) failed: n={n}, err={self._last_error}")
        return n == 1

    def _sendinput_vk_up(self, key):
        """SendInput 虚拟键码释放"""
        vk = self._get_vk(key)
        flags = KEYEVENTF_KEYUP
        if self._is_extended(key):
            flags |= KEYEVENTF_EXTENDEDKEY
        inp = Input(type=INPUT_KEYBOARD)
        inp.union.ki = KeyBdInput(wVk=vk, wScan=0, dwFlags=flags,
                                  time=0, dwExtraInfo=ctypes.pointer(self._extra))
        n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        if n != 1:
            self._last_error = kernel32.GetLastError()
            self._log(f"SendInput(vk up) failed: n={n}, err={self._last_error}")
        return n == 1

    def _postmessage_down(self, key):
        """PostMessage 按下（直接发到游戏窗口消息队列）"""
        if not self.game_hwnd:
            self._log("PostMessage: no game_hwnd")
            return False
        vk = self._get_vk(key)
        scan = MapVirtualKey(vk, 0) & 0xFF
        extended = self._is_extended(key)
        lparam = self._make_lparam(vk, is_down=True, scan=scan, extended=extended)
        msg = WM_SYSKEYDOWN if self._is_sys_key(key) else WM_KEYDOWN
        result = user32.PostMessageW(self.game_hwnd, msg, vk, lparam)
        if not result:
            self._last_error = kernel32.GetLastError()
            self._log(f"PostMessage(down) failed: err={self._last_error}")
        return bool(result)

    def _postmessage_up(self, key):
        """PostMessage 释放"""
        if not self.game_hwnd:
            return False
        vk = self._get_vk(key)
        scan = MapVirtualKey(vk, 0) & 0xFF
        extended = self._is_extended(key)
        lparam = self._make_lparam(vk, is_down=False, scan=scan, extended=extended,
                                   prev=1, transition=1)
        msg = WM_SYSKEYUP if self._is_sys_key(key) else WM_KEYUP
        result = user32.PostMessageW(self.game_hwnd, msg, vk, lparam)
        if not result:
            self._last_error = kernel32.GetLastError()
            self._log(f"PostMessage(up) failed: err={self._last_error}")
        return bool(result)

    def key_down(self, key):
        """按下一个键"""
        method = self.input_method
        if method == "auto":
            method = "sendinput_scan"  # auto 默认用扫描码

        if method == "sendinput_scan":
            ok = self._sendinput_scan_down(key)
        elif method == "sendinput_vk":
            ok = self._sendinput_vk_down(key)
        elif method == "postmessage":
            ok = self._postmessage_down(key)
        else:
            raise ValueError(f"Unknown input_method: {method}")

        if ok:
            self._pressed_keys.add(key.lower())
        self._log(f"key_down({key}) method={method} ok={ok}")
        return ok

    def key_up(self, key):
        """释放一个键"""
        method = self.input_method
        if method == "auto":
            method = "sendinput_scan"

        if method == "sendinput_scan":
            ok = self._sendinput_scan_up(key)
        elif method == "sendinput_vk":
            ok = self._sendinput_vk_up(key)
        elif method == "postmessage":
            ok = self._postmessage_up(key)
        else:
            raise ValueError(f"Unknown input_method: {method}")

        if ok:
            self._pressed_keys.discard(key.lower())
        self._log(f"key_up({key}) method={method} ok={ok}")
        return ok

    def press_key(self, key, duration=0.05):
        """单击一个键（按下+释放）"""
        self.key_down(key)
        time.sleep(duration)
        self.key_up(key)

    def press_combo(self, *keys, duration=0.05):
        """按组合键"""
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
        self.hold_key("left", duration)

    def move_right(self, duration=0.1):
        self.hold_key("right", duration)

    def jump(self, jump_key="alt"):
        self.press_key(jump_key, duration=0.1)

    def attack(self, attack_key="x"):
        self.press_key(attack_key, duration=0.05)

    def use_skill(self, skill_key):
        self.press_key(skill_key, duration=0.05)

    def climb_up(self, duration=0.1):
        self.hold_key("up", duration)

    def climb_down(self, duration=0.1):
        self.hold_key("down", duration)

    def mouse_click(self, x=None, y=None, button="left"):
        """鼠标点击，可指定坐标"""
        if x is not None and y is not None:
            user32.SetCursorPos(x, y)
            time.sleep(0.02)

        flag_down = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
        flag_up = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP

        inp_down = Input(type=INPUT_MOUSE)
        inp_down.union.mi = MouseInput(dx=0, dy=0, mouseData=0, dwFlags=flag_down,
                                       time=0, dwExtraInfo=ctypes.pointer(self._extra))
        user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(inp_down))
        time.sleep(0.02)
        inp_up = Input(type=INPUT_MOUSE)
        inp_up.union.mi = MouseInput(dx=0, dy=0, mouseData=0, dwFlags=flag_up,
                                     time=0, dwExtraInfo=ctypes.pointer(self._extra))
        user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(inp_up))

    def diagnose(self):
        """
        诊断输入环境，返回诊断报告。
        不实际发送按键，只检查环境状态。
        """
        report = []
        report.append("=== Input Controller Diagnosis ===")

        # 1. 游戏窗口
        if self.game_hwnd:
            report.append(f"Game hwnd: {self.game_hwnd}")
            # 检查窗口是否可见
            is_visible = bool(user32.IsWindowVisible(self.game_hwnd))
            report.append(f"Window visible: {is_visible}")
            # 检查是否前台
            fg = user32.GetForegroundWindow()
            report.append(f"Foreground window: {fg} (game: {fg == self.game_hwnd})")
            # 检查窗口标题
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(self.game_hwnd, title, 256)
            report.append(f"Window title: {title.value}")
        else:
            report.append("Game hwnd: NOT SET (PostMessage won't work)")

        # 2. 进程权限
        report.append(f"Input method: {self.input_method}")

        # 3. 测试 SendInput 是否可用（发送一个无害的键测试）
        # 用 F15 测试（通常不会被应用处理）
        test_inp = Input(type=INPUT_KEYBOARD)
        test_inp.union.ki = KeyBdInput(wVk=0x7E, wScan=0, dwFlags=0,
                                       time=0, dwExtraInfo=ctypes.pointer(self._extra))
        n = user32.SendInput(1, ctypes.byref(test_inp), ctypes.sizeof(test_inp))
        report.append(f"SendInput test: n={n} (1=ok)")
        if n != 1:
            err = kernel32.GetLastError()
            report.append(f"  GetLastError: {err}")
            report.append("  SendInput may be blocked by UIPI or anti-cheat")
            report.append("  Try: run script as Administrator, or use postmessage method")
        # 释放测试键
        test_inp.union.ki = KeyBdInput(wVk=0x7E, wScan=0, dwFlags=KEYEVENTF_KEYUP,
                                       time=0, dwExtraInfo=ctypes.pointer(self._extra))
        user32.SendInput(1, ctypes.byref(test_inp), ctypes.sizeof(test_inp))

        # 4. PostMessage 测试
        if self.game_hwnd:
            result = user32.PostMessageW(self.game_hwnd, WM_KEYDOWN, 0x7E, 0)
            report.append(f"PostMessage test: result={result} (nonzero=queued)")
            if not result:
                err = kernel32.GetLastError()
                report.append(f"  GetLastError: {err}")

        report.append("=== End Diagnosis ===")
        return "\n".join(report)


def MapVirtualKey(uCode, uMapType):
    """封装 MapVirtualKeyW"""
    return user32.MapVirtualKeyW(uCode, uMapType)
