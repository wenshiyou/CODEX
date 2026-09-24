# -*- coding: utf-8 -*-
"""命名遮蔽扫描:def 方法名 与 self.x= 赋值属性名 交集必须为0(AGENTS第97条)。"""
import ast, io
src = io.open('maple_route_ui.py', encoding='utf-8-sig').read()
tree = ast.parse(src)
defs, assigns = set(), set()
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        defs.add(node.name)
    tgts = []
    if isinstance(node, ast.Assign):
        tgts = node.targets
    elif isinstance(node, ast.AnnAssign):
        tgts = [node.target]
    for t in tgts:
        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self':
            assigns.add(t.attr)
inter = defs & assigns
print('def数=%d self赋值属性数=%d 交集=%s' % (len(defs), len(assigns), sorted(inter)))
print('_platform_cross_direction 是否被属性赋值遮蔽:', '_platform_cross_direction' in assigns)
