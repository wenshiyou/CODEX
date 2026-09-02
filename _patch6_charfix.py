# -*- coding: utf-8 -*-
path = 'maple_route_ui.py'
with open(path, encoding='utf-8-sig') as f:
    lines = f.read().split('\n')

# ========== 1. 替换_load_char_templates + 删除_resave_char_templates ==========
# 当前：行5132-5177 (索引5131-5176) 包含_load_char_templates + _resave_char_templates
# 替换为v76的_load_char_templates（不含_resave）

new_load = '''    def _load_char_templates(self):
        """从磁盘加载人物特征模板（扫描所有char_*.png，按ID排序，最多保留CHAR_MAX_TEMPLATES张）"""
        self._char_templates = []
        tpl_dir = CHAR_TEMPLATE_DIR
        if not os.path.exists(tpl_dir):
            print("[人物特征] 无保存的特征模板，为空")
            return
        try:
            # 扫描所有 char_<数字>.png，按ID数字排序
            files = []
            for fname in os.listdir(tpl_dir):
                m = re.match(r"char_(\\d+)\\.png$", fname)
                if m:
                    files.append((int(m.group(1)), fname))
            files.sort(key=lambda x: x)  # 按ID升序（旧的在前）
            # 只保留最后CHAR_MAX_TEMPLATES张（最新的）
            files = files[-CHAR_MAX_TEMPLATES:]
            for tid, fname in files:
                img_path = os.path.join(tpl_dir, fname)
                img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    h, w = img.shape
                    self._char_templates.append({
                        "id": tid,
                        "img": img,
                        "width": w,
                        "height": h,
                        "created_at": ""
                    })
            if self._char_templates:
                print("[人物特征] 已加载 %d 张模板（ID: %s）" % (
                    len(self._char_templates),
                    ",".join(str(t["id"]) for t in self._char_templates)))
            else:
                print("[人物特征] 无保存的特征模板，为空")
        except Exception as e:
            print("[人物特征] 加载模板失败:", e)

'''.split('\n')

# 索引5131到5176（行5132到5177），包含_load_char_templates和_resave_char_templates
# 确认一下5177行是什么
print('行5177:', repr(lines[5176][:80]))
print('行5178:', repr(lines[5177][:80]))

lines[5131:5177] = new_load
print('第一部分替换成功, 当前行数:', len(lines))

# 重新计算偏移
offset = len(new_load) - (5177 - 5131)

# ========== 2. 替换_capture_character_feature中的保存逻辑 ==========
# 找到新的_capture_character_feature位置
cap_start = None
for i, l in enumerate(lines):
    if 'def _capture_character_feature' in l:
        cap_start = i
        break
print('_capture_character_feature新行:', cap_start + 1)

# 找到"created_at = time.strftime"行
save_start = None
for i in range(cap_start, cap_start + 50):
    if 'created_at = time.strftime' in lines[i]:
        save_start = i
        break
print('保存逻辑起始行:', save_start + 1)

# 找到'print("[人物特征]", msg)'行
save_end = None
for i in range(save_start, save_start + 40):
    if 'print("[人物特征]", msg)' in lines[i]:
        save_end = i
        break
print('保存逻辑结束行:', save_end + 1)

new_save = '''        # 新ID=当前最大ID+1（不覆盖旧的，保留历史模板）
        max_id = max((t["id"] for t in self._char_templates), default=-1)
        new_id = max_id + 1
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

        ch, cw = captured.shape
        # 追加新模板到列表末尾（最新的在最后）
        self._char_templates.append({
            "id": new_id,
            "img": captured,
            "width": cw,
            "height": ch,
            "created_at": created_at
        })
        # 超过最大数量时删除最旧的（列表第一个，含磁盘文件）
        while len(self._char_templates) > CHAR_MAX_TEMPLATES:
            oldest = self._char_templates.pop(0)
            old_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % oldest["id"])
            if os.path.exists(old_path):
                os.remove(old_path)
            print("[人物特征] 超过%d张，删除最旧模板 #%d" % (CHAR_MAX_TEMPLATES, oldest["id"]))
        # 自动滚动到最新模板（UI下拉列表显示最后一页）
        max_scroll = max(0, len(self._char_templates) - CHAR_DD_FEAT_PER_PAGE)
        self._char_scroll = max_scroll
        self._save_char_meta()

        msg = "人物特征已保存 (%dx%d) 共%d张（ID #%d）" % (cw, ch, len(self._char_templates), new_id)
        self._add_log(msg)
        print("[人物特征]", msg)
'''.split('\n')

lines[save_start:save_end + 1] = new_save
print('第二部分替换成功, 当前行数:', len(lines))

with open(path, 'w', encoding='utf-8-sig') as f:
    f.write('\n'.join(lines))
print('文件已保存')
