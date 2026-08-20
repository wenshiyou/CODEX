"""
测试：直接控制游戏角色左右移动，用于测试路径录制
"""
import ctypes
import time
import struct

user32 = ctypes.windll.user32

# 查找游戏窗口
hwnd = user32.FindWindowW(None, "冒险岛怀旧服")
print(f"游戏窗口句柄: {hwnd}")

if not hwnd:
    print("未找到游戏窗口！")
    exit(1)

# 激活游戏窗口
user32.SetForegroundWindow(hwnd)
time.sleep(0.5)

# SendInput 结构体
PUL = ctypes.POINTER(ctypes.c_ulong)

class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL)
    ]

class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort)
    ]

class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL)
    ]

class Input_I(ctypes.Union):
    _fields_ = [
        ("ki", KeyBdInput),
        ("mi", MouseInput),
        ("hi", HardwareInput)
    ]

class Input(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ii", Input_I)
    ]

def press_key(hex_key_code):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput(hex_key_code, 0, 0, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

def release_key(hex_key_code):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput(hex_key_code, 0, 0x0002, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

# 方向键虚拟键码
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28

print("3秒后开始向右移动...")
time.sleep(3)

print("向右移动3秒...")
press_key(VK_RIGHT)
time.sleep(3)
release_key(VK_RIGHT)
time.sleep(0.5)

print("向左移动3秒...")
press_key(VK_LEFT)
time.sleep(3)
release_key(VK_LEFT)

print("移动完成！")
