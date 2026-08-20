"""
Minimap Route Recorder - Global Hotkey Version
Auto lock game window + blue border detection (projection) + ROI dot tracking
Hotkeys: F5=platform F6=ladder F7=clear F8=save (global, no window switch needed)
"""
import ctypes
import struct
import mss
import numpy as np
import cv2
import os
import json
import time
import sys
import queue

# 无缓冲输出，方便实时看日志
sys.stdout.reconfigure(line_buffering=True)

os.chdir(os.path.dirname(os.path.abspath(__file__)))

DISPLAY_SCALE = 1
WINDOW_TITLE = "冒险岛怀旧服"
FIXED_W = 340
FIXED_H = 250
YELLOW_H_LOW = 25
YELLOW_H_HIGH = 35
YELLOW_S_LOW = 120
YELLOW_V_LOW = 180

VK_F5 = 0x74
VK_F6 = 0x75
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
PLATFORMS_FILE = os.path.join(DATA_DIR, "minimap_platforms.json")
LADDERS_FILE = os.path.join(DATA_DIR, "minimap_ladders.json")
REGION_FILE = os.path.join(DATA_DIR, "minimap_region.json")

COLOR_PLATFORM = (0, 255, 0)
COLOR_LADDER = (255, 100, 0)
COLOR_RECORDING = (0, 0, 255)
COLOR_PLAYER = (0, 255, 255)

user32 = ctypes.windll.user32


