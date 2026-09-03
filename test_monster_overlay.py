# -*- coding: utf-8 -*-
"""
怪物特征匹配测试 - 真实游戏窗口蒙板版
直接在游戏窗口上叠加透明蒙板，显示识别红框
一帧一次识别，实时显示
"""
import cv2
import numpy as np
import time
import win32gui
import win32ui
import win32con
from ctypes import windll, c_int, c_uint, c_void_p, byref, Structure, POINTER, WINFUNCTYPE
from ctypes.wintypes import DWORD, HWND, RECT, POINT, MSG

# === 配置 ===
TEMPLATE_PATH = "test_monster_template2.png"  # 怪物特征模板（15x16）
MATCH_THRESHOLD = 0.70  # 匹配阈值
GAME_WINDOW_TITLE = "冒险岛怀旧服"  # 游戏窗口标题

# === Win32 透明蒙板 ===
class MARGINS(Structure):
    _fields_ = [("cxLeftWidth", c_int), ("cxRightWidth", c_int),
                ("cyTopHeight", c_int), ("cyBottomHeight", c_int)]

class POINT(Structure):
    _fields_ = [("x", c_int), ("y", c_int)]

class MSG(Structure):
    _fields_ = [("hwnd", HWND), ("message", c_uint), ("wParam", c_void_p),
                ("lParam", c_void_p), ("time", DWORD), ("pt", POINT)]

user32 = windll.user32
dwmapi = windll.dwmapi
gdi32 = windll.gdi32

# 窗口过程回调
WNDPROC = WINFUNCTYPE(c_int, HWND, c_uint, c_void_p, c_void_p)

