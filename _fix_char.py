with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修改_load_char_templates：只加载最后一次的，去掉_MPASS回退，没有就为空
old_load = '''    def _load_char_templates(self):
        """从磁盘加载已保存的人物特征模板（优先运行时目录app_dir/data，打包后也能加载用户保存的模板）"""
        self._char_templates = []
        # 优先从运行时目录加载（用户保存的模板，打包后也在app_dir/data/char_templates）
        tpl_dir = CHAR_TEMPLATE_DIR
        has_runtime = False
        if os.path.exists(tpl_dir):
            has_runtime = any(f.startswith("char_") and f.endswith(".png") for f in os.listdir(tpl_dir))
        if not has_runtime and getattr(sys, 'frozen', False):
            tpl_dir = os.path.join(sys._MEIPASS, "data", "char_templates")
        if not os.path.exists(tpl_dir):
            return
        try:
            # 扫描 char_<id>.png 直接加载
            for fname in sorted(os.listdir(tpl_dir)):
                if fname.startswith("char_") and fname.endswith(".png"):
                    try:
                        tid = int(fname.replace("char_", "").replace(".png", ""))
                    except ValueError:
                        continue
                    img_path = os.path.join(tpl_dir, fname)
                    # 用imdecode兼容中文路径（cv2.imread中文路径返回None）
                    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        h, w = img.shape[:2]
                        self._char_templates.append({
                            "id": tid,
                            "img": img,
                            "width": w,
                            "height": h,
                            "created_at": ""
                        })
            print("[人物特征] 已加载 %d 套模板" % len(self._char_templates))
        except Exception as e:
            print("[人物特征] 加载模板失败:", e)'''

new_load = '''    def _load_char_templates(self):
        """从磁盘加载最后一次保存的人物特征模板（只保留最后一次，没有就为空）"""
        self._char_templates = []
        tpl_dir = CHAR_TEMPLATE_DIR
        if not os.path.exists(tpl_dir):
            print("[人物特征] 无保存的特征模板，为空")
            return
        try:
            # 只加载 char_0.png（最后一次保存的）
            img_path = os.path.join(tpl_dir, "char_0.png")
            if os.path.exists(img_path):
                img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    h, w = img.shape[:2]
                    self._char_templates.append({
                        "id": 0,
                        "img": img,
                        "width": w,
                        "height": h,
                        "created_at": ""
                    })
                    print("[人物特征] 已加载最后一次保存的模板 (%dx%d)" % (w, h))
                else:
                    print("[人物特征] 模板图片加载失败，为空")
            else:
                print("[人物特征] 无保存的特征模板，为空")
        except Exception as e:
            print("[人物特征] 加载模板失败:", e)'''
content = content.replace(old_load, new_load)

# 2. 修改_capture_character_feature：保存时固定ID=0直接覆盖，不递增
old_capture = '''        # 超过上限则替换最早的一套
        if len(self._char_templates) >= CHAR_MAX_TEMPLATES:
            oldest = self._char_templates.pop(0)
            old_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % oldest["id"])
            if os.path.exists(old_path):
                os.remove(old_path)
            self._add_log("模板已满，替换最早一套")

        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]
        if fh <= 0 or fw <= 0:
            self._add_log("截图失败")
            return

        print("[人物特征] 弹出框选窗口，拖拽框选人物身体，回车确认，ESC取消")
        # cv2.selectROI 返回 (x, y, w, h)，取消返回全0
        roi = cv2.selectROI("Select Character", frame, showCrosshair=False, fromCenter=False)
        cv2.destroyWindow("Select Character")

        x, y, w, h = roi
        if w <= 0 or h <= 0:
            print("[人物特征] 取消框选")
            return

        captured = frame[y:y + h, x:x + w].copy()

        # 分配新ID（取最大ID+1）
        existing_ids = [t["id"] for t in self._char_templates]
        new_id = (max(existing_ids) + 1) if existing_ids else 0
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")

        # 保存到磁盘（用imencode兼容中文路径，cv2.imwrite中文路径静默失败）
        img_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % new_id)
        ok, buf = cv2.imencode(".png", captured)
        if ok:
            buf.tofile(img_path)
            print("[人物特征] 模板已保存:", img_path)
        else:
            self._add_log("人物特征保存失败")
            print("[人物特征] 保存失败: cv2.imencode返回False")

        ch, cw = captured.shape[:2]
        self._char_templates.append({
            "id": new_id,
            "img": captured,
            "width": cw,
            "height": ch,
            "created_at": created_at
        })
        self._save_char_meta()

        msg = "人物特征#%d已保存 (%dx%d) 共%d套" % (new_id, cw, ch, len(self._char_templates))
        self._add_log(msg)
        print("[人物特征]", msg)'''

new_capture = '''        self._update_window_rect()
        frame = self._capture_window()
        fh, fw = frame.shape[:2]
        if fh <= 0 or fw <= 0:
            self._add_log("截图失败")
            return

        print("[人物特征] 弹出框选窗口，拖拽框选人物身体，回车确认，ESC取消")
        # cv2.selectROI 返回 (x, y, w, h)，取消返回全0
        roi = cv2.selectROI("Select Character", frame, showCrosshair=False, fromCenter=False)
        cv2.destroyWindow("Select Character")

        x, y, w, h = roi
        if w <= 0 or h <= 0:
            print("[人物特征] 取消框选")
            return

        captured = frame[y:y + h, x:x + w].copy()

        # 固定ID=0，直接覆盖旧的（只保留最后一次）
        new_id = 0
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")

        # 保存到磁盘（用imencode兼容中文路径，cv2.imwrite中文路径静默失败）
        img_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % new_id)
        ok, buf = cv2.imencode(".png", captured)
        if ok:
            buf.tofile(img_path)
            print("[人物特征] 模板已保存:", img_path)
        else:
            self._add_log("人物特征保存失败")
            print("[人物特征] 保存失败: cv2.imencode返回False")

        ch, cw = captured.shape[:2]
        # 清空旧的，只保留最后一次
        self._char_templates = [{
            "id": new_id,
            "img": captured,
            "width": cw,
            "height": ch,
            "created_at": created_at
        }]
        self._save_char_meta()

        msg = "人物特征已保存 (%dx%d)（覆盖上一次）" % (cw, ch)
        self._add_log(msg)
        print("[人物特征]", msg)'''
content = content.replace(old_capture, new_capture)

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
