# -*- coding: utf-8 -*-
"""_verify37 删除后静态体检：类内方法名 vs self 属性赋值名 重名遮蔽扫描。"""
import ast
import io

PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
text = io.open(PATH, encoding='utf-8-sig').read()
tree = ast.parse(text)
bad = False
for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    attrs = set()
    for node in ast.walk(cls):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self':
                attrs.add(t.attr)
    inter = methods & attrs
    print("类 %-28s 方法%3d self属性%3d 重名遮蔽交集=%s" % (cls.name, len(methods), len(attrs), sorted(inter)))
    if inter:
        bad = True
print("SHADOW_SCAN", "FAIL" if bad else "EMPTY_OK")