def key_pressed(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class GlobalHotkeyListener:
    """低级键盘钩子全局热键（主线程版），绕过 UIPI，游戏前台也能捕获"""
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104

    def __init__(self, vk_list):
        self.vk_list = set(vk_list)
        self.events = queue.Queue()
        self._hook = None
        self._hook_proc_ref = None

    def _hook_proc(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
            vk = ctypes.cast(lParam, ctypes.POINTER(ctypes.c_ulong))[0] & 0xFF
            if vk in self.vk_list:
                self.events.put(vk)
        return user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

    def install(self):
        """在主线程安装钩子，返回是否成功"""
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p)
        self._hook_proc_ref = HOOKPROC(self._hook_proc)
        kernel32 = ctypes.windll.kernel32
        self._hook = user32.SetWindowsHookExW(
            self.WH_KEYBOARD_LL, self._hook_proc_ref,
            kernel32.GetModuleHandleW(None), 0
        )
        return bool(self._hook)

    def pump(self):
        """每帧调用，处理钩子消息（必须在安装钩子的线程调用）"""
        msg = ctypes.c_void_p()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
            if msg.value == 0x0012:  # WM_QUIT
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def uninstall(self):
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def get_events(self):
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                break
        return events


class MinimapRouteRecorder:
    def __init__(self):
        self.sct = mss.mss()
        self.hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if not self.hwnd:
            raise RuntimeError("Game window not found: " + WINDOW_TITLE)
        self._update_window_rect()
        self._detect_minimap()

        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []
        self.platforms = self._load(PLATFORMS_FILE, "platforms")
        self.ladders = self._load(LADDERS_FILE, "ladders")
        self.last_player_pos = None
        self.frame_count = 0

        # 低级键盘钩子全局热键（绕过 UIPI，游戏前台也能触发）
        self.hotkey = GlobalHotkeyListener([VK_F5, VK_F6, VK_F7, VK_F8, VK_F9])
        ok = self.hotkey.install()
        print("Hotkey hook installed:", ok)

        print("Map area:", self.map_area_rect["width"], "x", self.map_area_rect["height"])
        print("Loaded:", len(self.platforms), "platforms,", len(self.ladders), "ladders")
        print("Global: F5=platform F6=ladder F7=clear F8=save F9=manual select")
        print("Window: M=manual select R=redetect Q=quit\n")

    def _update_window_rect(self):
        rect = ctypes.create_string_buffer(16)
        user32.GetWindowRect(self.hwnd, rect)
        l, t, r, b = struct.unpack("llll", rect.raw)
        self.window_rect = {"left": l, "top": t, "width": r - l, "height": b - t}

    def _load_region(self):
        """从文件加载已保存的小地图区域，成功返回 True"""
        if not os.path.exists(REGION_FILE):
            return False
        try:
            with open(REGION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "map" in data and "minimap" in data:
                self.map_area_rect = data["map"]
                self.minimap_rect = data["minimap"]
                print("Loaded saved region:", self.map_area_rect["width"], "x", self.map_area_rect["height"])
                return True
        except Exception:
            pass
        return False

    def _detect_minimap(self):
        """三特征点定位：左=小地图文字左，右=大地图文字右，下=350px内蓝色圆弧"""
        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]

        # 懒加载模板
        if not hasattr(self, '_tpl_minimap'):
            base = os.path.join(os.path.dirname(__file__), "data", "templates")
            self._tpl_minimap = cv2.imread(os.path.join(base, "minimap_title.png"))
            self._tpl_bigmap = cv2.imread(os.path.join(base, "bigmap_title.png"))
            self._tpl_arc = cv2.imread(os.path.join(base, "minimap_blue_arc.png"))
            print("Templates loaded: mini%dx%d big%dx%d arc%dx%d" % (
                self._tpl_minimap.shape[1], self._tpl_minimap.shape[0],
                self._tpl_bigmap.shape[1], self._tpl_bigmap.shape[0],
                self._tpl_arc.shape[1], self._tpl_arc.shape[0]))

        tpl_m, tpl_b, tpl_a = self._tpl_minimap, self._tpl_bigmap, self._tpl_arc
        mh, mw = tpl_m.shape[:2]
        bh, bw = tpl_b.shape[:2]
        ah, aw = tpl_a.shape[:2]

        # 1. 找"小地图"文字
        roi_m = frame[0:120, 0:300]
        res_m = cv2.matchTemplate(roi_m, tpl_m, cv2.TM_CCOEFF_NORMED)
        _, val_m, _, loc_m = cv2.minMaxLoc(res_m)
        mini_x, mini_y = loc_m
        print("小地图: val=%.3f at (%d,%d)" % (val_m, mini_x, mini_y))
        if val_m < 0.55:
            print("小地图匹配度过低，回退扫描线法")
            self._detect_minimap_scanline()
            return

        # 2. 找"大地图"文字（小地图右侧同行）
        roi_b_x1 = mini_x + mw
        roi_b_x2 = min(fw, mini_x + 200)
        roi_b = frame[max(0, mini_y - 5):mini_y + mh + 10, roi_b_x1:roi_b_x2]
        res_b = cv2.matchTemplate(roi_b, tpl_b, cv2.TM_CCOEFF_NORMED)
        _, val_b, _, loc_b = cv2.minMaxLoc(res_b)
        big_x = roi_b_x1 + loc_b[0]
        big_y = max(0, mini_y - 5) + loc_b[1]
        print("大地图: val=%.3f at (%d,%d)" % (val_b, big_x, big_y))

        # 3. 边界：左=小地图左，右=大地图右，上=小地图下
        left = mini_x
        right = big_x + bw
        top = mini_y + mh
        print("边界: L=%d R=%d T=%d W=%d" % (left, right, top, right - left))

        # 4. top向下350px内找右下角蓝色圆弧
        arc_y1 = top
        arc_y2 = min(fh, top + 350)
        arc_x1 = max(0, right - 60)
        arc_x2 = min(fw, right + 20)
        roi_a = frame[arc_y1:arc_y2, arc_x1:arc_x2]
        res_a = cv2.matchTemplate(roi_a, tpl_a, cv2.TM_CCOEFF_NORMED)
        _, val_a, _, loc_a = cv2.minMaxLoc(res_a)
        arc_x = arc_x1 + loc_a[0]
        arc_y = arc_y1 + loc_a[1]
        bottom = arc_y + ah
        print("圆弧: val=%.3f at (%d,%d) bottom=%d" % (val_a, arc_x, arc_y, bottom))

        # 5. 计算区域
        self.minimap_rect = {
            "left": left, "top": mini_y,
            "width": right - left, "height": bottom - mini_y
        }
        self.map_area_rect = {
            "left": left + 3,
            "top": top + 24,
            "width": right - left - 6,
            "height": bottom - top - 27
        }
        self._save_region()

        # 调试图
        dbg = frame.copy()
        cv2.rectangle(dbg, (mini_x, mini_y), (mini_x + mw, mini_y + mh), (0, 0, 255), 1)
        cv2.rectangle(dbg, (big_x, big_y), (big_x + bw, big_y + bh), (0, 165, 255), 1)
        cv2.rectangle(dbg, (arc_x, arc_y), (arc_x + aw, arc_y + ah), (0, 255, 255), 1)
        cv2.rectangle(dbg, (self.minimap_rect["left"], self.minimap_rect["top"]),
                      (self.minimap_rect["left"] + self.minimap_rect["width"],
                       self.minimap_rect["top"] + self.minimap_rect["height"]), (255, 0, 0), 1)
        mr = self.map_area_rect
        cv2.rectangle(dbg, (mr["left"], mr["top"]),
                      (mr["left"] + mr["width"], mr["top"] + mr["height"]), (0, 255, 0), 2)
        cv2.imwrite("debug_detect.png", dbg)
        print("Map area: %dx%d" % (self.map_area_rect["width"], self.map_area_rect["height"]))

    def _detect_minimap(self):
        """三特征点定位：左=小地图文字左，右=大地图文字右，下=350px内蓝色圆弧"""
        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]

        # 懒加载模板
        if not hasattr(self, '_tpl_minimap'):
            base = os.path.join(os.path.dirname(__file__), "data", "templates")
            self._tpl_minimap = cv2.imread(os.path.join(base, "minimap_title.png"))
            self._tpl_bigmap = cv2.imread(os.path.join(base, "bigmap_title.png"))
            self._tpl_arc = cv2.imread(os.path.join(base, "minimap_blue_arc.png"))
            print("Templates loaded")

        tpl_m = self._tpl_minimap
        tpl_b = self._tpl_bigmap
        tpl_a = self._tpl_arc
        mh, mw = tpl_m.shape[:2]
        bh, bw = tpl_b.shape[:2]
        ah, aw = tpl_a.shape[:2]

        # 1. 找"小地图"文字
        roi_m = frame[0:120, 0:300]
        res_m = cv2.matchTemplate(roi_m, tpl_m, cv2.TM_CCOEFF_NORMED)
        _, val_m, _, loc_m = cv2.minMaxLoc(res_m)
        mini_x, mini_y = loc_m
        print("小地图 match: val=%.3f at (%d,%d)" % (val_m, mini_x, mini_y))

        if val_m < 0.6:
            print("WARNING: 小地图 match too low (%.3f), fallback scanline" % val_m)
            self._detect_minimap_scanline()
            return

        # 2. 找"大地图"文字
        roi_b_x1 = mini_x + mw
        roi_b_x2 = min(fw, mini_x + 200)
        roi_b = frame[mini_y - 5:mini_y + mh + 10, roi_b_x1:roi_b_x2]
        res_b = cv2.matchTemplate(roi_b, tpl_b, cv2.TM_CCOEFF_NORMED)
        _, val_b, _, loc_b = cv2.minMaxLoc(res_b)
        big_x = roi_b_x1 + loc_b[0]
        big_y = mini_y - 5 + loc_b[1]
        print("大地图 match: val=%.3f at (%d,%d)" % (val_b, big_x, big_y))

        # 3. 左右边界
        left = mini_x
        right = big_x + bw
        top = mini_y + mh
        print("边界: left=%d right=%d top=%d width=%d" % (left, right, top, right - left))

        # 4. top向下350px内找右下角蓝色圆弧
        arc_y1 = top
        arc_y2 = min(fh, top + 350)
        arc_x1 = max(0, right - 60)
        arc_x2 = min(fw, right + 20)
        roi_a = frame[arc_y1:arc_y2, arc_x1:arc_x2]
        res_a = cv2.matchTemplate(roi_a, tpl_a, cv2.TM_CCOEFF_NORMED)
        _, val_a, _, loc_a = cv2.minMaxLoc(res_a)
        arc_x = arc_x1 + loc_a[0]
        arc_y = arc_y1 + loc_a[1]
        bottom = arc_y + ah
        print("圆弧 match: val=%.3f at (%d,%d), bottom=%d" % (val_a, arc_x, arc_y, bottom))

        # 5. 小地图外框
        self.minimap_rect = {
            "left": left, "top": mini_y,
            "width": right - left, "height": bottom - mini_y
        }
        # 6. 地图内容区：去掉标题栏(下移50px)和左右下边框
        self.map_area_rect = {
            "left": left + 3,
            "top": top + 50,
            "width": right - left - 6,
            "height": bottom - top - 50 - 3
        }

        self._save_region()

        # 调试图
        dbg = frame.copy()
        cv2.rectangle(dbg, (mini_x, mini_y), (mini_x + mw, mini_y + mh), (0, 0, 255), 1)
        cv2.rectangle(dbg, (big_x, big_y), (big_x + bw, big_y + bh), (0, 165, 255), 1)
        cv2.rectangle(dbg, (arc_x, arc_y), (arc_x + aw, arc_y + ah), (0, 255, 255), 1)
        cv2.rectangle(dbg, (self.minimap_rect["left"], self.minimap_rect["top"]),
                      (self.minimap_rect["left"] + self.minimap_rect["width"],
                       self.minimap_rect["top"] + self.minimap_rect["height"]), (255, 0, 0), 1)
        mr = self.map_area_rect
        cv2.rectangle(dbg, (mr["left"], mr["top"]),
                      (mr["left"] + mr["width"], mr["top"] + mr["height"]), (0, 255, 0), 2)
        cv2.imwrite("debug_detect.png", dbg)
        print("Map area:", self.map_area_rect["width"], "x", self.map_area_rect["height"])

    def _detect_minimap_scanline(self):
        """【兜底】扫描线法：直接巡最外面的细边框（含圆角），标题栏包含在内"""
        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]

        # 搜索区域：窗口左上角小范围（小地图固定在左上角，避免扫到游戏背景）
        roi_top = 8
        roi_bottom = min(fh, 260)
        roi_right = min(fw, 220)
        roi = frame[roi_top:roi_bottom, 0:roi_right].copy()
        roi_h, roi_w = roi.shape[:2]

        # 灰度 + 亮度阈值找灰白色细边框
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        def scan_h(start, end, step, threshold=130, ratio=0.55):
            for y in range(start, end, step):
                if y < 0 or y >= roi_h:
                    break
                if np.sum(gray[y, :] > threshold) > roi_w * ratio:
                    return y
            return None

        def scan_v(start, end, step, y1, y2, threshold=130, ratio=0.45):
            for x in range(start, end, step):
                if x < 0 or x >= roi_w:
                    break
                if np.sum(gray[y1:y2, x] > threshold) > (y2 - y1) * ratio:
                    return x
            return None

        # 顶部：从上往下第一条亮线
        top_y = scan_h(0, roi_h // 2, 1, 130, 0.55)

        # 左右边框先找（用顶部以下的范围）
        if top_y is not None:
            mid_y1 = top_y + 20
            mid_y2 = min(roi_h - 5, top_y + 180)
            left_x = scan_v(0, roi_w // 2, 1, mid_y1, mid_y2, 130, 0.45)
            right_x = scan_v(roi_w - 1, roi_w // 2, -1, mid_y1, mid_y2, 130, 0.45)
        else:
            left_x = scan_v(0, roi_w // 2, 1, 20, roi_h - 5, 130, 0.45)
            right_x = scan_v(roi_w - 1, roi_w // 2, -1, 20, roi_h - 5, 130, 0.45)

        # 底部：在合理范围内找（小地图高宽比约1:1，高度≈宽度±30）
        if top_y is not None and left_x is not None and right_x is not None:
            est_h = right_x - left_x  # 估计高度≈宽度
            bottom_search_top = top_y + max(120, est_h - 30)
            bottom_search_bottom = top_y + min(roi_h - top_y - 5, est_h + 40)
            bottom_y = scan_h(bottom_search_bottom, bottom_search_top, -1, 120, 0.45)
        else:
            bottom_y = scan_h(roi_h - 1, 60, -1, 130, 0.50)

        # 兜底
        if top_y is None: top_y = 5
        if bottom_y is None: bottom_y = roi_h - 5
        if left_x is None: left_x = 3
        if right_x is None: right_x = roi_w - 5

        print("Scan border: top=%d bottom=%d left=%d right=%d" % (top_y, bottom_y, left_x, right_x))

        # 小地图外框 = 扫描线粗定位（含标题栏）
        self.minimap_rect = {
            "left": left_x,
            "top": roi_top + top_y,
            "width": right_x - left_x,
            "height": bottom_y - top_y
        }

        # ===== 第二步：颜色检测精修，裁掉多余边框 =====
        # 截取粗定位区域，用颜色分析找真实内容边界
        coarse = frame[roi_top + top_y:roi_top + bottom_y, left_x:right_x].copy()
        ch, cw = coarse.shape[:2]
        hsv_c = cv2.cvtColor(coarse, cv2.COLOR_BGR2HSV)
        # 内容像素：非亮边框（亮度<160 或 饱和度>50），即深色背景+彩色平台+光点
        content_mask = ((hsv_c[:, :, 2] < 160) | (hsv_c[:, :, 1] > 50)).astype(np.uint8) * 255
        content_mask = cv2.morphologyEx(content_mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

        def find_content_edge(mask, axis, start, end, step, ratio=0.15):
            """沿 axis=0(行) 或 axis=1(列) 扫描，找第一个内容占比>ratio的位置"""
            h_m, w_m = mask.shape
            if axis == 0:
                for i in range(start, end, step):
                    if np.sum(mask[i, :] > 0) > w_m * ratio:
                        return i
            else:
                for i in range(start, end, step):
                    if np.sum(mask[:, i] > 0) > h_m * ratio:
                        return i
            return None

        # 精修四边（从粗边框向内找内容边界）
        refine_top = find_content_edge(content_mask, 0, 0, ch // 2, 1, 0.15)
        refine_bottom = find_content_edge(content_mask, 0, ch - 1, ch // 3, -1, 0.15)
        refine_left = find_content_edge(content_mask, 1, 0, cw // 2, 1, 0.10)
        refine_right = find_content_edge(content_mask, 1, cw - 1, cw // 2, -1, 0.10)

        # 精修失败则用粗定位 + 固定内边距
        if refine_left is None: refine_left = 8
        if refine_top is None: refine_top = 2
        if refine_right is None: refine_right = cw - 2
        if refine_bottom is None: refine_bottom = ch - 2

        print("Refine: L=%d T=%d R=%d B=%d (coarse %dx%d)" % (
            refine_left, refine_top, refine_right, refine_bottom, cw, ch))

        # 地图区域 = 精修后的内容区（窗口内坐标）
        self.map_area_rect = {
            "left": left_x + refine_left,
            "top": roi_top + top_y + refine_top,
            "width": refine_right - refine_left,
            "height": refine_bottom - refine_top
        }

        self._save_region()
        dbg = frame.copy()
        cv2.rectangle(dbg, (self.minimap_rect["left"], self.minimap_rect["top"]),
                      (self.minimap_rect["left"] + self.minimap_rect["width"],
                       self.minimap_rect["top"] + self.minimap_rect["height"]), (255, 0, 0), 1)
        mr = self.map_area_rect
        cv2.rectangle(dbg, (mr["left"], mr["top"]),
                      (mr["left"] + mr["width"], mr["top"] + mr["height"]), (0, 255, 0), 1)
        cv2.imwrite("debug_detect.png", dbg)
        print("Map area:", self.map_area_rect["width"], "x", self.map_area_rect["height"])

    def _save_region(self):
        with open(REGION_FILE, "w", encoding="utf-8") as f:
            json.dump({"minimap": self.minimap_rect, "map": self.map_area_rect}, f, indent=2)

    def _load(self, path, key):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f).get(key, [])
            except Exception:
                return []
        return []

    def _save(self):
        with open(PLATFORMS_FILE, "w", encoding="utf-8") as f:
            json.dump({"platforms": self.platforms, "count": len(self.platforms)}, f, indent=2)
        with open(LADDERS_FILE, "w", encoding="utf-8") as f:
            json.dump({"ladders": self.ladders, "count": len(self.ladders)}, f, indent=2)
        print("Saved:", len(self.platforms), "platforms,", len(self.ladders), "ladders")

    def _capture_window(self):
        r = self.window_rect
        return np.array(self.sct.grab(r))[:, :, :3]

    def _capture_map(self):
        r = self.map_area_rect
        reg = {
            "left": self.window_rect["left"] + r["left"],
            "top": self.window_rect["top"] + r["top"],
            "width": r["width"],
            "height": r["height"]
        }
        return np.array(self.sct.grab(reg))[:, :, :3]

    def find_player_dot(self, map_area):
        hsv = cv2.cvtColor(map_area, cv2.COLOR_BGR2HSV)
        lower = np.array([YELLOW_H_LOW, YELLOW_S_LOW, YELLOW_V_LOW])
        upper = np.array([YELLOW_H_HIGH, 255, 255])
        h, w = map_area.shape[:2]

        if self.last_player_pos:
            cx, cy = self.last_player_pos
            x1 = max(0, cx - 12)
            y1 = max(0, cy - 12)
            x2 = min(w, cx + 13)
            y2 = min(h, cy + 13)
            roi_hsv = hsv[y1:y2, x1:x2]
            mask = cv2.inRange(roi_hsv, lower, upper)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 30]
            if valid:
                largest = max(valid, key=cv2.contourArea)
                M = cv2.moments(largest)
                if M["m00"] > 0:
                    px = int(M["m10"] / M["m00"]) + x1
                    py = int(M["m01"] / M["m00"]) + y1
                    self.last_player_pos = (px, py)
                    return (px, py)

        mask = cv2.inRange(hsv, lower, upper)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in cnts if 1 <= cv2.contourArea(c) <= 30]
        if valid:
            largest = max(valid, key=cv2.contourArea)
            M = cv2.moments(largest)
            if M["m00"] > 0:
                px = int(M["m10"] / M["m00"])
                py = int(M["m01"] / M["m00"])
                self.last_player_pos = (px, py)
                return (px, py)
        self.last_player_pos = None
        return None

    def extract_platform(self, points):
        if len(points) < 2:
            return []
        ys = sorted(set(int(p[1] // 3) * 3 for p in points))
        clusters = []
        cur = [ys[0]]
        for y in ys[1:]:
            if y - cur[-1] <= 6:
                cur.append(y)
            else:
                clusters.append(cur)
                cur = [y]
        clusters.append(cur)
        platforms = []
        for cl in clusters:
            cp = [p for p in points if int(p[1] // 3) * 3 in cl]
            if len(cp) < 2:
                continue
            xs = [p[0] for p in cp]
            y_base = sum(p[1] for p in cp) / len(cp)
            platforms.append({
                "id": len(self.platforms) + len(platforms),
                "x_min": float(min(xs)),
                "x_max": float(max(xs)),
                "y_base": float(y_base)
            })
        return platforms

    def extract_ladder(self, points):
        if len(points) < 2:
            return []
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return [{
            "id": len(self.ladders),
            "x": float(sorted(xs)[len(xs) // 2]),
            "y_top": float(min(ys)),
            "y_bottom": float(max(ys))
        }]

    def _check_hotkeys(self):
        for vk in self.hotkey.get_events():
            if vk == VK_F5:
                if self.recording_ladder:
                    print("Stop ladder first (F6)")
                elif self.recording_platform:
                    np_ = self.extract_platform(self.platform_points)
                    if np_:
                        self.platforms.extend(np_)
                        print("Extracted", len(np_), "platforms,", len(self.platform_points), "points")
                    else:
                        print("No platform extracted,", len(self.platform_points), "points")
                    self.platform_points = []
                    self.recording_platform = False
                else:
                    self.recording_platform = True
                    self.platform_points = []
                    print("Platform recording started...")
            elif vk == VK_F6:
                if self.recording_platform:
                    print("Stop platform first (F5)")
                elif self.recording_ladder:
                    nl = self.extract_ladder(self.ladder_points)
                    if nl:
                        self.ladders.extend(nl)
                        print("Extracted", len(nl), "ladders,", len(self.ladder_points), "points")
                    else:
                        print("No ladder extracted,", len(self.ladder_points), "points")
                    self.ladder_points = []
                    self.recording_ladder = False
                else:
                    self.recording_ladder = True
                    self.ladder_points = []
                    print("Ladder recording started...")
            elif vk == VK_F7:
                self.platform_points = []
                self.ladder_points = []
                print("Cleared")
            elif vk == VK_F8:
                self._save()
            elif vk == VK_F9:
                print("Manual select triggered (F9)")
                self.manual_select_region()

    def draw(self, map_area, player_pos):
        display = map_area.copy()
        h, w = display.shape[:2]
        for p in self.platforms:
            x1 = int(max(0, min(p["x_min"], w - 1)))
            x2 = int(max(0, min(p["x_max"], w - 1)))
            y = int(max(0, min(p["y_base"], h - 1)))
            cv2.line(display, (x1, y), (x2, y), COLOR_PLATFORM, 1)
        for l in self.ladders:
            x = int(max(0, min(l["x"], w - 1)))
            y1 = int(max(0, min(l["y_top"], h - 1)))
            y2 = int(max(0, min(l["y_bottom"], h - 1)))
            cv2.line(display, (x, y1), (x, y2), COLOR_LADDER, 1)
        if self.recording_platform and len(self.platform_points) > 1:
            cv2.polylines(display, [np.array(self.platform_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        if self.recording_ladder and len(self.ladder_points) > 1:
            cv2.polylines(display, [np.array(self.ladder_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        if player_pos:
            cv2.circle(display, player_pos, 2, COLOR_PLAYER, -1)
            cv2.circle(display, player_pos, 4, (0, 0, 255), 1)
        display = cv2.resize(display, (FIXED_W, FIXED_H),
                             interpolation=cv2.INTER_NEAREST)
        return display

    def manual_select_region(self):
        """手动拖拽框选小地图区域（在主窗口上操作，不新建窗口）"""
        self._update_window_rect()
        frame = self._capture_window()
        print("\n=== 手动框选小地图 ===")
        print("在当前窗口中拖拽框选小地图区域")
        print("按 Enter 确认，按 C 取消")

        win = getattr(self, "_win_name", "Minimap Route")
        # 把主窗口放大到能看到整个游戏截图
        disp_w = min(frame.shape[1], 1000)
        disp_h = int(frame.shape[0] * disp_w / frame.shape[1])
        cv2.resizeWindow(win, disp_w, disp_h)
        cv2.waitKey(30)

        # 在主窗口上直接框选
        roi = cv2.selectROI(win, frame, fromCenter=False, showCrosshair=True)

        x, y, w, h = roi
        if w < 20 or h < 20:
            print("取消或选择区域太小，保持原设置")
            # 恢复窗口大小
            cv2.resizeWindow(win, FIXED_W, FIXED_H)
            return False

        # 选中的区域即小地图外框（窗口内坐标）
        self.minimap_rect = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
        pad_l, pad_t, pad_r, pad_b = 8, 2, 2, 2
        self.map_area_rect = {
            "left": int(x) + pad_l, "top": int(y) + pad_t,
            "width": int(w) - pad_l - pad_r, "height": int(h) - pad_t - pad_b
        }
        self._save_region()
        self.frame_count = 0
        self.last_player_pos = None
        # 恢复窗口大小为固定尺寸
        cv2.resizeWindow(win, FIXED_W, FIXED_H)
        self._win_size = (FIXED_W, FIXED_H)
        print("手动选择区域: (%d,%d) %dx%d" % (x, y, w, h))
        print("Map area:", self.map_area_rect["width"], "x", self.map_area_rect["height"])
        return True

    def run(self):
        win = "Minimap Route"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win, FIXED_W, FIXED_H)
        self._win_name = win
        self._win_size = (FIXED_W, FIXED_H)
        while True:
            try:
                map_area = self._capture_map()
            except Exception:
                time.sleep(0.05)
                continue

            # 窗口被手动框选关掉后自动重建
            try:
                cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE)
            except Exception:
                cv2.namedWindow(win, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(win, self._win_size[0], self._win_size[1])

            # 调试：保存实际截取的地图区域（只存一次）
            if self.frame_count == 0:
                cv2.imwrite("debug_map_area.png", map_area)
                print("Captured map_area:", map_area.shape[1], "x", map_area.shape[0])

            self.frame_count += 1
            if self.frame_count % 2 == 0 or self.last_player_pos is None:
                player_pos = self.find_player_dot(map_area)
            else:
                player_pos = self.last_player_pos

            if self.recording_platform and player_pos:
                self.platform_points.append(player_pos)
            if self.recording_ladder and player_pos:
                self.ladder_points.append(player_pos)

            self.hotkey.pump()
            self._check_hotkeys()

            cv2.imshow(win, self.draw(map_area, player_pos))
            cv2.resizeWindow(win, FIXED_W, FIXED_H)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                break
            elif key == ord('r'):
                print("Redetecting...")
                self._detect_minimap()
            elif key == ord('n'):
                self.manual_select_region()
        cv2.destroyAllWindows()
        self.hotkey.uninstall()
        print("Final:", len(self.platforms), "platforms,", len(self.ladders), "ladders")


if __name__ == "__main__":
    MinimapRouteRecorder().run()
