# -*- coding: utf-8 -*-
"""把蒙板段新增局部变量 _precise_now 改名为 _climb_hide_mon,避免与检测线程16283同名局部变量混淆(纯改名,零行为变化)。"""
import io, os, py_compile, sys
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'maple_route_ui.py')
with io.open(PATH, 'r', encoding='utf-8-sig', newline='') as f:
    src = f.read()
old = (
"                    _precise_now = bool(getattr(self, '_ladder_precise_mode', False)) and getattr(self, '_climb_state', 'none') in ('to_ladder', 'climbing', 'descend')\n"
"                    if _precise_now:\n"
)
new = (
"                    _climb_hide_mon = bool(getattr(self, '_ladder_precise_mode', False)) and getattr(self, '_climb_state', 'none') in ('to_ladder', 'climbing', 'descend')\n"
"                    if _climb_hide_mon:\n"
)
c = src.count(old)
if c != 1:
    print("FAIL count=%d,中止未写回" % c); sys.exit(1)
src = src.replace(old, new)
with io.open(PATH, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(src.replace('\r\n', '\n').replace('\r', '\n'))
py_compile.compile(PATH, doraise=True)
print("rename OK + py_compile pass")
