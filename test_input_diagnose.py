"""
输入方式诊断测试脚本
依次测试三种输入方式，观察角色是否移动，确定哪种方式有效：
  1. SendInput + 扫描码 + EXTENDEDKEY（推荐）
  2. SendInput + 虚拟键码
  3. PostMessage 直接发消息到游戏窗口

使用方法：
  1. 打开游戏，角色站在安全位置
  2. 运行本脚本
  3. 观察每次测试角色是否移动/跳跃
  4. 根据输出确定有效的输入方式
"""
import ctypes
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.controller import InputController

user32 = ctypes.windll.user32
WINDOW_TITLE = "冒险岛怀旧服"


def find_game_window():
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        print(f"未找到游戏窗口: {WINDOW_TITLE}")
        print("请确认游戏已启动且窗口标题正确")
        return None
    return hwnd


def test_method(ctrl, method_name, test_key="right", duration=1.5):
    """测试一种输入方式"""
    print(f"\n{'='*60}")
    print(f"测试: {method_name}")
    print(f"  按键: {test_key}, 持续: {duration}秒")
    print(f"  3秒后开始，请关注角色是否移动...")
    time.sleep(3)

    ctrl.set_foreground()
    time.sleep(0.5)

    t0 = time.time()
    ctrl.key_down(test_key)
    time.sleep(duration)
    ctrl.key_up(test_key)
    elapsed = time.time() - t0

    print(f"  完成，耗时 {elapsed:.2f}秒")
    print(f"  角色是否移动了？(是/否)")
    time.sleep(1)


def test_jump(ctrl, method_name, jump_key="alt"):
    """测试跳跃"""
    print(f"\n{'='*60}")
    print(f"测试跳跃: {method_name}")
    print(f"  跳跃键: {jump_key}")
    print(f"  2秒后开始跳3次...")
    time.sleep(2)

    ctrl.set_foreground()
    time.sleep(0.3)

    for i in range(3):
        ctrl.press_key(jump_key, duration=0.1)
        time.sleep(0.5)
        print(f"  跳了第{i+1}次")

    print(f"  角色是否跳跃了？(是/否)")
    time.sleep(1)


def main():
    print("=" * 60)
    print("冒险岛挂机脚本 - 输入方式诊断工具")
    print("=" * 60)

    hwnd = find_game_window()
    if not hwnd:
        return

    print(f"游戏窗口句柄: {hwnd}")

    # 先运行环境诊断
    ctrl = InputController(game_hwnd=hwnd, input_method="sendinput_scan", verbose=True)
    print("\n" + ctrl.diagnose())

    input("\n按 Enter 开始逐项测试...")

    # 测试1: SendInput + 扫描码 + EXTENDEDKEY
    ctrl1 = InputController(game_hwnd=hwnd, input_method="sendinput_scan", verbose=True)
    test_method(ctrl1, "SendInput + 扫描码 + EXTENDEDKEY", "right", 1.5)
    test_jump(ctrl1, "SendInput + 扫描码", "alt")

    # 测试2: SendInput + 虚拟键码
    ctrl2 = InputController(game_hwnd=hwnd, input_method="sendinput_vk", verbose=True)
    test_method(ctrl2, "SendInput + 虚拟键码", "right", 1.5)
    test_jump(ctrl2, "SendInput + 虚拟键码", "alt")

    # 测试3: PostMessage
    ctrl3 = InputController(game_hwnd=hwnd, input_method="postmessage", verbose=True)
    test_method(ctrl3, "PostMessage（直接发窗口消息）", "right", 1.5)
    test_jump(ctrl3, "PostMessage", "alt")

    print("\n" + "=" * 60)
    print("测试完成！")
    print("请根据观察结果，在 config.json 中设置 input_method:")
    print("  - 如果 SendInput+扫描码有效: input_method = 'sendinput_scan'")
    print("  - 如果 SendInput+虚拟键码有效: input_method = 'sendinput_vk'")
    print("  - 如果 PostMessage有效: input_method = 'postmessage'")
    print("  - 如果都无效: 可能需要以管理员身份运行脚本，或游戏有反作弊拦截")
    print("=" * 60)


if __name__ == "__main__":
    main()
