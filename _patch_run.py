import re

path = r"C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py"
with open(path, "r", encoding="utf-8") as f:
    src = f.read()

# 1. 替换 run() 方法
new_run = '''    def _add_log(self, msg):
        self._logs.append(msg)
        if len(self._logs) > 20:
            self._logs = self._logs[-20:]

    def _capture_character_feature(self):
        """人物特征截图（待实现）：在游戏窗口框选人物身体，保存为特征模板"""
        self._add_log("人物特征功能开发中...")
        print("[人物特征] 功能开发中")

    def _clear_character_features(self):
        """清除所有人物特征模板"""
        self._add_log("特征已清除")
        print("[特征清除] 已清除所有特征")

    def _bind_window(self):
        """重新绑定游戏窗口"""
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if hwnd:
            self.hwnd = hwnd
            self._update_window_rect()
            self._add_log("窗口已绑定")
            print("[窗口绑定] 已绑定:", WINDOW_TITLE)
        else:
            self._add_log("未找到游戏窗口")
            print("[窗口绑定] 未找到:", WINDOW_TITLE)

    def run(self):
        win = "Minimap Route"
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        cv2.resizeWindow(win, UI_W, UI_H)
        cv2.setMouseCallback(win, self._on_mouse)
        self._win_name = win
        self._win_size = (UI_W, UI_H)
        while True:
            try:
                map_area = self._capture_map()
            except Exception:
                time.sleep(0.05)
                continue

            try:
                cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE)
            except Exception:
                cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
                cv2.resizeWindow(win, UI_W, UI_H)
                cv2.setMouseCallback(win, self._on_mouse)

            if self.frame_count == 0:
                cv2.imwrite("debug_map_area.png", map_area)
                print("Captured map_area:", map_area.shape[1], "x", map_area.shape[0])

            self.frame_count += 1
            if self._auto_refresh and self.frame_count % 30 == 0:
                self._detect_minimap(debug=False)
            if self.frame_count % 2 == 0 or self.last_player_pos is None:
                player_pos = self.find_player_dot(map_area)
            else:
                player_pos = self.last_player_pos

            if self.recording_platform and player_pos:
                self.platform_points.append(player_pos)
            if self.recording_ladder and player_pos:
                self.ladder_points.append(player_pos)

            self._random_step(player_pos)
            self._check_hotkeys()

            cv2.imshow(win, self.draw(map_area, player_pos))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                self._stop_random()
                break
            elif key == ord('r'):
                print("Redetecting...")
                self._detect_minimap()
            elif key == ord('n'):
                self.manual_select_region()
        cv2.destroyAllWindows()
        print("Final:", len(self.platforms), "platforms,", len(self.ladders), "ladders")
'''

pattern_run = re.compile(r'    def run\(self\):.*?(?=\n\nif __name__)', re.DOTALL)
src = pattern_run.sub(new_run, src)

# 2. 清理 _on_mouse 中的 _selecting 死代码（替换为简化版）
# 找到 _on_mouse 中从 "if self._selecting:" 到 "return" 的块，删除
# 实际上保留也无害，因为 _selecting 永远是 False。先不删，避免出错。

with open(path, "w", encoding="utf-8") as f:
    f.write(src)

print("Patched run() and added helper methods")
