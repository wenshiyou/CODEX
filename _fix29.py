# -*- coding: utf-8 -*-
# 梯子特征编号: 弹窗+画面统一用"模板列表序号(1基,连续)"; 删除/清空/新增联动清画面缓存; 选锁距离逻辑不动
import io
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(P, "r", encoding="utf-8") as f:
    t = f.read()

pairs = []

# R1 YOLO分支返回带 None 序号
pairs.append((
"            return sorted([(int(cx), int(cy), round(s, 3)) for cx, cy, s in _yc], key=lambda c: c[0])",
"            return sorted([(int(cx), int(cy), round(s, 3), None) for cx, cy, s in _yc], key=lambda c: c[0])  # YOLO无模板序号,编号留空由绘制按位置兜底"
))

# R2 模板循环 enumerate(用_ker+timg锚,区别于_match_ladder_screen_x里的同名循环)
pairs.append((
"        _ker = np.ones((5, 5), dtype=np.uint8)\n"
"        for tpl in self._ladder_templates:\n"
"            timg = tpl[\"img\"]",
"        _ker = np.ones((5, 5), dtype=np.uint8)\n"
"        for _ti, tpl in enumerate(self._ladder_templates):  # _ti+1=模板列表显示序号(与特征弹窗一致)\n"
"            timg = tpl[\"img\"]"
))

# R3 NMS带序号 + 返回4元组
pairs.append((
"            for s, cx, cy in cand:                    # 按分数从高到低贪心NMS:近邻已选则跳过\n"
"                if all(abs(cx - qx) > LADDER_MARK_NMS_X for _, qx, qy in peaks):\n"
"                    peaks.append((s, int(cx), int(cy)))\n"
"        peaks.sort(key=lambda p: p[1])\n"
"        return [(cx, cy, round(s, 3)) for s, cx, cy in peaks]",
"            for s, cx, cy in cand:                    # 按分数从高到低贪心NMS:近邻已选则跳过\n"
"                if all(abs(cx - qx) > LADDER_MARK_NMS_X for _, qx, qy, _t in peaks):\n"
"                    peaks.append((s, int(cx), int(cy), _ti + 1))   # 带模板列表序号,画面编号与弹窗一致\n"
"        peaks.sort(key=lambda p: p[1])\n"
"        return [(cx, cy, round(s, 3), _tn) for s, cx, cy, _tn in peaks]"
))

# R4 overlay下发带序号
pairs.append((
'            self._monster_overlay_data["ladder_marks"] = [(c[0], c[1]) for c in self._lad_marks_cache]',
'            self._monster_overlay_data["ladder_marks"] = [(c[0], c[1], (c[3] if len(c) > 3 else None)) for c in self._lad_marks_cache]  # 下发(cx,cy,模板序号)'
))

# R5 白框绘制: 编号用模板序号
pairs.append((
"                                    for _i, (_lmx, _lmy) in enumerate(data.get('ladder_marks', [])):\n"
"                                        if _sel_x is not None and abs(_lmx - _sel_x) <= LADDER_MARK_NMS_X:\n"
"                                            continue   # 被选中的这把白框不画(下面原地转红框)\n"
"                                        gdi32.Rectangle(hdc, _lmx - 25, _lmy - 60, _lmx + 25, _lmy + 60)  # 宽50高120,中心=白框中心\n"
"                                        # 给每个梯子打编号(用户2026-09-16)\n"
"                                        gdi32.SetTextColor(hdc, 0xFFFFFF)\n"
"                                        gdi32.SetBkMode(hdc, 1)\n"
'                                        _num_txt = "#%d" % (_i + 1)\n'
"                                        gdi32.TextOutW(hdc, _lmx - 8, _lmy - 78, _num_txt, len(_num_txt))",
"                                    for _i, _lm in enumerate(data.get('ladder_marks', [])):\n"
"                                        _lmx, _lmy = _lm[0], _lm[1]\n"
"                                        _ltid = _lm[2] if len(_lm) > 2 else None     # 模板列表序号(与弹窗一致);YOLO兜底为None\n"
"                                        if _sel_x is not None and abs(_lmx - _sel_x) <= LADDER_MARK_NMS_X:\n"
"                                            continue   # 被选中的这把白框不画(下面原地转红框)\n"
"                                        gdi32.Rectangle(hdc, _lmx - 25, _lmy - 60, _lmx + 25, _lmy + 60)  # 宽50高120,中心=白框中心\n"
"                                        # 编号=模板序号(用户2026-09-17:弹窗/画面同一套连续编号);无模板(YOLO)才按位置兜底\n"
"                                        gdi32.SetTextColor(hdc, 0xFFFFFF)\n"
"                                        gdi32.SetBkMode(hdc, 1)\n"
'                                        _num_txt = ("#%d" % _ltid) if _ltid else ("#%d" % (_i + 1))\n'
"                                        gdi32.TextOutW(hdc, _lmx - 8, _lmy - 78, _num_txt, len(_num_txt))"
))

