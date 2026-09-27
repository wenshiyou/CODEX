# -*- coding: utf-8 -*-
"""AST命名遮蔽扫描:def方法名 ∩ self.x=赋值属性名 必须为0。"""
import ast, io
src = io.open(r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py", encoding="utf-8-sig").read()
tree = ast.parse(src)
methods = set()
attrs = set()
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        methods.add(node.name)
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                attrs.add(t.attr)
    if isinstance(node, ast.AnnAssign):
        t = node.target
        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
            attrs.add(t.attr)
inter = methods & attrs
print("def方法数=", len(methods), " self属性数=", len(attrs))
print("交集=", sorted(inter) if inter else "空(0) -> 通过")
