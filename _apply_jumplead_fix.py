# -*- coding: utf-8 -*-
"""jumplead 收尾两处修正:跑跳clamp下限60->62;approach修正轮收紧到TOL补走。"""
import ast, io, sys
P = "maple_route_ui.py"
with io.open(P, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()
edits = [
("LADDER_RUNJUMP_DX_MIN = 60          # 跑跳目标下限clamp(必须>伺服入口LADDER_RUNJUMP_LO=60,否则跑跳永不触发)",
 "LADDER_RUNJUMP_DX_MIN = 62          # 跑跳目标下限clamp(须给 60<asdx≤目标 留触发窗;若=60则窗为空跑跳永不触发)"),
("""            _lead = int(self._ladder_jump_cfg.get('vl_r' if diff > 0 else 'vl_l', LADDER_VERT_LEAD_DEFAULT))
            _timeout = (now_ms - self._ladder_realign_t) >= LADDER_SERVO_APPROACH_TIMEOUT_MS
            _release = adiff <= _lead or adiff <= LADDER_REALIGN_TOL or _timeout""",
"""            _lead_cfg = int(self._ladder_jump_cfg.get('vl_r' if diff > 0 else 'vl_l', LADDER_VERT_LEAD_DEFAULT))
            # 首次approach用人工提前px(留惯性滑入);若settle停在半路(10<残差<=lead)退回修正(corr>0)收紧到TOL:
            # 按住补走到<=10再松——否则残差仍<=lead会立刻又松手、不补走,空耗修正轮次。
            _lead = LADDER_REALIGN_TOL if self._ladder_realign_corr > 0 else _lead_cfg
            _timeout = (now_ms - self._ladder_realign_t) >= LADDER_SERVO_APPROACH_TIMEOUT_MS
            _release = adiff <= _lead or _timeout"""),
]
for old, new in edits:
    c = s.count(old)
    if c != 1:
        print("FAIL count=%d: %r" % (c, old[:40])); sys.exit(1)
    s = s.replace(old, new)
ast.parse(s)
with io.open(P, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
print("JUMPLEAD_FIX_OK")
