# -*- coding: utf-8 -*-
# 补丁(不提交git): 梯子二点式录制 + 同列整条覆盖
import io
p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
raw = io.open(p, 'rb').read().decode('utf-8-sig')
s = raw.replace('\r\n', '\n')

# 0) 新增录制同列覆盖常量: 按行前缀插入(不赌中文注释标点), 紧跟顶格 LADDER_MM_SAME_COL_OV 定义行
_lines = s.split('\n')
_const_line = ("LADDER_REC_SAME_COL_X = 8      # 录制覆盖:新录梯与旧录梯|X差|<8视为同一列竖梯,整条覆盖、删除同列旧碎段"
               "(二点式端到端重录);实测本图同列碎段对中心差<=7、并排梯最小差9")
_hit = False
for _i, _l in enumerate(_lines):
    if _l.startswith('LADDER_MM_SAME_COL_OV = 2'):
        _lines.insert(_i + 1, _const_line)
        _hit = True
        break
assert _hit, "常量:未找到顶格 LADDER_MM_SAME_COL_OV 定义行"
s = '\n'.join(_lines)

edits = []

# 1) 录制收集: 只留首尾两点
old1 = (
"            if self.recording_ladder and player_pos:\n"
"                # 【统一坐标空间】梯子与平台、旧梯子完全同一空间=小地图画面原始像素坐标：\n"
"                # 直接收集光点画面坐标，不做任何背景滚动/相对位移修正(此前scroll_y修正造出第二坐标空间导致梯子分层,已废弃)\n"
"                self.ladder_points.append(player_pos)\n"
"                _lseg_t = time.time()  # 本段首/末光点时间,算这把梯子从下到上爬升耗时(用户2026-09-17)\n"
"                if getattr(self, '_ladder_seg_t0', None) is None:\n"
"                    self._ladder_seg_t0 = _lseg_t\n"
"                self._ladder_seg_t1 = _lseg_t\n"
)
new1 = (
"            if self.recording_ladder and player_pos:\n"
"                # 【二点式录制(用户2026-09-23)】梯子只留首尾两个光点=梯底端/梯顶端,两点连成竖直线,中间爬梯轨迹点一帧都不存;\n"
"                # 坐标仍=小地图画面原始像素(不做滚动修正)。首点=F6开始时梯底光点(固定),末点随爬刷新为梯顶光点。\n"
"                _lseg_t = time.time()  # 首/末光点时间,算这把梯子从下到上爬升耗时(用户2026-09-17)\n"
"                if not self.ladder_points:\n"
"                    self.ladder_points = [player_pos]        # 首点=梯底端,固定\n"
"                    self._ladder_seg_t0 = _lseg_t\n"
"                else:\n"
"                    self.ladder_points = [self.ladder_points[0], player_pos]  # 末点=梯顶端,随爬刷新,中间点不留\n"
"                self._ladder_seg_t1 = _lseg_t\n"
)
edits.append(("录制收集两点", old1, new1))

# 2) extract_ladder 两点式
old2 = (
"        xs = [p[0] for p in points]\n"
"        ys = [p[1] for p in points]\n"
"        result = [{\n"
"            \"id\": len(self.ladders),\n"
"            \"x\": float(sorted(xs)[len(xs) // 2]),\n"
"            \"y_top\": float(min(ys)),\n"
"            \"y_bottom\": float(max(ys))\n"
"        }]\n"
"        # 超详细日志：确认点收集是否完整(第一个点/最后一个点/Y的min-max/点数)\n"
"        _debug_log(\"[梯录B] extract详细：点数=%d 首点=%s 末点=%s Ymin=%.1f Ymax=%.1f Yrange=%.1f x=%.1f\" % (\n"
"            len(points), str(points[0]), str(points[-1]), min(ys), max(ys), max(ys)-min(ys), result[0][\"x\"]))\n"
"        _debug_log(\"[梯录B] extract成功：原始点数=%d x=%.1f y_top=%.1f y_bottom=%.1f ladders总数将=%d\" % (\n"
"            len(points), result[0][\"x\"], result[0][\"y_top\"], result[0][\"y_bottom\"], len(self.ladders) + len(result)))  # 调试日志：验证extract_ladder是否返回非空结果\n"
"        return result\n"
)
new2 = (
"        # 二点式(用户2026-09-23):只用首点(梯底端)、末点(梯顶端)连成竖直线,中间轨迹点全弃用;\n"
"        # x=首尾X均值(不再取一长串晃动轨迹点的中位数,避免爬梯横向晃动把x带偏、同列长梯碎成上下多段)。\n"
"        p0, p1 = points[0], points[-1]\n"
"        _x = (float(p0[0]) + float(p1[0])) / 2.0\n"
"        _yt = min(float(p0[1]), float(p1[1]))\n"
"        _yb = max(float(p0[1]), float(p1[1]))\n"
"        result = [{\n"
"            \"id\": len(self.ladders),\n"
"            \"x\": _x,\n"
"            \"y_top\": _yt,\n"
"            \"y_bottom\": _yb\n"
"        }]\n"
"        _debug_log(\"[梯录B] 二点式成功:底端=%s 顶端=%s x=%.1f y_top=%.1f y_bottom=%.1f 梯长=%.1f ladders总数将=%d\" % (\n"
"            str(p0), str(p1), _x, _yt, _yb, _yb - _yt, len(self.ladders) + len(result)))\n"
"        return result\n"
)
edits.append(("extract两点式", old2, new2))

