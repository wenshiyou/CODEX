# -*- coding: utf-8 -*-
"""测试：用pygame创建透明置顶窗口，显示准星，可拖拽到屏幕任意位置"""
import pygame
import win32gui
import win32con
import win32api
import sys

def test_crosshair_pygame():
    """测试pygame透明置顶准星窗口"""
    # 初始化pygame
    pygame.init()
    
    # 创建窗口
    screen = pygame.display.set_mode((100, 100), pygame.NOFRAME)
    
    # 获取窗口句柄
    hwnd = pygame.display.get_wm_info()["window"]
    
    # 设置窗口置顶
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                           win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
    
    # 设置窗口透明（白色透明）
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE,
                            win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) | win32con.WS_EX_LAYERED)
    win32gui.SetLayeredWindowAttributes(hwnd, win32api.RGB(255, 255, 255), 0, win32con.LWA_COLORKEY)
    
    # 初始位置在屏幕中央
    win32gui.SetWindowPos(hwnd, 0, 500, 300, 0, 0,
                           win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
    
    print("测试窗口已创建，5秒后自动关闭")
    print("请尝试拖拽准星窗口，看看能否拖到屏幕任意位置")
    
    # 主循环
    start_time = pygame.time.get_ticks()
    dragging = False
    drag_offset = (0, 0)
    
    while pygame.time.get_ticks() - start_time < 5000:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    dragging = True
                    drag_offset = event.pos
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    dragging = False
            elif event.type == pygame.MOUSEMOTION:
                if dragging:
                    # 移动窗口
                    x, y = win32gui.GetCursorPos()
                    win32gui.SetWindowPos(hwnd, 0, x - drag_offset[0], y - drag_offset[1], 0, 0,
                                           win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
        
        # 清屏（白色背景，会被透明化）
        screen.fill((255, 255, 255))
        
        # 绘制准星（红色）
        pygame.draw.circle(screen, (255, 0, 0), (50, 50), 15, 2)
        pygame.draw.line(screen, (255, 0, 0), (20, 50), (35, 50), 2)
        pygame.draw.line(screen, (255, 0, 0), (65, 50), (80, 50), 2)
        pygame.draw.line(screen, (255, 0, 0), (50, 20), (50, 35), 2)
        pygame.draw.line(screen, (255, 0, 0), (50, 65), (50, 80), 2)
        
        pygame.display.flip()
        pygame.time.delay(16)
    
    pygame.quit()
    print("测试完成")

if __name__ == "__main__":
    import win32api
    test_crosshair_pygame()
