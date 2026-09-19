# -*- coding: utf-8 -*-
"""2026-09-19 用户拍板:①梯子同帧二维合并(X<=60/Y<=50留高分) ②上行到顶只认后脑(删光点对梯顶,下行保留光点对梯底,250->500ms)。
带 count==1 断言,任一锚点失配不写文件;保持 UTF-8 BOM + 纯 LF。"""
import py_compile

p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
raw = open(p, 'rb').read()
assert raw.startswith(b'\xef\xbb\xbf'), '源文件无BOM,停手'
text = raw.decode('utf-8-sig')
assert '\r\n' not in text, '源文件含CRLF,停手'

reps = []

# R1 后脑连续无后脑到顶窗口 250 -> 500
reps.append((
"BACK_TOP_LOST_MS = 250",
"BACK_TOP_LOST_MS = 500",
True))

# R2 新增同帧梯子二维合并常量(插在 LADDER_LOCK_MAX_STEP_X 定义行之前)
reps.append((
"LADDER_LOCK_MAX_STEP_X = 120",
"LADDER_MERGE_DX = 60        # 同帧邻近梯子二维合并(用户2026-09-19):两命中中心|X差|<=60且|Y差|<=50视为同一把,只留质量分最高者\n"
"LADDER_MERGE_DY = 50        # 同上Y阈值;治同把梯出两块/双框重叠被当成两把梯\n"
"LADDER_LOCK_MAX_STEP_X = 120",
True))

# R3 YOLO 分支出口走统一二维合并
reps.append((
"            return sorted([(int(cx), int(cy), round(s, 3), None) for cx, cy, s in _yc], key=lambda c: c[0])  # YOLO无模板序号,编号留空由绘制按位置兜底",
"            _raw_y = [(int(cx), int(cy), round(s, 3), None) for cx, cy, s in _yc]  # YOLO无模板序号,编号留空由绘制按位置兜底\n"
"            return self._merge_nearby_ladders(_raw_y)",
True))

# R4 模板分支出口走统一二维合并
reps.append((
"        peaks.sort(key=lambda p: p[1])\n"
"        return [(cx, cy, round(s, 3), _tn) for s, cx, cy, _tn in peaks]",
"        peaks.sort(key=lambda p: p[1])\n"
"        _raw_t = [(cx, cy, round(s, 3), _tn) for s, cx, cy, _tn in peaks]\n"
"        return self._merge_nearby_ladders(_raw_t)",
True))

# R5 新增二维合并方法(放在 _dir_band_pick_ladder 之前)
reps.append((
"    @staticmethod\n"
"    def _dir_band_pick_ladder(half, psx, psy, cdir, mon_x):",
"    def _merge_nearby_ladders(self, cands):\n"
"        \"\"\"同帧邻近梯子二维合并(用户2026-09-19):两命中中心|X差|<=LADDER_MERGE_DX且|Y差|<=LADDER_MERGE_DY视为同一把,\n"
"        按质量分降序贪心只留分最高者(同把梯多峰/双框重叠合一),返回按X排序的[(cx,cy,score,tn),...];结构不变、下游无感。\"\"\"\n"
"        def _qv(c):\n"
"            try:\n"
"                return float(c[2]) if c[2] is not None else -1.0\n"
"            except (TypeError, ValueError, IndexError):\n"
"                return -1.0\n"
"        items = sorted(cands, key=_qv, reverse=True)\n"
"        kept = []\n"
"        for c in items:\n"
"            cx, cy = int(c[0]), int(c[1])\n"
"            is_dup = False\n"
"            for k in kept:\n"
"                if abs(cx - int(k[0])) <= LADDER_MERGE_DX and abs(cy - int(k[1])) <= LADDER_MERGE_DY:\n"
"                    is_dup = True\n"
"                    break\n"
"            if not is_dup:\n"
"                kept.append(c)\n"
"        kept.sort(key=lambda c: c[0])\n"
"        return kept\n"
"\n"
"    @staticmethod\n"
"    def _dir_band_pick_ladder(half, psx, psy, cdir, mon_x):",
True))

# R6a climbing 到顶判定:上行删 _map_ok 光点判据只认后脑;下行保留光点对梯底
reps.append((
"            _arrived = False\n"
"            _arrive_why = \"\"\n"
"            _map_ok = False\n"
"            if _end_y:\n"
"                _map_ok = (py <= _end_y + LADDER_TOP_ARRIVE_TOL) if _up else (py >= _end_y - LADDER_TOP_ARRIVE_TOL)\n"
"            _top_by_back = bool(_up and self._ladder_back_top)\n"
"            if _top_by_back or _map_ok:",
"            _arrived = False\n"
"            _arrive_why = \"\"\n"
"            # 【用户2026-09-19】上行到顶只认后脑:连续BACK_TOP_LOST_MS看不到后脑=翻台到顶;\n"
"            # 物理删除上行\"光点Y重合梯顶\"判据(坏/短录制梯顶会让人刚抓住、还在梯底就误判到顶松手=爬一半掉下来)。\n"
"            # 下行不接后脑,仍只认光点Y重合梯底;总超时(录制duration+2s)保命不变。\n"
"            _top_by_back = bool(_up and self._ladder_back_top)\n"
"            _map_ok_down = bool((not _up) and bool(_end_y) and py >= _end_y - LADDER_TOP_ARRIVE_TOL)\n"
"            if _top_by_back or _map_ok_down:",
True))

# R6b hold 理由措辞:下行才走光点,梯端->梯底
reps.append((
'                        else ("光点重合梯端后多按%dms翻稳" % LADDER_TOP_HOLD_MS)',
'                        else ("光点重合梯底后多按%dms翻稳" % LADDER_TOP_HOLD_MS)',
True))

# R7(可选,仅注释一致性) 637 行 250ms -> 500ms
reps.append((
"到顶=climbing中连续250ms看不到后脑",
"到顶=climbing中连续500ms看不到后脑",
False))

# 先全部校验锚点
for old, new, req in reps:
    c = text.count(old)
    if c != 1:
        if req:
            raise SystemExit('锚点失配 count=%d (required): %r' % (c, old[:70]))
        print('SKIP optional count=%d: %r' % (c, old[:50]))

# 全部唯一才替换并写回
for old, new, req in reps:
    if text.count(old) == 1:
        text = text.replace(old, new)

assert '\r\n' not in text, '替换后引入CRLF'
open(p, 'wb').write(b'\xef\xbb\xbf' + text.encode('utf-8'))
py_compile.compile(p, doraise=True)
print('APPLY OK + py_compile PASS')
