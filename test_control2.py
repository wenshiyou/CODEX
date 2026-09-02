"""
测试：用扫描码方式发送方向键控制角色
"""
import ctypes
import time

user32 = ctypes.windll.user32

game_hwnd = user32.FindWindowW(None, "冒险岛怀旧服")
print(f"游戏窗口: {game_hwnd}")

if not game_hwnd:
    print("未找到游戏窗口！")
    exit(1)

# 激活游戏窗口
user32.SetForegroundWindow(game_hwnd)
time.sleep(1)

PUL = ctypes.POINTER(ctypes.c_ulong)
class KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", PUL)]
class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput)]
class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]

KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002

# 方向键扫描码
SCAN_RIGHT = 0x4D
SCAN_LEFT = 0x4B
SCAN_UP = 0x48
SCAN_DOWN = 0x50

def press_scan(scan_code):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput(0, scan_code, KEYEVENTF_SCANCODE, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

def release_scan(scan_code):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput(0, scan_code, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

print("3秒后开始向右移动...")
time.sleep(3)

print("按住右键3秒...")
press_scan(SCAN_RIGHT)
time.sleep(3)
release_scan(SCAN_RIGHT)
time.sleep(0.5)

print("按住左键3秒...")
press_scan(SCAN_LEFT)
time.sleep(3)
release_scan(SCAN_LEFT)

print("完成！")
