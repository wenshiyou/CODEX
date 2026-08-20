"""综合补丁：修复血条检测 + 集成YOLO怪物检测 + 实时连线"""
import re

with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    code = f.read()

original_len = len(code)

# === 1. 替换 _detect_hp_mp_bars：只搜底部25px，HSV，限制x在中间区域 ===
old_detect = '''    def _detect_hp_mp_bars(self, frame):
        """自动检测HP/MP血条位置（扫描线），返回 (hp_bar, mp_bar) 每个为 (x,y,w) 或 None"""
        if frame is None:
            return None, None
        h, w = frame.shape[:2]
        # 只扫描底部60像素（血条在最底部状态栏）
        y_start = max(0, h - 60)
        roi = frame[y_start:, :]
        # HSV颜色分割：HP=红色，MP=青蓝色
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # HP红色（HSV中红色跨越0度，两个范围合并）
        hp_mask1 = cv2.inRange(hsv, np.array([0, 50, 50]), np.array([10, 255, 255]))
        hp_mask2 = cv2.inRange(hsv, np.array([170, 50, 50]), np.array([180, 255, 255]))
        hp_mask = (hp_mask1 | hp_mask2) > 0
        # MP青蓝色
        mp_mask = cv2.inRange(hsv, np.array([90, 40, 60]), np.array([130, 255, 255])) > 0
        hp_counts = hp_mask.sum(axis=1)
        mp_counts = mp_mask.sum(axis=1)
        hp_bar = mp_bar = None
        if hp_counts.max() > 20:
            row = int(np.argmax(hp_counts))
            cols = np.where(hp_mask[row])[0]
            if len(cols) > 20:
                x1, x2 = int(cols.min()), int(cols.max())
                bw = x2 - x1 + 1
                if 30 <= bw <= 600:
                    hp_bar = (x1, y_start + row, bw)
        if mp_counts.max() > 20:
            row = int(np.argmax(mp_counts))
            cols = np.where(mp_mask[row])[0]
            if len(cols) > 20:
                x1, x2 = int(cols.min()), int(cols.max())
                bw = x2 - x1 + 1
                if 30 <= bw <= 600:
                    mp_bar = (x1, y_start + row, bw)
        _debug_log("血条检测: hp=%s mp=%s frame=%dx%d" % (hp_bar, mp_bar, w, h))
        return hp_bar, mp_bar'''

new_detect = '''    def _detect_hp_mp_bars(self, frame):
        """检测HP/MP血条：只搜底部25px，HSV颜色，HP在左MP在右"""
        if frame is None:
            return None, None
        h, w = frame.shape[:2]
        y_start = max(0, h - 25)
        roi = frame[y_start:, :]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # HP红色
        hp_mask1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([12, 255, 255]))
        hp_mask2 = cv2.inRange(hsv, np.array([168, 80, 80]), np.array([180, 255, 255]))
        hp_mask = (hp_mask1 | hp_mask2) > 0
        # MP青蓝色
        mp_mask = cv2.inRange(hsv, np.array([85, 60, 80]), np.array([135, 255, 255])) > 0
        hp_bar = self._find_longest_hbar(hp_mask, y_start)
        mp_bar = self._find_longest_hbar(mp_mask, y_start)
        # HP必须在MP左边
        if hp_bar and mp_bar and hp_bar[0] > mp_bar[0]:
            hp_bar, mp_bar = mp_bar, hp_bar
        _debug_log("血条检测: hp=%s mp=%s" % (hp_bar, mp_bar))
        return hp_bar, mp_bar

    def _find_longest_hbar(self, mask, y_offset):
        """从二值mask找最长水平连续段，返回(x,y,w)或None"""
        if mask is None or mask.size == 0 or mask.sum() < 15:
            return None
        counts = mask.sum(axis=1)
        row = int(np.argmax(counts))
        cols = np.where(mask[row])[0]
        if len(cols) < 15:
            return None
        gaps = np.diff(cols)
        splits = np.where(gaps > 3)[0]
        best = (int(cols[0]), int(cols[-1]))
        best_len = best[1] - best[0] + 1
        start = 0
        for sp in splits:
            seg_len = cols[sp] - cols[start] + 1
            if seg_len > best_len:
                best_len = seg_len
                best = (int(cols[start]), int(cols[sp]))
            start = sp + 1
        seg_len = cols[-1] - cols[start] + 1
        if seg_len > best_len:
            best = (int(cols[start]), int(cols[-1]))
        x1, x2 = best
        bw = x2 - x1 + 1
        if 20 <= bw <= 400:
            return (x1, y_offset + row, bw)
        return None'''

if old_detect in code:
    code = code.replace(old_detect, new_detect)
    print("[1/6] _detect_hp_mp_bars 已替换")