# extract 失败日志措辞(点数<2)
old2b = '            _debug_log("[梯录B] extract失败：点数=%d < 2" % len(points))  # 调试日志：点数不足'
new2b = '            _debug_log("[梯录B] extract失败：点数=%d < 2(二点式需F6在梯底开始、爬到梯顶再F6,留下首尾两点)" % len(points))'
edits.append(("extract失败日志", old2b, new2b))

# 3) F6 同列整条覆盖
old3 = (
'                    # 梯子覆盖规则：同一梯子=X基本一样(差值<2) 且 Y范围有交叠，新录制覆盖旧记录(不管保没保存)；X差≥2 或 Y范围完全不重叠=不同梯子不覆盖\n'
'                    new_ld = nl[0]\n'
'                    # 记录本把梯子录制爬升耗时(首末光点时间差),供爬梯总超时=耗时+2s兜底(用户2026-09-17)\n'
'                    if getattr(self, \'_ladder_seg_t0\', None) is not None and getattr(self, \'_ladder_seg_t1\', None) is not None and self._ladder_seg_t1 >= self._ladder_seg_t0:\n'
'                        new_ld[\'duration_sec\'] = round(self._ladder_seg_t1 - self._ladder_seg_t0, 2)\n'
'                    replaced = False\n'
'                    for i, old in enumerate(self.ladders):\n'
'                        y_overlap = not (new_ld["y_bottom"] < old["y_top"] or new_ld["y_top"] > old["y_bottom"])  # Y范围有交叠\n'
'                        if abs(old["x"] - new_ld["x"]) < 2 and y_overlap:\n'
'                            new_ld["id"] = old["id"]  # 保持原编号\n'
'                            self.ladders[i] = new_ld\n'
'                            replaced = True\n'
'                            _debug_log("[梯录D] 覆盖旧梯子 id=%s 旧x=%.1f 新x=%.1f y_top=%.1f y_bottom=%.1f" % (old["id"], old["x"], new_ld["x"], new_ld["y_top"], new_ld["y_bottom"]))\n'
'                            break\n'
'                    if not replaced:\n'
'                        self.ladders.append(new_ld)\n'
'                    print("Extracted 1 ladder,", len(self.ladder_points), "points,", "覆盖旧梯" if replaced else "新增", "ladders总数=", len(self.ladders))\n'
)
new3 = (
'                    # 梯子覆盖规则(二点式,用户2026-09-23):同一列竖梯只留一条——新录梯与任一旧录梯|X差|<LADDER_REC_SAME_COL_X即判同一把\n'
'                    # (不再要求Y重叠:二点式端到端重录本就覆盖上下各碎段);把同列旧碎段全部删除、用新整条替换(id继承同列最小号);\n'
'                    # 不同列(|X差|>=容差,如并排两把梯)不动,按新增。\n'
'                    new_ld = nl[0]\n'
'                    # 记录本把梯子录制爬升耗时(首末光点时间差),供爬梯总超时=耗时+2s兜底(用户2026-09-17)\n'
'                    if getattr(self, \'_ladder_seg_t0\', None) is not None and getattr(self, \'_ladder_seg_t1\', None) is not None and self._ladder_seg_t1 >= self._ladder_seg_t0:\n'
'                        new_ld[\'duration_sec\'] = round(self._ladder_seg_t1 - self._ladder_seg_t0, 2)\n'
'                    same_idx = [i for i, old in enumerate(self.ladders)\n'
'                                if abs(float(old.get("x", 0.0)) - float(new_ld["x"])) < LADDER_REC_SAME_COL_X]\n'
'                    replaced = False\n'
'                    if same_idx:\n'
'                        keep_id = min(self.ladders[i].get("id", len(self.ladders)) for i in same_idx)\n'
'                        for i in sorted(same_idx, reverse=True):\n'
'                            _cov = self.ladders.pop(i)\n'
'                            _debug_log("[梯录D] 同列覆盖删除旧梯 id=%s x=%.1f top=%.1f bot=%.1f" % (\n'
'                                _cov.get("id"), _cov.get("x", 0.0), _cov.get("y_top", 0.0), _cov.get("y_bottom", 0.0)))\n'
'                        new_ld["id"] = keep_id  # 继承同列最小编号,不产生重复号\n'
'                        self.ladders.append(new_ld)\n'
'                        replaced = True\n'
'                    if not replaced:\n'
'                        new_ld["id"] = len(self.ladders)\n'
'                        self.ladders.append(new_ld)\n'
'                    print("Extracted 1 ladder(二点式),", ("同列覆盖%d条" % len(same_idx)) if replaced else "新增", "ladders总数=", len(self.ladders))\n'
)
edits.append(("同列整条覆盖", old3, new3))

for name, old, new in edits:
    c = s.count(old)
    assert c == 1, "[%s] 锚点命中=%d(应为1),未写盘" % (name, c)
    s = s.replace(old, new, 1)

io.open(p, 'w', encoding='utf-8-sig', newline='').write(s.replace('\n', '\r\n'))
print("PATCH WRITTEN OK:", ["常量"] + [e[0] for e in edits])