class OverlayWindow:
    """透明蒙板窗口，叠加在游戏窗口上"""
    def __init__(self, game_hwnd):
        self.game_hwnd = game_hwnd
        self.hwnd = None
        self.hdc = None
        self.mem_dc = None
        self.mem_bmp = None
        self.width = 0
        self.height = None
        self.match_rect = None  # 匹配到的矩形 (x1, y1, x2, y2)
        self.match_score = 0
        self.fps = 0
        self.frame_count = 0
        self.fps_start = time.time()
        
    def create(self):
        """创建透明蒙板窗口"""
        # 获取游戏窗口位置
        rect = RECT()
        user32.GetWindowRect(self.game_hwnd, byref(rect))
        self.width = rect.right - rect.left
        self.height = rect.bottom - rect.top
        
        # 创建分层窗口
        ws_ex = win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TOPMOST
        ws = win32con.WS_POPUP
        
        # 注册窗口类
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32gui.GetModuleHandle(None)
        wc.lpszClassName = "MonsterMatchOverlay"
        wc.lpfnWndProc = self._wnd_proc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = 0
        try:
            win32gui.RegisterClass(wc)
        except:
            pass
        
        # 创建窗口
        self.hwnd = win32gui.CreateWindowEx(
            ws_ex, "MonsterMatchOverlay", "怪物匹配蒙板",
            ws, rect.left, rect.top, self.width, self.height,
            0, 0, wc.hInstance, None
        )
        
        # 设置DWM扩展帧边界（全透明）
        margins = MARGINS(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea(self.hwnd, byref(margins))
        
        # 设置分层窗口属性（透明色=黑色，透明度=255）
        user32.SetLayeredWindowAttributes(self.hwnd, 0, 255, win32con.LWA_COLORKEY)
        
        # 显示窗口
        user32.ShowWindow(self.hwnd, win32con.SW_SHOW)
        user32.UpdateWindow(self.hwnd)
        
        # 获取DC
        self.hdc = user32.GetDC(self.hwnd)
        self.mem_dc = gdi32.CreateCompatibleDC(self.hdc)
        self.mem_bmp = gdi32.CreateCompatibleBitmap(self.hdc, self.width, self.height)
        gdi32.SelectObject(self.mem_dc, self.mem_bmp)
        
        print(f"蒙板窗口已创建: {self.width}x{self.height}, hwnd={self.hwnd}")
        
    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """窗口过程"""
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
    
    def update_position(self):
        """跟随游戏窗口位置"""
        rect = RECT()
        user32.GetWindowRect(self.game_hwnd, byref(rect))
        new_w = rect.right - rect.left
        new_h = rect.bottom - rect.top
        
        if new_w != self.width or new_h != self.height:
            # 窗口大小变化，重建位图
            self.width = new_w
            self.height = new_h
            gdi32.DeleteObject(self.mem_bmp)
            self.mem_bmp = gdi32.CreateCompatibleBitmap(self.hdc, self.width, self.height)
            gdi32.SelectObject(self.mem_dc, self.mem_bmp)
        
        user32.MoveWindow(self.hwnd, rect.left, rect.top, self.width, self.height, True)
    
    def clear(self):
        """清空蒙板（用黑色填充，黑色是透明色）"""
        brush = gdi32.CreateSolidBrush(0x000000)  # 黑色=透明
        rect = RECT(0, 0, self.width, self.height)
        user32.FillRect(self.mem_dc, byref(rect), brush)
        gdi32.DeleteObject(brush)
    
    def draw_rect(self, x1, y1, x2, y2, color, width=2):
        """画矩形框"""
        pen = gdi32.CreatePen(win32con.PS_SOLID, width, color)
        old_pen = gdi32.SelectObject(self.mem_dc, pen)
        old_brush = gdi32.SelectObject(self.mem_dc, gdi32.GetStockObject(win32con.NULL_BRUSH))
        
        gdi32.Rectangle(self.mem_dc, x1, y1, x2, y2)
        
        gdi32.SelectObject(self.mem_dc, old_pen)
        gdi32.SelectObject(self.mem_dc, old_brush)
        gdi32.DeleteObject(pen)
    
    def draw_text(self, x, y, text, color, size=16):
        """画文字"""
        font = gdi32.CreateFontW(size, 0, 0, 0, win32con.FW_BOLD, 0, 0, 0,
                                   win32con.DEFAULT_CHARSET, win32con.OUT_DEFAULT_PRECIS,
                                   win32con.CLIP_DEFAULT_PRECIS, win32con.DEFAULT_QUALITY,
                                   win32con.DEFAULT_PITCH | win32con.FF_DONTCARE, "微软雅黑")
        old_font = gdi32.SelectObject(self.mem_dc, font)
        gdi32.SetTextColor(self.mem_dc, color)
        gdi32.SetBkMode(self.mem_dc, win32con.TRANSPARENT)
        
        rect = RECT(x, y, x + 300, y + size + 10)
        user32.DrawTextW(self.mem_dc, text, -1, byref(rect), win32con.DT_LEFT | win32con.DT_TOP)
        
        gdi32.SelectObject(self.mem_dc, old_font)
        gdi32.DeleteObject(font)
    
    def present(self):
        """把内存DC的内容显示到窗口"""
        gdi32.BitBlt(self.hdc, 0, 0, self.width, self.height, self.mem_dc, 0, 0, win32con.SRCCOPY)
    
    def destroy(self):
        """销毁窗口"""
        if self.mem_bmp:
            gdi32.DeleteObject(self.mem_bmp)
        if self.mem_dc:
            gdi32.DeleteDC(self.mem_dc)
        if self.hdc:
            user32.ReleaseDC(self.hwnd, self.hdc)
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)