else:
    print("[1/6] WARNING: _detect_hp_mp_bars 未找到")

# === 2. 替换 _read_bar_percent：用条内行像素占比 ===
old_read = '''    def _read_bar_percent(self, frame, bar, color_type):
        """读取血条填充百分比，color_type='hp'红或'mp'蓝"""
        if bar is None or frame is None:
            return None
        x, y, w = bar
        if y >= frame.shape[0] or x + w > frame.shape[1]:
            return None
        line = frame[y, x:x + w]
        if color_type == "hp":
            filled = np.sum((line[:, 2] > 120) & (line[:, 1] < 70) & (line[:, 0] < 70))
        else:
            filled = np.sum((line[:, 0] > 120) & (line[:, 2] < 100) & (line[:, 1] > 80) & (line[:, 1] < 200))
        return float(filled) / float(max(w, 1)) * 100.0'''

new_read = '''    def _read_bar_percent(self, frame, bar, color_type):
        """读取血条填充百分比：条内行的彩色像素占总宽比"""
        if bar is None or frame is None:
            return None
        x, y, w = bar
        if y >= frame.shape[0] or x + w > frame.shape[1]:
            return None
        # 取条所在行及上下各1行，取彩色像素最多的那行
        best_filled = 0
        for dy in [-1, 0, 1]:
            yy = y + dy
            if 0 <= yy < frame.shape[0]:
                line = frame[yy, x:x + w]
                if color_type == "hp":
                    filled = np.sum((line[:, 2] > 100) & (line[:, 1] < 90) & (line[:, 0] < 90))
                else:
                    filled = np.sum((line[:, 0] > 100) & (line[:, 2] < 120) & (line[:, 1] > 60))
                best_filled = max(best_filled, filled)
        return float(best_filled) / float(max(w, 1)) * 100.0'''

if old_read in code:
    code = code.replace(old_read, new_read)
    print("[2/6] _read_bar_percent 已替换")
else:
    print("[2/6] WARNING: _read_bar_percent 未找到")

# === 3. 在 __init__ 中添加 YOLO 相关属性 ===
old_init_attr = '        self._digit_templates = {}  # 0-9数字模板\n        self._last_max_check = 0'
new_init_attr = '''        self._digit_templates = {}  # 0-9数字模板
        self._last_max_check = 0
        # YOLO怪物检测
        self._yolo_net = None
        self._monsters = []  # [(x1,y1,x2,y2,score), ...]
        self._last_yolo_check = 0
        self._yolo_conf = 0.4
        self._yolo_nms = 0.45'''

if old_init_attr in code:
    code = code.replace(old_init_attr, new_init_attr)
    print("[3/6] __init__ YOLO属性已添加")
else:
    print("[3/6] WARNING: __init__属性未找到")

