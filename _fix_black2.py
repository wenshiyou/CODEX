p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

# 修复1: 人物特征加载优先从exe目录
old_load = '''        self._char_templates = []
        # 打包(frozen)时 char_0.png 在 _MEIPASS/data/char_templates；直接扫描 char_*.png 加载(不依赖meta.json, meta可能没打包)
        if getattr(sys, 'frozen', False):
            tpl_dir = os.path.join(sys._MEIPASS, "data", "char_templates")
        else:
            tpl_dir = CHAR_TEMPLATE_DIR'''
new_load = '''        self._char_templates = []
        # 优先从exe目录(CHAR_TEMPLATE_DIR)加载用户保存的模板，没有再从_MEIPASS读打包时的初始模板
        tpl_dir = CHAR_TEMPLATE_DIR
        try:
            has_user = os.path.exists(tpl_dir) and any(f.startswith("char_") and f.endswith(".png") for f in os.listdir(tpl_dir) if os.path.isfile(os.path.join(tpl_dir, f)))
        except Exception:
            has_user = False
        if not has_user and getattr(sys, 'frozen', False):
            tpl_dir = os.path.join(sys._MEIPASS, "data", "char_templates")'''
assert old_load in code, 'load block not found'
code = code.replace(old_load, new_load)
print('Fix1: char template load from exe dir first')

# 修复2: lock_screen_from_dot 整体加 try-except
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
assert old_lock in code, 'lock block not found'
code = code.replace(old_lock, new_lock)
print('Fix2: lock_screen_from_dot try-except')

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)
print('All fixes applied')
