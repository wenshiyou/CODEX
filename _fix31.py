# -*- coding: utf-8 -*-
# _fix31: 梯子常驻白框扫描的Y范围,与X同款直接读寻怪配置(far_range_y_up/down),
# 不再用 getattr(self._far_range_y_*, 默认150)——该属性仅运行打怪决策时才同步350,停止态卡150,
# 会把人物上方较高的绳梯裁掉。改后停止态/运行态梯子识别范围都=寻怪范围。
import io
p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(p, "r", encoding="utf-8") as f:
    text = f.read()

old = (
    "        _yu = getattr(self, '_far_range_y_up', FAR_RANGE_Y_UP_DEFAULT)\n"
    "        _yd = getattr(self, '_far_range_y_down', FAR_RANGE_Y_DOWN_DEFAULT)\n"
)
new = (
    "        _yu = max(10, int(_fc.get(\"far_range_y_up\", FAR_RANGE_Y_UP_DEFAULT) or FAR_RANGE_Y_UP_DEFAULT))   # Y与X同款直接读寻怪配置(用户2026-09-17:梯子识别范围=寻怪范围,停止态也用配置值不再卡默认150)\n"
    "        _yd = max(10, int(_fc.get(\"far_range_y_down\", FAR_RANGE_Y_DOWN_DEFAULT) or FAR_RANGE_Y_DOWN_DEFAULT))\n"
)
assert text.count(old) == 1, "Y范围两行 命中数=%d(应为1)" % text.count(old)
text = text.replace(old, new)

with io.open(p, "w", encoding="utf-8", newline="") as f:
    f.write(text)
print("_fix31 OK: 梯子扫描Y范围已改为直接读寻怪配置far_range_y_up/down")
