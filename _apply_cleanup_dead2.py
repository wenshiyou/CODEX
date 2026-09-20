# -*- coding: utf-8 -*-
import io, py_compile
MP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(MP, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()
assert "\r\n" not in s
old = "        # 空怪1秒黑名单+压制侧:只读过滤候选(清理/append归主线,避免两线程同改list)\n"
assert s.count(old) == 1, s.count(old)
s = s.replace(old, "")
with io.open(MP, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
py_compile.compile(MP, doraise=True)
print("DEAD_COMMENT_OK")