def capture_window(hwnd):
    """截取窗口客户区"""
    left, top, right, bot = win32gui.GetClientRect(hwnd)
    w = right - left
    h = bot - top
    if w <= 0 or h <= 0:
        return None
    
    hwndDC = win32gui.GetWindowDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()
    saveBitMap = win32ui.CreateBitmap()
    saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
    saveDC.SelectObject(saveBitMap)
    saveDC.BitBlt((0, 0), (w, h), mfcDC, (0, 0), win32con.SRCCOPY)
    
    bmpinfo = saveBitMap.GetInfo()
    bmpstr = saveBitMap.GetBitmapBits(True)
    img = np.frombuffer(bmpstr, dtype='uint8')
    try:
        img.shape = (bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4)
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    except:
        img = None
    
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
    game_hwnd = win32gui.FindWindow(None, GAME_WINDOW_TITLE)
    if not game_hwnd:
        print(f"错误：找不到游戏窗口 '{GAME_WINDOW_TITLE}'")
        return
    print(f"找到游戏窗口，句柄: {game_hwnd}")
    
    # 创建蒙板窗口
    overlay = OverlayWindow(game_hwnd)
    overlay.create()
    
    print("\n开始实时识别（一帧一次），按 q 退出...")
    print("在游戏中走动，看蒙板上的红框标在哪里")
    print("=" * 60)
    
    frame_count = 0
    fps_start = time.time()
    fps = 0
    
    try:
        while True:
            t0 = time.time()
            
            # 1. 跟随游戏窗口位置
            overlay.update_position()
            
            # 2. 截取游戏窗口
            frame = capture_window(game_hwnd)
            if frame is None:
                time.sleep(0.01)
                continue
            t1 = time.time()
            
            # 3. 模板匹配（一帧一次）
            result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            t2 = time.time()
            
            # 4. 清空蒙板
            overlay.clear()
            
            # 5. 画匹配结果
            if max_val >= MATCH_THRESHOLD:
                x1, y1 = max_loc
                x2, y2 = x1 + tw, y1 + th
                # 红框（BGR: 0,0,255 -> GDI: 0x0000FF）
                overlay.draw_rect(x1, y1, x2, y2, 0x0000FF, 2)
                overlay.draw_text(x1, y1 - 20, f"匹配度: {max_val:.3f}", 0x0000FF, 14)
                match_status = f"✓ 匹配 ({max_val:.3f}) 位置=({x1},{y1})"
            else:
                match_status = f"✗ 未匹配 (最高{max_val:.3f})"
            
            # 6. 画FPS和耗时
            capture_time = (t1 - t0) * 1000
            match_time = (t2 - t1) * 1000
            total_time = (t2 - t0) * 1000
            
            frame_count += 1
            if time.time() - fps_start >= 1.0:
                fps = frame_count / (time.time() - fps_start)
                frame_count = 0
                fps_start = time.time()
            
            overlay.draw_text(10, 10, f"FPS: {fps:.1f} (一帧一次)", 0x00FF00, 16)
            overlay.draw_text(10, 32, f"截图: {capture_time:.1f}ms  匹配: {match_time:.1f}ms  总: {total_time:.1f}ms", 0xFFFF00, 14)
            overlay.draw_text(10, 54, match_status, 0x00FFFF if max_val >= MATCH_THRESHOLD else 0x0000FF, 14)
            
            # 7. 显示蒙板
            overlay.present()
            
            # 每30帧打印
            if frame_count % 30 == 0 and frame_count > 0:
                print(f"FPS:{fps:.1f} 截图:{capture_time:.1f}ms 匹配:{match_time:.1f}ms 总:{total_time:.1f}ms {match_status}")
            
            # 处理消息（避免窗口无响应）
            msg = MSG()
            while user32.PeekMessageW(byref(msg), 0, 0, 0, 1):
                user32.TranslateMessage(byref(msg))
                user32.DispatchMessageW(byref(msg))
                if msg.message == win32con.WM_QUIT:
                    raise KeyboardInterrupt
            
            # 按q退出（检查控制台按键）
            if user32.GetAsyncKeyState(ord('Q')) & 0x8000:
                break
            
            time.sleep(0.001)  # 避免CPU占用过高
    
    except KeyboardInterrupt:
        pass
    finally:
        overlay.destroy()
        print("\n已退出")

if __name__ == "__main__":
    main()
