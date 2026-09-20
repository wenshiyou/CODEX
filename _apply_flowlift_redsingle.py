# -*- coding: utf-8 -*-
"""
原子修改(用户2026-09-20):
A. 田字诊断框:水平移动时在"吊身后500"基础上再上移 FLOW_LIFT_Y=150(斜后方、不平齐人物);垂直(上下)分支不动。
B. 红框全局唯一(治本,非补丁):
   1) 蒙板同步段(主线,每帧组装overlay):一心爬梯(_ladder_precise_mode=True 且 climb_state in to_ladder/climbing/descend)
      时清主线怪锁 _combat_locked_target/_locked_box_cache/_combat_had_target,不下发怪红框;
      目标怪屏幕X/Y已冻结在 _ladder_target_mon_x/y,爬梯不依赖怪锁;出梯 _reset_climb 置 precise=False 后B重开怪扫重锁。
   2) paint 绘制层互斥兜底:有选中梯红框 ladder_sel 时怪红框让位,同屏只一个红框。
   3) _reset_climb 出梯清 ladder_sel,防到顶后梯红框残留。
保 UTF-8 带 BOM + LF;每处 assert count==1;全过才写回;py_compile。
"""
import io, os, py_compile, sys

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'maple_route_ui.py')
with io.open(PATH, 'r', encoding='utf-8-sig', newline='') as f:
    src = f.read()

EDITS = []

# --- A1. 新增田字上移常量 ---
EDITS.append((
"        FLOW_BOX, FLOW_MATCH, FLOW_TAIL_GAP, FLOW_MIN_GAP, FLOW_MARGIN = 120, 160, 500, 160, 24\n",
"        FLOW_BOX, FLOW_MATCH, FLOW_TAIL_GAP, FLOW_MIN_GAP, FLOW_MARGIN = 120, 160, 500, 160, 24\n"
"        FLOW_LIFT_Y = 150   # 水平移动时田字框在吊身后基础上再上移的像素(斜后方、不平齐人物;用户2026-09-20)\n",
"A1 田字上移常量"))

# --- A2. 水平分支 cy 上移 ---
EDITS.append((
"                    _cx = (_px - FLOW_TAIL_GAP) if _d > 0 else (_px + FLOW_TAIL_GAP); _cy = _py\n",
"                    _cx = (_px - FLOW_TAIL_GAP) if _d > 0 else (_px + FLOW_TAIL_GAP); _cy = _py - FLOW_LIFT_Y  # 水平:身后+上移=斜后方\n",
"A2 田字水平分支上移150"))

# --- B1. 蒙板同步:一心爬梯清主线怪锁、不下发怪红框 ---
_old_b1 = (
'                    self._monster_overlay_data["locked_target"] = getattr(self, \'_combat_locked_target\', None)\n'
'                    # 【阶段一】红框按锁定坐标直画(脱检也在,修"打怪正常但红框经常不显示");预备怪next下发黄框\n'
'                    self._monster_overlay_data["locked_rect"] = self._compute_locked_rect(\n'
'                        self._monster_overlay_data["locked_target"])\n'
)
_new_b1 = (
'                    # 一心爬梯(关怪扫:precise=True 且 to_ladder建锁后/climbing/descend)清主线怪锁,怪红框不与梯红框并存(用户2026-09-20红框唯一)\n'
'                    # 目标怪屏幕X/Y已冻结在_ladder_target_mon_x/y,爬梯不读怪锁;出梯_reset_climb置precise=False后B重开怪扫重锁\n'
'                    _precise_now = bool(getattr(self, \'_ladder_precise_mode\', False)) and getattr(self, \'_climb_state\', \'none\') in (\'to_ladder\', \'climbing\', \'descend\')\n'
'                    if _precise_now:\n'
'                        self._combat_locked_target = None\n'
'                        self._locked_box_cache = None\n'
'                        self._combat_had_target = False\n'
'                        self._monster_overlay_data["locked_target"] = None\n'
'                        self._monster_overlay_data["locked_rect"] = None\n'
'                    else:\n'
'                        self._monster_overlay_data["locked_target"] = getattr(self, \'_combat_locked_target\', None)\n'
'                        # 【阶段一】红框按锁定坐标直画(脱检也在,修"打怪正常但红框经常不显示");预备怪next下发黄框\n'
'                        self._monster_overlay_data["locked_rect"] = self._compute_locked_rect(\n'
'                            self._monster_overlay_data["locked_target"])\n'
)
EDITS.append((_old_b1, _new_b1, "B1 一心爬梯清主线怪锁+不下发怪红框"))

# --- B2. paint 怪红框与梯红框互斥(梯红框优先) ---
EDITS.append((
"                                # 红框:按主线locked_rect直画(脱检也在)+人物到锁定中心红线\n"
"                                if _locked_rect:\n",
"                                # 红框:按主线locked_rect直画(脱检也在)+人物到锁定中心红线\n"
"                                # 红框全局唯一:有选中梯红框ladder_sel时怪红框让位(用户2026-09-20,同屏只一个红框)\n"
"                                if _locked_rect and not data.get('ladder_sel'):\n",
"B2 绘制层怪/梯红框互斥"))

# --- B3. _reset_climb 出梯清选中梯红框 ---
EDITS.append((
"        self._lad_marks_recent = []         # 出梯清两帧累积候选池\n",
"        self._lad_marks_recent = []         # 出梯清两帧累积候选池\n"
"        _ovd_reset = getattr(self, '_monster_overlay_data', None)  # 出梯清选中梯红框,防到顶后梯红框残留(用户2026-09-20)\n"
"        if _ovd_reset is not None:\n"
"            _ovd_reset[\"ladder_sel\"] = None\n",
"B3 出梯清梯红框"))

for old, new, tag in EDITS:
    c = src.count(old)
    if c != 1:
        print("FAIL [%s] count=%d (期望1),已中止,未写回" % (tag, c))
        sys.exit(1)
    src = src.replace(old, new)
    print("OK  [%s]" % tag)

# 保 BOM + LF
src_lf = src.replace('\r\n', '\n').replace('\r', '\n')
with io.open(PATH, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(src_lf)
py_compile.compile(PATH, doraise=True)
print("py_compile pass")
