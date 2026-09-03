# -*- coding: utf-8 -*-
"""
单独的怪物特征模板匹配测试程序
只做识别，不和别的功能弄在一起
功能：截取游戏窗口 → 怪物特征模板匹配 → 显示匹配结果和耗时
一帧一次识别
"""
import cv2
import numpy as np
import time
import win32gui
import win32ui
import win32con

# === 配置 ===
TEMPLATE_PATH = "test_monster_template2.png"  # 怪物特征模板（15x16）
MATCH_THRESHOLD = 0.70  # 匹配阈值
GAME_WINDOW_TITLE = "冒险岛怀旧服"  # 游戏窗口标题

def capture_window(hwnd):
    """截取窗口（BitBlt方式，比PrintWindow更稳定）"""
    # 获取窗口客户区大小
    left, top, right, bot = win32gui.GetClientRect(hwnd)
    w = right - left
    h = bot - top
    if w <= 0 or h <= 0:
        return None
    
    # 获取窗口DC
    hwndDC = win32gui.GetWindowDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    
    # 创建兼容DC和位图
    saveDC = mfcDC.CreateCompatibleDC()
    saveBitMap = win32ui.CreateBitmap()
    saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
    saveDC.SelectObject(saveBitMap)
    
    # BitBlt截图
    saveDC.BitBlt((0, 0), (w, h), mfcDC, (0, 0), win32con.SRCCOPY)
    
    # 获取位图数据
    bmpinfo = saveBitMap.GetInfo()
    bmpstr = saveBitMap.GetBitmapBits(True)
    
    # 转换为numpy数组
    img = np.frombuffer(bmpstr, dtype='uint8')
    try:
        img.shape = (bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4)
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    except:
        img = None
    
    # 释放资源
    win32gui.DeleteObject(saveBitMap.GetHandle())
    saveDC.DeleteDC()
    mfcDC.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwndDC)
    
    return img

def main():
    # 加载模板
    template = cv2.imread(TEMPLATE_PATH)
    if template is None:
        print("错误：找不到模板文件", TEMPLATE_PATH)
        return
    th, tw = template.shape[:2]
    print(f"模板尺寸: {tw}x{th}")
    
    # 查找游戏窗口
    hwnd = win32gui.FindWindow(None, GAME_WINDOW_TITLE)
    if not hwnd:
        print(f"错误：找不到游戏窗口 '{GAME_WINDOW_TITLE}'")
        # 列出所有窗口标题
        print("当前窗口列表：")
        def enum_callback(hwnd, extra):
            title = win32gui.GetWindowText(hwnd)
            if title and "冒险岛" in title:
                print(f"  找到: {title} (hwnd={hwnd})")
        win32gui.EnumWindows(enum_callback, None)
        return
    print(f"找到游戏窗口，句柄: {hwnd}")
    
    # 创建显示窗口
    cv2.namedWindow("怪物特征匹配测试（一帧一次）", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("怪物特征匹配测试（一帧一次）", 800, 600)
    
    frame_count = 0
    fps_start = time.time()
    fps = 0
    
    print("\n开始识别（一帧一次），按 q 退出...")
    print("=" * 60)
    
    while True:
        t0 = time.time()
        
        # 1. 截取游戏窗口
        frame = capture_window(hwnd)
        if frame is None:
            print("截图失败，跳过此帧")
            time.sleep(0.01)
            continue
        t1 = time.time()
        
        # 2. 模板匹配（一帧一次）
        result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        t2 = time.time()
        
        # 3. 画匹配框
        display = frame.copy()
        if max_val >= MATCH_THRESHOLD:
            top_left = max_loc
            bottom_right = (top_left[0] + tw, top_left[1] + th)
            cv2.rectangle(display, top_left, bottom_right, (0, 0, 255), 2)
            cv2.putText(display, f"匹配度: {max_val:.3f}", (top_left[0], top_left[1]-10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            match_status = f"✓ 匹配成功 ({max_val:.3f}) 位置=({top_left[0]},{top_left[1]})"
        else:
            match_status = f"✗ 未匹配 (最高{max_val:.3f})"
        
        # 4. 计算耗时和FPS
        capture_time = (t1 - t0) * 1000
        match_time = (t2 - t1) * 1000
        total_time = (t2 - t0) * 1000
        
        frame_count += 1
        if time.time() - fps_start >= 1.0:
            fps = frame_count / (time.time() - fps_start)
            frame_count = 0
            fps_start = time.time()
        
        # 5. 显示信息
        info_y = 30
        cv2.putText(display, f"FPS: {fps:.1f} (一帧一次)", (10, info_y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        info_y += 25
        cv2.putText(display, f"截图耗时: {capture_time:.1f}ms", (10, info_y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        info_y += 22
        cv2.putText(display, f"匹配耗时: {match_time:.1f}ms", (10, info_y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        info_y += 22
        cv2.putText(display, f"总耗时: {total_time:.1f}ms", (10, info_y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        info_y += 22
        color = (0, 255, 0) if max_val >= MATCH_THRESHOLD else (0, 0, 255)
        cv2.putText(display, match_status, (10, info_y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        
        # 6. 显示
        cv2.imshow("怪物特征匹配测试（一帧一次）", display)
        
        # 每30帧打印一次
        if frame_count % 30 == 0 and frame_count > 0:
            print(f"FPS:{fps:.1f} 截图:{capture_time:.1f}ms 匹配:{match_time:.1f}ms 总:{total_time:.1f}ms {match_status}")
        
        # 按q退出
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    cv2.destroyAllWindows()
    print("\n已退出")

if __name__ == "__main__":
    main()
