# -*- coding: utf-8 -*-
"""阶段一脚本B补丁:drop善后块无条件清旧current出手/首击标记(防叠位怪继承attacked当帧被误判空怪)。"""
import os, py_compile
P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maple_route_ui.py")
raw = open(P, "rb").read()
had_bom = raw.startswith(b"\xef\xbb\xbf")
src = raw.decode("utf-8-sig").replace("\r\n", "\n")
old = '''                # 异步催B下一检测帧立刻全图YOLO+血条(不等节流),但不阻塞、不return:本帧next已顶替,直接接着打/追
                self._yolo_last_t = 0.0
                self._bars_last_t = 0.0
            # 是否"真的换了目标"'''
new = '''                # 异步催B下一检测帧立刻全图YOLO+血条(不等节流),但不阻塞、不return:本帧next已顶替,直接接着打/追
                self._yolo_last_t = 0.0
                self._bars_last_t = 0.0
                # 旧current既已判死,出手/首击标记无条件清掉(等价旧drop块的16519-16520),防新旧怪叠在±40内
                # _is_new_target误判False、新怪继承attacked=True当帧被误判空怪丢掉;下面新目标块会再设一遍(幂等)
                self._combat_target_attacked = False
                self._combat_first_strike_time = 0
            # 是否"真的换了目标"'''
assert src.count(old) == 1, "锚点命中数=%d" % src.count(old)
src = src.replace(old, new, 1)
out = src.encode("utf-8")
if had_bom:
    out = b"\xef\xbb\xbf" + out
assert b"\r\n" not in out
open(P, "wb").write(out)
py_compile.compile(P, doraise=True)
print("补丁OK py_compile通过")
