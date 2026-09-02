"""
键盘控制测试工具 —— 验证哪条发键通路能被游戏/系统接收
用法：python keyboard_test.py
会自动检测环境、列出窗口、测试各种发键方式，结果写入 keyboard_test.log
"""
import ctypes
import time
import os
import sys

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keyboard_test.log")

def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# === 环境检测 ===
def check_admin():
    """检测是否以管理员身份运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def check_foreground():
    """获取当前前台窗口"""
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return hwnd, buf.value or "(无标题)"

def list_windows():
    """列出所有可见窗口标题"""
    results = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                results.append((hwnd, buf.value))
        return True
    user32.EnumWindows(cb, 0)
    return results

# === 发键方式1: keybd_event (VK模式) ===
def send_keybd_event_vk(vk, duration=100):
    scan = user32.MapVirtualKeyW(vk, 0)
    ext = 0x0001 if vk in (0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x28,0x2D,0x2E) else 0
    user32.keybd_event(vk, scan, ext, 0)
    time.sleep(duration / 1000.0)
    user32.keybd_event(vk, scan, ext | 0x0002, 0)

# === 发键方式2: keybd_event (扫描码模式) ===
def send_keybd_event_scan(vk, duration=100):
    scan = user32.MapVirtualKeyW(vk, 0)
    ext = 0x0001 if vk in (0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x28,0x2D,0x2E) else 0
    # KEYEVENTF_SCANCODE = 0x0008
    user32.keybd_event(vk, scan, ext | 0x0008, 0)
    time.sleep(duration / 1000.0)
    user32.keybd_event(vk, scan, ext | 0x0008 | 0x0002, 0)

# === 发键方式3: SendInput (VK模式) ===
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]
    _anonymous_ = ("_input",)
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT)]

def send_input_vk(vk, duration=100):
    scan = user32.MapVirtualKeyW(vk, 0)
    ext = 0x0001 if vk in (0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x28,0x2D,0x2E) else 0
    def make_input(vk_code, scan_code, flags):
        inp = INPUT()
        inp.type = 1
        inp.ki.wVk = vk_code
        inp.ki.wScan = scan_code
        inp.ki.dwFlags = flags
        inp.ki.time = 0
        inp.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        return inp
    down = make_input(vk, scan, ext)
    up = make_input(vk, scan, ext | 0x0002)
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(down))
    time.sleep(duration / 1000.0)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(up))

# === 发键方式4: SendInput (扫描码模式) ===
def send_input_scan(vk, duration=100):
    scan = user32.MapVirtualKeyW(vk, 0)
    ext = 0x0001 if vk in (0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x28,0x2D,0x2E) else 0
    def make_input(vk_code, scan_code, flags):
        inp = INPUT()
        inp.type = 1
        inp.ki.wVk = 0  # 扫描码模式
        inp.ki.wScan = scan_code
        inp.ki.dwFlags = flags | 0x0008  # KEYEVENTF_SCANCODE
        inp.ki.time = 0
        inp.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        return inp
    down = make_input(vk, scan, ext)
    up = make_input(vk, scan, ext | 0x0002)
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(down))
    time.sleep(duration / 1000.0)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(up))

# === 发键方式5: PostMessage (后台发键，不需要前台) ===
def send_post_message(hwnd, vk, duration=100):
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    scan = user32.MapVirtualKeyW(vk, 0)
    lparam_down = (scan << 16) | 1
    lparam_up = (scan << 16) | 0xC0000001
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lparam_down)
    time.sleep(duration / 1000.0)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, lparam_up)

# === 前台切换 ===
def force_foreground(hwnd):
    """强制切换前台窗口，返回是否成功"""
    old_fg = user32.GetForegroundWindow()
    game_thread = user32.GetWindowThreadProcessId(hwnd, None)
    cur_thread = kernel32.GetCurrentThreadId()
    attached = False
    if game_thread != 0 and game_thread != cur_thread:
        attached = user32.AttachThreadInput(cur_thread, game_thread, True)
    # Alt trick
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 0x0002, 0)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if user32.GetForegroundWindow() != hwnd:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
    time.sleep(0.08)
    fg_ok = user32.GetForegroundWindow() == hwnd
    # 恢复
    if attached:
        if old_fg and old_fg != hwnd:
            user32.SetForegroundWindow(old_fg)
        user32.AttachThreadInput(cur_thread, game_thread, False)
    return fg_ok

def vk_name(vk):
    names = {0x41:"A",0x42:"B",0x51:"Q",0x57:"W",0x45:"E",0x52:"R",
             0x31:"1",0x32:"2",0x33:"3",0x2E:"Delete",0x23:"End",
             0x20:"Space",0x0D:"Enter",0x1B:"Esc"}
    return names.get(vk, "VK=0x%02X" % vk)

def main():
    log("=" * 60)
    log("键盘控制测试工具启动")
    log("=" * 60)

    # 1. 环境检测
    log("--- 环境检测 ---")
    is_admin = check_admin()
    log("管理员权限: %s" % ("是" if is_admin else "否（如果游戏以管理员运行，发键会被UIPI拦截）"))
    fg_hwnd, fg_title = check_foreground()
    log("当前前台窗口: hwnd=%s title='%s'" % (fg_hwnd, fg_title))

    # 2. 列出窗口
    log("--- 可见窗口列表（前30个）---")
    wins = list_windows()
    game_hwnd = None
    for i, (hwnd, title) in enumerate(wins[:30]):
        log("  [%d] hwnd=%s title='%s'" % (i, hwnd, title))
        if "冒险岛" in title or "maple" in title.lower():
            game_hwnd = hwnd
    if game_hwnd:
        log("找到游戏窗口: hwnd=%s" % game_hwnd)
    else:
        log("未找到冒险岛窗口，将使用当前前台窗口测试")
        game_hwnd = fg_hwnd

    # 3. 前台切换测试
    log("--- 前台切换测试 ---")
    fg_ok = force_foreground(game_hwnd)
    log("强制切换前台结果: %s" % ("成功" if fg_ok else "失败（UIPI拦截？需要管理员权限？）"))

    # 4. 发键测试（每种方式发Q键，间隔2秒）
    test_vk = 0x51  # Q键
    log("--- 发键测试（测试键: %s，每种方式间隔3秒）---" % vk_name(test_vk))

    methods = [
        ("keybd_event(VK模式)", send_keybd_event_vk),
        ("keybd_event(扫描码模式)", send_keybd_event_scan),
        ("SendInput(VK模式)", send_input_vk),
        ("SendInput(扫描码模式)", send_input_scan),
    ]

    for name, func in methods:
        log("测试: %s ..." % name)
        try:
            # 先确保游戏在前台
            force_foreground(game_hwnd)
            time.sleep(0.1)
            func(test_vk, duration=120)
            log("  -> 已发送，请观察游戏是否有反应（角色是否做了Q键动作）")
        except Exception as e:
            log("  -> 异常: %s" % e)
        time.sleep(2)

    # 5. PostMessage后台发键测试
    log("--- PostMessage后台发键测试（不需要前台）---")
    try:
        send_post_message(game_hwnd, test_vk, duration=120)
        log("  -> PostMessage已发送到 hwnd=%s" % game_hwnd)
    except Exception as e:
        log("  -> 异常: %s" % e)

    # 6. 扩展键测试（Delete/End，用户的药品键）
    log("--- 扩展键测试（Delete=0x2E, End=0x23）---")
    for vk in (0x2E, 0x23):
        scan = user32.MapVirtualKeyW(vk, 0)
        ext = 0x0001
        log("  %s: scan=0x%02X ext=%d" % (vk_name(vk), scan, ext))
        try:
            force_foreground(game_hwnd)
            time.sleep(0.1)
            send_input_scan(vk, duration=120)
            log("    SendInput(扫描码)已发送 %s" % vk_name(vk))
        except Exception as e:
            log("    异常: %s" % e)
        time.sleep(1.5)

    # 7. 总结
    log("=" * 60)
    log("测试完成！结果已写入 keyboard_test.log")
    log("请观察游戏中哪种发键方式有反应，把结果告诉我")
    log("如果所有方式都没反应：")
    log("  1. 确认游戏是否在前台")
    log("  2. 右键本脚本/EXE → 以管理员身份运行（UIPI问题）")
    log("  3. 确认游戏内Q键绑定了技能/药品")
    log("=" * 60)

if __name__ == "__main__":
    main()
