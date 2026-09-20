# -*- coding: utf-8 -*-
"""打开跨层总闸:combat_step 实参 allow_cross False->True(maple 唯一硬开关)。cur_cross 仍传None。"""
import ast, io, sys
P = "maple_route_ui.py"
with io.open(P, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()
old = "            _attacked, _eff_up, _ydn, False, freeze_lock=False,  # 同层调试期allow_cross=False:不上下梯,超跳高带怪不参选(用户2026-09-20)"
new = "            _attacked, _eff_up, _ydn, True, freeze_lock=False,  # 跨层已开allow_cross=True(用户2026-09-21):超跳高带怪产cross走上梯/下跳;cur_cross仍传None防续命恒真漏帧误cross呆住"
c = s.count(old)
if c != 1:
    print("FAIL count=%d" % c); sys.exit(1)
s = s.replace(old, new)
ast.parse(s)
with io.open(P, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
print("CROSS_ON_OK")
