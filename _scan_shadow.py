# -*- coding: utf-8 -*-
# 全量排查:实例属性 self.x=... 与类方法 def x(...) 重名(属性遮蔽方法 -> 'xxx' object is not callable)
import ast, io
src = io.open('maple_route_ui.py', encoding='utf-8').read()
tree = ast.parse(src)

methods = {}   # 方法名 -> 定义行
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[item.name] = item.lineno

assigns = {}   # self.<attr>= 的属性名 -> [行号]
for node in ast.walk(tree):
    tgts = []
    if isinstance(node, ast.Assign):
        tgts = node.targets
    elif isinstance(node, ast.AnnAssign):
        tgts = [node.target]
    for t in tgts:
        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self':
            assigns.setdefault(t.attr, []).append(node.lineno)

shadow = sorted(set(methods) & set(assigns))
print('=== self属性 与 方法 重名(遮蔽隐患) 共%d个 ===' % len(shadow))
for name in shadow:
    print('\n● %s  方法定义@%d  属性赋值行:%s' % (name, methods[name], assigns[name]))
print('\n方法总数=%d  self赋值属性总数=%d' % (len(methods), len(assigns)))
