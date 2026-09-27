# -*- coding: utf-8 -*-
"""AST命名遮蔽扫描：检查self实例属性与def方法同名"""
import ast, io

fp = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(fp, 'r', encoding='utf-8') as f:
    tree = ast.parse(f.read())

methods = set()
attrs = set()
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        methods.add(node.name)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'self':
        if isinstance(node.ctx, ast.Store):
            attrs.add(node.attr)

shadow = methods & attrs
if shadow:
    print("发现命名遮蔽:", sorted(shadow))
else:
    print("命名遮蔽扫描通过：0个冲突")
print("方法数:", len(methods), "属性数:", len(attrs))
