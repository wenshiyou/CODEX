# -*- coding: utf-8 -*-
import ast, io, sys
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
src = io.open(p, encoding='utf-8-sig').read()
tree = ast.parse(src)
methods = set()
attrs = set()
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        methods.add(node.name)
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
        if isinstance(node.value, ast.Name) and node.value.id == 'self':
            attrs.add(node.attr)
over = methods & attrs
print('方法名数=%d  self赋值属性数=%d' % (len(methods), len(attrs)))
print('遮蔽交集:', sorted(over) if over else '无(0)')
sys.exit(1 if over else 0)
