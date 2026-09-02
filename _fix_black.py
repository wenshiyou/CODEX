p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

# 修复1: _load_char_templates 整体加 try-except，防止启动崩溃
old_load_start = '''    def _load_char_templates(self):
        """从磁盘加载已保存的人物特征模板（frozen时从打包目录_MEIPASS读取, 非frozen从app_dir/data读取）"""
        self._char_templates = []
        # 优先从exe目录(CHAR_TEMPLATE_DIR)加载用户保存的模板，没有再从_MEIPASS读打包时的初始模板
        tpl_dir = CHAR_TEMPLATE_DIR
        if not os.path.exists(tpl_dir) or not any(f.startswith("char_") and f.endswith(".png") for f in os.listdir(tpl_dir) if os.path.isfile(os.path.join(tpl_dir, f))):
            if getattr(sys, 'frozen', False):
                tpl_dir = os.path.join(sys._MEIPASS, "data", "char_templates")
        if not os.path.exists(tpl_dir):
            return'''
new_load_start = '''    def _load_char_templates(self):
        """从磁盘加载已保存的人物特征模板（frozen时从打包目录_MEIPASS读取, 非frozen从app_dir/data读取）"""
        self._char_templates = []
        try:
            # 优先从exe目录(CHAR_TEMPLATE_DIR)加载用户保存的模板，没有再从_MEIPASS读打包时的初始模板
            tpl_dir = CHAR_TEMPLATE_DIR
            if not os.path.exists(tpl_dir) or not any(f.startswith("char_") and f.endswith(".png") for f in os.listdir(tpl_dir) if os.path.isfile(os.path.join(tpl_dir, f))):
                if getattr(sys, 'frozen', False):
                    tpl_dir = os.path.join(sys._MEIPASS, "data", "char_templates")
            if not os.path.exists(tpl_dir):
                return'''
assert old_load_start in code, 'load start not found'
code = code.replace(old_load_start, new_load_start)

# 找到 _load_char_templates 的结尾（下一个 def 之前），加 except
# 先找到函数体结束位置
old_load_end = '''                        self._char_templates.append({
                            "id": tid,
                            "img": img,
                            "width": w,
                            "height": h,
                            "created_at": ""
                        })'''
new_load_end = '''                        self._char_templates.append({
                            "id": tid,
                            "img": img,
                            "width": w,
                            "height": h,
                            "created_at": ""
                        })
        except Exception as e:
            print("[人物特征] 加载异常:", e)
            self._char_templates = []'''
assert old_load_end in code, 'load end not found'
code = code.replace(old_load_end, new_load_end)
print('Fix1: _load_char_templates try-except')

# 修复2: lock_screen_from_dot 加 try-except
old_lock = '''    def lock_screen_from_dot(self):
        """【新方案·不用倍率】小地图光点 → 归一化位置 → 游戏屏幕坐标(锁定人物真实坐标).
        原理: 小地图三特征定位裁剪(map_area_rect)映射到显示窗口; 光点在此窗口内归一化(0~1),
              归一化位置 × 游戏窗口尺寸 = 人物在游戏屏幕的坐标. 归一化尺度不变, 任何地图一套通用.
        返回: (screen_x, screen_y) 或 None"""
        r = getattr(self, 'map_area_rect', None)'''
new_lock = '''    def lock_screen_from_dot(self):
        """【新方案·不用倍率】小地图光点 → 归一化位置 → 游戏屏幕坐标(锁定人物真实坐标).
        原理: 小地图三特征定位裁剪(map_area_rect)映射到显示窗口; 光点在此窗口内归一化(0~1),
              归一化位置 × 游戏窗口尺寸 = 人物在游戏屏幕的坐标. 归一化尺度不变, 任何地图一套通用.
        返回: (screen_x, screen_y) 或 None"""
        try:
            return self._lock_screen_from_dot_inner()
        except Exception as e:
            if getattr(self, 'frame_count', 0) % 60 == 0:
                _debug_log("[光点锁定] 异常: %s" % e)
            return None

    def _lock_screen_from_dot_inner(self):
        r = getattr(self, 'map_area_rect', None)'''
assert old_lock in code, 'lock not found'
code = code.replace(old_lock, new_lock)
print('Fix2: lock_screen_from_dot try-except')

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)
print('All fixes applied')