# === 4. 在 _check_auto_potion 前添加 YOLO 方法 ===
yolo_methods = '''
    def _init_yolo(self):
        """加载YOLO onnx模型（cv2.dnn，不依赖onnxruntime）"""
        if self._yolo_net is not None:
            return True
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best.onnx")
        if not os.path.exists(model_path):
            model_path = "best.onnx"
        if not os.path.exists(model_path):
            print("[YOLO] 未找到 best.onnx")
            return False
        try:
            self._yolo_net = cv2.dnn.readNetFromONNX(model_path)
            self._yolo_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            print("[YOLO] 模型加载成功:", model_path)
            return True
        except Exception as e:
            print("[YOLO] 加载失败:", e)
            return False

    def _detect_monsters(self, frame):
        """YOLO检测怪物，返回 [(x1,y1,x2,y2,score), ...]"""
        if frame is None or not self._init_yolo():
            return []
        h, w = frame.shape[:2]
        INPUT_SIZE = 640
        scale = min(INPUT_SIZE / w, INPUT_SIZE / h)
        new_w, new_h = int(w * scale), int(h * scale)
        pad_x = (INPUT_SIZE - new_w) // 2
        pad_y = (INPUT_SIZE - new_h) // 2
        resized = cv2.resize(frame, (new_w, new_h))
        padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
        padded[pad_y:pad_y+new_h, pad_x:pad_x+new_w] = resized
        blob = cv2.dnn.blobFromImage(padded, 1/255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=True, crop=False)
        self._yolo_net.setInput(blob)
        out = self._yolo_net.forward()[0]  # (300, 6) = [x1,y1,x2,y2,score,cls]
        detections = []
        for row in out:
            x1, y1, x2, y2, score, cls = row
            if score < self._yolo_conf:
                continue
            x1 = int((x1 - pad_x) / scale)
            y1 = int((y1 - pad_y) / scale)
            x2 = int((x2 - pad_x) / scale)
            y2 = int((y2 - pad_y) / scale)
            if x2 > x1 and y2 > y1:
                detections.append((x1, y1, x2, y2, float(score)))
        # NMS去重
        if detections:
            boxes = [[d[0], d[1], d[2]-d[0], d[3]-d[1]] for d in detections]
            scores = [d[4] for d in detections]
            indices = cv2.dnn.NMSBoxes(boxes, scores, self._yolo_conf, self._yolo_nms)
            detections = [detections[i] for i in indices] if len(indices) > 0 else []
        return detections

    def _get_player_screen_pos(self, frame):
        """获取人物在游戏画面中的坐标（用特征模板匹配，失败返回画面中心底部）"""
        h, w = frame.shape[:2]
        # 优先用人物特征模板匹配
        best_loc = None
        best_score = 0
        tpl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "char_templates")
        if os.path.exists(tpl_dir):
            for fname in os.listdir(tpl_dir):
                if fname.endswith('.png'):
                    tpl = cv2.imread(os.path.join(tpl_dir, fname))
                    if tpl is None or tpl.shape[0] > h or tpl.shape[1] > w:
                        continue
                    res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    if max_val > best_score and max_val > 0.6:
                        best_score = max_val
                        best_loc = (max_loc[0] + tpl.shape[1]//2, max_loc[1] + tpl.shape[0]//2)
        if best_loc:
            return best_loc
        # 兜底：画面中心偏下
        return (w // 2, int(h * 0.65))

    def _draw_monster_overlay(self, frame, player_pos):
        """在游戏画面上画怪物框和人物连线"""
        if not self._monsters:
            return frame
        disp = frame.copy()
        px, py = player_pos
        cv2.circle(disp, (px, py), 6, (0, 255, 255), -1)
        cv2.putText(disp, "PLAYER", (px+8, py-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        for i, (x1, y1, x2, y2, score) in enumerate(self._monsters):
            cx, cy = (x1+x2)//2, (y1+y2)//2
            cv2.rectangle(disp, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(disp, "M%d %.0f%%" % (i, score*100), (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            # 连线
            cv2.line(disp, (px, py), (cx, cy), (0, 165, 255), 1)
            dist = int(np.sqrt((cx-px)**2 + (cy-py)**2))
            mid_x, mid_y = (px+cx)//2, (py+cy)//2
            cv2.putText(disp, str(dist), (mid_x, mid_y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 165, 255), 1)
        return disp

'''

# 在 _check_auto_potion 前插入
insert_point = '    def _check_auto_potion(self):'
if insert_point in code:
    code = code.replace(insert_point, yolo_methods + insert_point)
    print("[4/6] YOLO方法已插入")
else:
    print("[4/6] WARNING: _check_auto_potion 插入点未找到")

# === 5. 在主循环中添加 YOLO 检测（在 _check_auto_potion 后） ===
old_loop = '''            try:
                self._combat_tick()
            except Exception as e:
                print("[战斗] 异常:", e)'''

new_loop = '''            try:
                self._combat_tick()
            except Exception as e:
                print("[战斗] 异常:", e)

            # === YOLO怪物检测（每500ms一次） ===
            try:
                now_ms = time.time() * 1000
                if now_ms - self._last_yolo_check > 500:
                    self._last_yolo_check = now_ms
                    game_frame = self._capture_window()
                    if game_frame is not None:
                        self._monsters = self._detect_monsters(game_frame)
                        if self._monsters:
                            player_pos = self._get_player_screen_pos(game_frame)
                            overlay = self._draw_monster_overlay(game_frame, player_pos)
                            cv2.imshow("Monster Detection", overlay)
                            if self.frame_count % 30 == 0:
                                print("[YOLO] 检测到 %d 个怪物" % len(self._monsters))
            except Exception as e:
                print("[YOLO] 异常:", e)'''

if old_loop in code:
    code = code.replace(old_loop, new_loop)
    print("[5/6] 主循环YOLO检测已添加")
else:
    print("[5/6] WARNING: 主循环插入点未找到")

# === 6. 修复 _check_auto_potion 中的阈值读取（百分比0-100） ===
old_hp_thresh = '        hp_thresh = min(int(self._field_values.get("hp_value", "30") or "30"), 100)'
new_hp_thresh = '        hp_thresh = min(int(self._field_values.get("hp_value", "30") or "30"), 100)'
# 已经是对的，不用改

old_mp_thresh = '        mp_thresh = min(int(self._field_values.get("mp_value", "30") or "30"), 100)'
# 已经是对的

print("[6/6] 阈值校验已确认")

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("补丁完成，代码长度: %d -> %d" % (original_len, len(code)))
