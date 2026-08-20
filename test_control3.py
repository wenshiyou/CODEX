"""
测试：扫描码 + 扩展键标志 控制角色移动（修复版）
冒险岛用 DirectInput，必须用扫描码且方向键需带 EXTENDEDKEY 标志
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
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", PUL)]


class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]


# 关键标志位
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001   # 方向键必须带这个！
KEYEVENTF_KEYUP = 0x0002

# 方向键扫描码（set 1）
SCAN_UP = 0x48
SCAN_DOWN = 0x50
SCAN_LEFT = 0x4B
SCAN_RIGHT = 0x4D

# 普通键扫描码（不需要扩展标志）
SCAN_SPACE = 0x39
SCAN_LALT = 0x38
SCAN_LCTRL = 0x1D
SCAN_LSHIFT = 0x2A


def press_scan(scan_code, extended=False):
    """按下键，extended=True 表示方向键等扩展键"""
    extra = ctypes.c_ulong(0)
    flags = KEYEVENTF_SCANCODE
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    ii_ = Input_I()
    ii_.ki = KeyBdInput(0, scan_code, flags, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    n = user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))
    return n


def release_scan(scan_code, extended=False):
    """释放键"""
    extra = ctypes.c_ulong(0)
    flags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    ii_ = Input_I()
    ii_.ki = KeyBdInput(0, scan_code, flags, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    n = user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))
    return n


def hold_scan(scan_code, duration, extended=False):
    """按住键指定时长"""
    n1 = press_scan(scan_code, extended)
    time.sleep(duration)
    n2 = release_scan(scan_code, extended)
    return n1, n2


print("=" * 50)
print("测试1：虚拟键码方式（可能无效）")
print("=" * 50)
# 先试虚拟键码，看SendInput返回值
extra = ctypes.c_ulong(0)
ii_ = Input_I()
ii_.ki = KeyBdInput(0x27, 0, 0, 0, ctypes.pointer(extra))  # VK_RIGHT
x = Input(ctypes.c_ulong(1), ii_)
n = user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))
print(f"  虚拟键码按下 SendInput 返回: {n} (1=成功)")
time.sleep(0.1)
ii_.ki = KeyBdInput(0x27, 0, KEYEVENTF_KEYUP, 0, ctypes.pointer(extra))
x = Input(ctypes.c_ulong(1), ii_)
user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

print()
print("=" * 50)
print("测试2：扫描码 + 扩展键标志（应该有效）")
print("=" * 50)
print("3秒后开始向右移动3秒...")
time.sleep(3)

n1, n2 = hold_scan(SCAN_RIGHT, 3, extended=True)
print(f"  右键按下 SendInput={n1}, 释放 SendInput={n2}")
time.sleep(0.5)

print("向左移动3秒...")
n1, n2 = hold_scan(SCAN_LEFT, 3, extended=True)
print(f"  左键按下 SendInput={n1}, 释放 SendInput={n2}")
time.sleep(0.5)

print()
print("=" * 50)
print("测试3：跳跃（空格）")
print("=" * 50)
print("2秒后跳3次...")
time.sleep(2)
for i in range(3):
    press_scan(SCAN_SPACE, extended=False)
    time.sleep(0.15)
    release_scan(SCAN_SPACE, extended=False)
    time.sleep(0.5)
    print(f"  跳了第{i+1}次")

print()
print("测试完成！观察角色是否移动/跳跃")
