# -*- coding: utf-8 -*-
# 把 debug.log 保留时长 5 分钟 -> 60 分钟(1小时)。仅改保留时长与注释，不动裁剪算法/周期。
import io, sys

p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
raw = io.open(p, "rb").read().decode("utf-8-sig")   # 去 BOM，保留 CRLF
norm = raw.replace("\r\n", "\n")

edits = [
    # 1) 函数默认参数 5 -> 60
    ("def _maint_trim_debug_log(self, keep_minutes=5):",
     "def _maint_trim_debug_log(self, keep_minutes=60):"),
    # 2) _maint_run docstring 注释
    ("debug.log留最近5分钟 + 清1天前调试缓存。",
     "debug.log留最近60分钟(1小时) + 清1天前调试缓存。"),
    # 3) 实际调用实参 5 -> 60
    ("self._maint_trim_debug_log(5)",
     "self._maint_trim_debug_log(60)"),
    # 4) 主循环定期维护注释
    ("debug.log只留最近5分钟、清1天前调试缓存；backups全部保留",
     "debug.log只留最近60分钟(1小时)、清1天前调试缓存；backups全部保留"),
]

for old, new in edits:
    c = norm.count(old)
    if c != 1:
        print("ANCHOR FAIL count=%d : %s" % (c, old[:40]))
        sys.exit(3)
    norm = norm.replace(old, new)

out = norm.replace("\n", "\r\n")
io.open(p, "w", encoding="utf-8-sig", newline="").write(out)
print("PATCH OK, 4 edits applied")
