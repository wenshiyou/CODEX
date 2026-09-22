# -*- coding: utf-8 -*-
"""AST 命名遮蔽扫描: 类内 def 方法名 ∩ self.xxx 属性名 必须为空(防 self.xxx=... 覆盖同名方法)。"""
import ast, io
PATH = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
src = io.open(PATH, encoding='utf-8-sig').read()
tree = ast.parse(src)
bad = []
for cls in ast.walk(tree):
    if isinstance(cls, ast.ClassDef):
        methods = {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        attrs = set()
        for node in ast.walk(cls):
            # 只看"赋值语境"的 self.xxx = ...(Store 才会覆盖同名方法);self.xxx() 调用是Load,不算
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) \
                    and isinstance(node.value, ast.Name) and node.value.id == 'self':
                attrs.add(node.attr)
        inter = sorted(methods & attrs)
        if inter:
            bad.append((cls.name, inter))
if bad:
    for c, i in bad:
        print('SHADOW in %s: %s' % (c, i))
    raise SystemExit(1)
print('NO METHOD/ATTR SHADOW')
