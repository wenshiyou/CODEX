"""
屏幕截图模块 - 使用 mss 高速截屏
预留接口，可根据游戏窗口自动定位截图区域
"""
import numpy as np
try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False


class ScreenCapture:
    def __init__(self, region=None):
        """
        region: [left, top, width, height]，None 则全屏
        """
        self.region = region
        self.sct = mss.mss() if HAS_MSS else None

    def capture(self):
        """截取屏幕，返回 BGR 格式的 numpy 数组"""
        if not HAS_MSS:
            raise RuntimeError("mss 未安装，请 pip install mss")

        if self.region:
            left, top, width, height = self.region
            monitor = {"left": left, "top": top, "width": width, "height": height}
        else:
            monitor = self.sct.monitors[1]  # 主屏

        frame = np.array(self.sct.grab(monitor))
        # mss 返回 BGRA，转 BGR
        return frame[:, :, :3]

    def set_region(self, region):
        self.region = region

    def find_window(self, window_title):
        """
        根据窗口标题查找窗口位置（需要 pywin32）
        返回 [left, top, width, height]
        """
        try:
            import win32gui
            hwnd = win32gui.FindWindow(None, window_title)
            if hwnd:
                rect = win32gui.GetWindowRect(hwnd)
                return [rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]]
        except ImportError:
            pass
        return None
