# -*- coding: utf-8 -*-
# 只读校验(不写盘): 启停复位补丁
import io, ast
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s = io.open(P, 'rb').read().decode('utf-8-sig').replace('\r\n', '\n')

# 计数(定义不带self.; 调用带self.=start/stop两处)
assert s.count("def _reset_runtime_combat_state") == 1, "方法定义应=1"
assert s.count("self._reset_runtime_combat_state(") == 2, "start/stop调用应=2"
assert s.count("_reset_runtime_combat_state('F10启动·干净开场')") == 1
assert s.count("_reset_runtime_combat_state('F12停止·收场复位')") == 1
print("[count] 定义1 + start/stop调用2 OK")

tree = ast.parse(s)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MinimapRouteRecorder')
fns = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
newfn = fns.get('_reset_runtime_combat_state')
assert newfn is not None, "新方法不存在"

# 新方法引用的 self 成员必须在方法外也出现(防拼错造新属性)
seg = ast.get_source_segment(s, newfn)
attrs = set()
for n in ast.walk(newfn):
    if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'self':
        attrs.add(n.attr)
outside = s.replace(seg, '')
bad = [a for a in attrs if ('self.' + a) not in outside and ('def ' + a) not in outside]
assert not bad, "新方法外从未出现的成员(疑似拼错): %s" % bad
print("[AST] 新方法引用%d个self成员, 全部在方法外存在: %s" % (len(attrs), sorted(attrs)))

# start/stop 内调用顺序: _reset_climb -> _reset_runtime_combat_state -> 置 running
for fname, marker in (('_start_random', "self._random_running = True"),
                      ('_stop_random', "self._random_running = False")):
    src = ast.get_source_segment(s, fns[fname])
    i_reset = src.find("self._reset_climb()")
    i_call = src.find("self._reset_runtime_combat_state(")
    i_flag = src.find(marker)
    assert 0 <= i_reset < i_call < i_flag, "%s 顺序错 reset=%d call=%d flag=%d" % (fname, i_reset, i_call, i_flag)
    print("[顺序] %s: _reset_climb -> 复位 -> running OK" % fname)

# _reset_climb 本体未被加入开锁(23个内部调用点不受影响)
rc = ast.get_source_segment(s, fns['_reset_climb'])
assert '_reset_runtime_combat_state' not in rc and '_set_b_lock_enabled' not in rc
print("[隔离] _reset_climb 未被改动, 内部调用点行为不变 OK")

# py_compile
import py_compile
py_compile.compile(P, doraise=True)
print("[py_compile] OK")
print("ALL VERIFY OK")
