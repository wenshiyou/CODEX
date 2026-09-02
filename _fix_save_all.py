import base64

with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修改_save_calib：加入char_templates(base64)、yolo_model_path、blue_box
old_save_calib = '''    def _save_calib(self):
        """保存端点数据和倍率到文件（左/右/上端点 + 校准倍率）"""
        try:
            calib_file = os.path.join(DATA_DIR, "route_%d_calib.json" % self.current_route)
            with open(calib_file, "w", encoding="utf-8") as f:
                json.dump({
                    "calib_left": self._calib_left_pt,
                    "calib_right": self._calib_right_pt,
                    "calib_top": getattr(self, '_calib_top_pt', None),
                    "calibrated_scale_x": getattr(self, '_calibrated_scale_x', 0),  # 保存X倍率
                    "calibrated_scale_y": getattr(self, '_calibrated_scale_y', 0),  # 保存Y倍率
                }, f, indent=2)
        except Exception:
            pass'''

new_save_calib = '''    def _save_calib(self):
        """保存端点数据和倍率到文件（左/右/上端点 + 校准倍率 + 人物特征 + YOLO路径 + 绿框）"""
        try:
            calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % self.current_route)
            # 人物特征转base64（只保留最后一次）
            char_b64 = None
            if self._char_templates:
                tpl = self._char_templates[0]
                ok, buf = cv2.imencode(".png", tpl["img"])
                if ok:
                    char_b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            with open(calib_file, "w", encoding="utf-8") as f:
                json.dump({
                    "calib_left": self._calib_left_pt,
                    "calib_right": self._calib_right_pt,
                    "calib_top": getattr(self, '_calib_top_pt', None),
                    "calibrated_scale_x": getattr(self, '_calibrated_scale_x', 0),
                    "calibrated_scale_y": getattr(self, '_calibrated_scale_y', 0),
                    "char_template_b64": char_b64,
                    "yolo_model_path": getattr(self, '_yolo_model_path', None),
                    "blue_box": self._blue_box,
                }, f, indent=2)
        except Exception as e:
            print("[保存] 方案配置保存失败:", e)'''
content = content.replace(old_save_calib, new_save_calib)

# 2. 修改_switch_route：加载char_templates、yolo_model_path、blue_box
old_switch_load = '''        calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % route_id)
        if os.path.exists(calib_file):
            try:
                with open(calib_file, "r", encoding="utf-8") as f:
                    cd = json.load(f)
                self._calib_left_pt = cd.get("calib_left")
                self._calib_right_pt = cd.get("calib_right")
                self._calib_top_pt = cd.get("calib_top")
                # 加载倍率数据（程序重启后自动恢复，不需要重新校准）
                saved_sx = cd.get("calibrated_scale_x", 0)
                saved_sy = cd.get("calibrated_scale_y", 0)
                if saved_sx > 0 and saved_sy > 0:
                    self._calibrated_scale_x = saved_sx
                    self._calibrated_scale_y = saved_sy
                    self._map_screen_scale = saved_sx
                    print("[切换] 方案%d 已加载倍率: X=%.4f Y=%.4f" % (route_id, saved_sx, saved_sy))
            except Exception:
                pass'''

new_switch_load = '''        calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % route_id)
        if os.path.exists(calib_file):
            try:
                with open(calib_file, "r", encoding="utf-8") as f:
                    cd = json.load(f)
                self._calib_left_pt = cd.get("calib_left")
                self._calib_right_pt = cd.get("calib_right")
                self._calib_top_pt = cd.get("calib_top")
                # 加载倍率数据
                saved_sx = cd.get("calibrated_scale_x", 0)
                saved_sy = cd.get("calibrated_scale_y", 0)
                if saved_sx > 0 and saved_sy > 0:
                    self._calibrated_scale_x = saved_sx
                    self._calibrated_scale_y = saved_sy
                    self._map_screen_scale = saved_sx
                    print("[切换] 方案%d 已加载倍率: X=%.4f Y=%.4f" % (route_id, saved_sx, saved_sy))
                # 加载人物特征（base64转图片）
                char_b64 = cd.get("char_template_b64")
                if char_b64:
                    try:
                        img_bytes = base64.b64decode(char_b64)
                        img = cv2.imdecode(np.frombuffer(img_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if img is not None:
                            h, w = img.shape[:2]
                            self._char_templates = [{"id": 0, "img": img, "width": w, "height": h, "created_at": ""}]
                            print("[切换] 方案%d 已加载人物特征 %dx%d" % (route_id, w, h))
                    except Exception as e:
                        print("[切换] 人物特征加载失败:", e)
                else:
                    self._char_templates = []
                # 加载YOLO模型路径
                yolo_path = cd.get("yolo_model_path")
                if yolo_path:
                    self._yolo_model_path = yolo_path
                    self._yolo_net = None
                    print("[切换] 方案%d 已加载YOLO路径: %s" % (route_id, os.path.basename(yolo_path)))
                # 加载绿框配置
                bb = cd.get("blue_box")
                if bb and bb.get("width", 0) > 0:
                    self._blue_box = bb
                    print("[切换] 方案%d 已加载绿框 %dx%d" % (route_id, bb["width"], bb["height"]))
                else:
                    self._blue_box = None
            except Exception as e:
                print("[切换] 方案配置加载失败:", e)'''
content = content.replace(old_switch_load, new_switch_load)

# 3. 在文件顶部import base64（如果没有的话）
if 'import base64' not in content:
    content = content.replace('import json', 'import json\nimport base64', 1)

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
