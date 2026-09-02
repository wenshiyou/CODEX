p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

# === 修复1：人物特征加载优先从 app_dir（可写）加载，_MEIPASS 作为后备 ===
old1 = '''    def _load_char_templates(self):
        """从磁盘加载已保存的人物特征模板（frozen时从打包目录_MEIPASS读取, 非frozen从app_dir/data读取）"""
        self._char_templates = []
        # 打包(frozen)时 char_0.png 在 _MEIPASS/data/char_templates；直接扫描 char_*.png 加载(不依赖meta.json, meta可能没打包)
        if getattr(sys, 'frozen', False):
            tpl_dir = os.path.join(sys._MEIPASS, "data", "char_templates")
        else:
            tpl_dir = CHAR_TEMPLATE_DIR
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
                    img = load_png(img_path)
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

new1 = '''    def _load_char_templates(self):
        """从磁盘加载已保存的人物特征模板
        优先从 app_dir/data/char_templates（用户保存的，可写）加载；
        若为空，打包时再从 _MEIPASS/data/char_templates（内置默认）加载。"""
        self._char_templates = []

        def _scan_dir(tpl_dir):
            if not os.path.exists(tpl_dir):
                return
            for fname in sorted(os.listdir(tpl_dir)):
                if fname.startswith("char_") and fname.endswith(".png"):
                    try:
                        tid = int(fname.replace("char_", "").replace(".png", ""))
                    except ValueError:
                        continue
                    img_path = os.path.join(tpl_dir, fname)
                    img = load_png(img_path)
                    if img is not None:
                        h, w = img.shape[:2]
                        self._char_templates.append({
                            "id": tid,
                            "img": img,
                            "width": w,
                            "height": h,
                            "created_at": ""
                        })

        try:
            # 1. 优先从 app_dir（用户保存的可写目录）加载
            _scan_dir(CHAR_TEMPLATE_DIR)
            # 2. 若 app_dir 没有模板，打包时从 _MEIPASS（内置默认）加载
            if not self._char_templates and getattr(sys, 'frozen', False):
                _scan_dir(os.path.join(sys._MEIPASS, "data", "char_templates"))
            print("[人物特征] 已加载 %d 套模板" % len(self._char_templates))
        except Exception as e:
            print("[人物特征] 加载模板失败:", e)'''

assert old1 in code, 'fix1 pattern not found'
code = code.replace(old1, new1)
print('Fix1: char template load priority (app_dir first, _MEIPASS fallback)')

# === 修复2：红色基点默认偏移 200 -> 400（和注释一致）===
old2a = '''        self._auto_calib_green_offset = (200, 0)  # 复位X光圈在基点右方400（水平，可拖动调）
        self._auto_calib_blue_offset = (0, -200)  # 复位Y光圈在基点上方400（可拖动调）'''
new2a = '''        self._auto_calib_green_offset = (400, 0)  # 复位X光圈在基点右方400（水平，可拖动调）
        self._auto_calib_blue_offset = (0, -400)  # 复位Y光圈在基点上方400（可拖动调）'''
assert old2a in code, 'fix2a pattern not found'
code = code.replace(old2a, new2a)

old2b = '''                self._auto_calib_green_offset = (200, 0)  # X光圈默认在基点右方400（水平，提供X分量，可拖动调）'''
new2b = '''                self._auto_calib_green_offset = (400, 0)  # X光圈默认在基点右方400（水平，提供X分量，可拖动调）'''
assert old2b in code, 'fix2b pattern not found'
code = code.replace(old2b, new2b)

old2c = '''                self._auto_calib_blue_offset = (0, -200)  # Y光圈默认在基点上方400（可拖动调）'''
new2c = '''                self._auto_calib_blue_offset = (0, -400)  # Y光圈默认在基点上方400（可拖动调）'''
assert old2c in code, 'fix2c pattern not found'
code = code.replace(old2c, new2c)
print('Fix2: base point offset 200 -> 400')

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)
print('Done')
