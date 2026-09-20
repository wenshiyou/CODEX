# -*- coding: utf-8 -*-
"""原子修改：B线程最终怪表按"当前帧人物点+面板寻怪范围"硬几何裁剪。
治根：2秒宽限(_detect_last_monsters)+时序平滑(_temporal_smooth_detections)续命来的
屏外/超范围陈旧框、YOLO背景误检，原先只按Y剔UI(maple 16784)、不按当前人物点重裁X，
导致人走离后仍锁到 X差>far_range_x(实测729>500) 的旧框 -> 满屏瞬移追空/锁横跳/发呆。
本刀在两道续命之后、metric/写最终怪表之前插入硬裁；人物点当帧丢失不裁(防闪丢清空)。
只改这一处，不删宽限/平滑(防漏检仍需要)，不碰梯子线。保 BOM/LF。"""
import io, sys, py_compile

PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"

with io.open(PATH, "r", encoding="utf-8-sig", newline="") as f:
    src = f.read()

NL = "\r\n" if "\r\n" in src else "\n"

anchor = (
    "                    _merged = [b for b in _merged if _band_y1 <= (b[1] + b[3]) // 2 <= _band_y2]"
    "  # 识别带兜底剔UI误检" + NL
)

assert src.count(anchor) == 1, "锚点(识别带剔UI行)命中数=%d，应为1，已中止未写文件" % src.count(anchor)

block_lines = [
    "                    # 【锁怪治本·用户2026-09-20】最终怪表(已含2秒宽限/时序平滑续命)按当前帧人物点+面板寻怪范围硬几何裁：",
    "                    # 续命只防漏检，不得把人已走离的屏外/超范围陈旧框、背景误检继续喂锁怪(实测锁X差729>寻怪500旧框致满屏瞬移追空)。",
    "                    # 人物点当帧丢失(_ch is None)不裁防闪丢清空；X超far_range_x或Y超far_range上下沿一律剔除；metric/红框/决策统一用裁后表。",
    "                    if _ch is not None and _far_x > 0:",
    "                        _fx0, _fy0 = _ch[0], _ch[1]",
    "                        _fy_lo = _fy0 - _far_y_up if _far_y_up > 0 else _band_y1",
    "                        _fy_hi = _fy0 + _far_y_down if _far_y_down > 0 else _band_y2",
    "                        _clipped = []",
    "                        for _cb in _merged:",
    "                            _ccx = (_cb[0] + _cb[2]) // 2",
    "                            _ccy = _cb[3]  # 怪框底边=脚(与metric/分桶cy=y2同口径)",
    "                            if abs(_ccx - _fx0) <= _far_x and _fy_lo <= _ccy <= _fy_hi:",
    "                                _clipped.append(_cb)",
    "                        _merged = _clipped",
]
block = NL.join(block_lines) + NL

src2 = src.replace(anchor, anchor + block, 1)

# 必须落在 metric 构建与 _raw_monsters 赋值之前
i_clip = src2.find("# 【锁怪治本·用户2026-09-20】")
i_metric = src2.find("                    _metric = {}", i_clip)
i_raw = src2.find("                    self._raw_monsters = _merged", i_clip)
assert i_clip != -1 and i_metric != -1 and i_raw != -1 and i_clip < i_metric < i_raw, "插入位置异常，中止"

with io.open(PATH, "w", encoding="utf-8-sig", newline="") as f:
    f.write(src2)

py_compile.compile(PATH, doraise=True)
print("MONSTER_FAR_CLIP_APPLY_OK")
