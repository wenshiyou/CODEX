"""
自动测试平台录制：按P开始 -> 控制角色左右移动 -> 按P停止
"""
import ctypes
import time
import mss
import numpy as np
import cv2

user32 = ctypes.windll.user32

game_hwnd = user32.FindWindowW(None, "冒险岛怀旧服")
opencv_hwnd = [None]

def find_opencv_window():
    def callback(hwnd, _):
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        if "Minimap Route Recorder" in title.value:
            opencv_hwnd[0] = hwnd
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(callback), None)

find_opencv_window()
print(f"game: {game_hwnd}, opencv: {opencv_hwnd[0]}")

PUL = ctypes.POINTER(ctypes.c_ulong)
class KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", PUL)]
class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput)]
class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]

def send_key(hwnd, vk):
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput(vk, 0, 0, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))
    time.sleep(0.05)
    ii_.ki = KeyBdInput(vk, 0, 0x0002, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

def hold_key(vk, duration):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput(vk, 0, 0, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))
    time.sleep(duration)
    ii_.ki = KeyBdInput(vk, 0, 0x0002, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

VK_P = 0x50
VK_RIGHT = 0x27
VK_LEFT = 0x25

if opencv_hwnd[0] and game_hwnd:
    print("start test...")
    send_key(opencv_hwnd[0], VK_P)
    time.sleep(1)

    user32.SetForegroundWindow(game_hwnd)
    time.sleep(0.5)
    print("move right 3s...")
    hold_key(VK_RIGHT, 3)
    time.sleep(0.3)
    print("move left 3s...")
    hold_key(VK_LEFT, 3)
    time.sleep(0.3)

    send_key(opencv_hwnd[0], VK_P)
    time.sleep(1)

    sct = mss.mss()
    frame = np.array(sct.grab(sct.monitors[1]))[:, :, :3]
    cv2.imwrite("test_platform_result.png", frame)
    print("done! saved test_platform_result.png")
else:
    print("window not found!")
