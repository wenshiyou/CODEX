# -*- coding: utf-8 -*-
import io, sys
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(P, "r", encoding="utf-8-sig") as f:
    text = f.read()
old = '''            if os.path.exists(_p):
                with open(_p, "r", encoding="utf-8") as fp:
                    _lv = json.load(fp).get("level", PERF_DEFAULT_LEVEL)'''
new = '''            if os.path.exists(_p):
                # utf-8-sig兼容带BOM(历史/外部编辑器存的)与不带BOM;保存端写标准utf-8无BOM,下次即归一
                with open(_p, "r", encoding="utf-8-sig") as fp:
                    _lv = json.load(fp).get("level", PERF_DEFAULT_LEVEL)'''
c = text.count(old)
if c != 1:
    print("ANCHOR FAIL count=%d" % c); sys.exit(1)
text = text.replace(old, new, 1)
assert "\r\n" not in text
with io.open(P, "wb") as f:
    f.write(b"\xef\xbb\xbf" + text.encode("utf-8"))
print("PERF BOM READ FIX OK")