# R6 红框编号: 按坐标反查模板序号
pairs.append((
"                                    gdi32.SetTextColor(hdc, 0x0000FF)\n"
"                                    gdi32.SetBkMode(hdc, 1)\n"
'                                    _stxt = "选中"\n'
"                                    gdi32.TextOutW(hdc, _sx - 15, _sy - 78, _stxt, len(_stxt))",
"                                    # 红框编号:按坐标从当帧白框反查它命中的模板序号(选锁距离逻辑不动,仅显示层反查)\n"
"                                    _sel_tid = None\n"
"                                    for _lm in data.get('ladder_marks', []):\n"
"                                        if len(_lm) > 2 and _lm[2] and abs(_lm[0] - _sx) <= LADDER_MARK_NMS_X and abs(_lm[1] - _sy) <= 60:\n"
"                                            _sel_tid = _lm[2]\n"
"                                            break\n"
"                                    gdi32.SetTextColor(hdc, 0x0000FF)\n"
"                                    gdi32.SetBkMode(hdc, 1)\n"
'                                    _stxt = ("#%d" % _sel_tid) if _sel_tid else "选中"\n'
"                                    gdi32.TextOutW(hdc, _sx - 8, _sy - 78, _stxt, len(_stxt))"
))

# R7 弹窗标签用 idx+1(用紧跟的尺寸行锚定,区别于怪物特征同名行)
pairs.append((
'                tk.Label(row, text="#%d" % tpl["id"], font=("微软雅黑", 9, "bold"), width=3).pack(side="left")\n'
'                tk.Label(row, text="%dx%d" % (tpl["width"], tpl["height"]),',
'                tk.Label(row, text="#%d" % (idx + 1), font=("微软雅黑", 9, "bold"), width=3).pack(side="left")\n'
'                tk.Label(row, text="%dx%d" % (tpl["width"], tpl["height"]),'
))

# R8 删除确认文案用 i+1
pairs.append((
'                        if messagebox.askyesno("确认", "删除梯子特征#%d？" % self._ladder_templates[i]["id"]):',
'                        if messagebox.askyesno("确认", "删除梯子特征#%d？" % (i + 1)):'
))

# R9 新增_reset_ladder_display_cache + 删除函数清缓存、日志用序号
pairs.append((
"    def _delete_ladder_template(self, index):\n"
"        if 0 <= index < len(self._ladder_templates):\n"
"            t = self._ladder_templates.pop(index)\n"
"            self._save_ladder_templates(self.current_route)\n"
'            self._add_log("已删除梯子特征#%d" % t["id"])',
"    def _reset_ladder_display_cache(self):\n"
'        """梯子模板增/删后清主窗口画面白框、选框、冻结身份缓存(用户2026-09-17):被删梯子的框当帧消失、\n'
'        编号随列表重排;识别线程下一帧用最新模板重扫。只做原子赋None/[],跨线程安全。"""\n'
"        self._lad_marks_cache = []\n"
"        self._lad_marks_recent = []\n"
"        self._ladder_lock = None\n"
"        self._ladder_lock_patch = None\n"
"        self._ladder_snap_x = None\n"
"        self._locked_ladder = None\n"
"        try:\n"
"            _ov = getattr(self, '_monster_overlay_data', None)\n"
"            if isinstance(_ov, dict):\n"
'                _ov["ladder_marks"] = []\n'
'                _ov["ladder_sel"] = None\n'
"        except Exception:\n"
"            pass\n"
"\n"
"    def _delete_ladder_template(self, index):\n"
"        if 0 <= index < len(self._ladder_templates):\n"
"            _del_no = index + 1\n"
"            self._ladder_templates.pop(index)\n"
"            self._save_ladder_templates(self.current_route)\n"
"            self._reset_ladder_display_cache()   # 画面上对应梯子框立即删除,不残留旧白框/冻结块\n"
'            self._add_log("已删除梯子特征#%d" % _del_no)'
))

# R10 全部删除也清缓存
pairs.append((
"    def _clear_ladder_templates(self):\n"
"        n = len(self._ladder_templates)\n"
"        self._ladder_templates = []",
"    def _clear_ladder_templates(self):\n"
"        n = len(self._ladder_templates)\n"
"        self._ladder_templates = []\n"
"        self._reset_ladder_display_cache()"
))

# R11 捕获新模板: 清缓存 + 日志用显示序号
pairs.append((
'        self._ladder_templates.append({"id": new_id, "img": cap, "width": cw, "height": ch})\n'
"        self._save_ladder_templates(self.current_route)\n"
'        self._add_log("梯子特征#%d已保存(%dx%d) 共%d套，已存入方案%d" % (\n'
"            new_id, cw, ch, len(self._ladder_templates), self.current_route))\n"
'        print("[梯子特征] #%d 已存 %dx%d，共%d套" % (new_id, cw, ch, len(self._ladder_templates)))',
'        self._ladder_templates.append({"id": new_id, "img": cap, "width": cw, "height": ch})\n'
"        self._save_ladder_templates(self.current_route)\n"
"        self._reset_ladder_display_cache()   # 新增/替换模板后清旧白框,下一帧用新模板重扫、编号重排\n"
"        _new_no = len(self._ladder_templates)   # 显示序号=列表位置(连续);内部id仅用于存盘兼容\n"
'        self._add_log("梯子特征#%d已保存(%dx%d) 共%d套，已存入方案%d" % (\n'
"            _new_no, cw, ch, _new_no, self.current_route))\n"
'        print("[梯子特征] #%d 已存 %dx%d，共%d套" % (_new_no, cw, ch, _new_no))'
))

for i, (old, new) in enumerate(pairs, 1):
    c = t.count(old)
    assert c == 1, "R%d 锚点命中%d次" % (i, c)
    t = t.replace(old, new, 1)

with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(t)
print("梯子编号改造完成, 共%d处替换" % len(pairs))
