# -*- coding: utf-8 -*-
import io, ast
p = "maple_route_ui.py"
src = io.open(p, encoding="utf-8-sig").read()
tree = ast.parse(src)
fns = set()
for n in ast.walk(tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        fns.add(n.name)
new_methods = ["_note_freq_event", "_note_phantom_drop", "_note_stale_feeds", "_note_stale_target_attack"]
attrs = set()
for n in ast.walk(tree):
    if isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                attrs.add(t.attr)
new_fields = ["_recognize_beat_t", "_recog_err_last", "_stale_rep", "_phantom_streak", "_freq_events"]
print("== 字段遮蔽方法(应为空) ==", [a for a in new_fields if a in fns] or "无")
for m in new_methods:
    print("方法定义数 %-28s = %d" % (m, src.count("def %s(" % m)))
for call in ["self._note_freq_event(", "self._note_phantom_drop(", "self._note_stale_feeds(now)",
             "self._note_stale_target_attack(t_cx, t_cy, now)", "self._recognize_beat_t =",
             "log='exception'", "elif log == 'exception'", "def _stall_observer",
             "self._rlog("]:
    print("出现 %-44s = %d" % (call, src.count(call)))
print("AST_OK")
