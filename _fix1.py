import re

with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修改 _load_blue_box
old_load = '''            if "width" in data and "height" in data:
                self._blue_box = {"width": int(data["width"]), "height": int(data["height"])}
                print("[蓝色框] 加载成功: %dx%d" % (self._blue_box["width"], self._blue_box["height"]))'''
new_load = '''            if "width" in data and "height" in data:
                self._blue_box = {
                    "width": int(data["width"]),
                    "height": int(data["height"]),
                    "bl_ox": int(data.get("bl_ox", 0)),
                    "bl_oy": int(data.get("bl_oy", 0)),
                    "tr_ox": int(data.get("tr_ox", 0)),
                    "tr_oy": int(data.get("tr_oy", 0)),
                }
                print("[绿框] 加载成功: %dx%d 偏移(bl=%d,%d tr=%d,%d)" % (
                    self._blue_box["width"], self._blue_box["height"],
                    self._blue_box["bl_ox"], self._blue_box["bl_oy"],
                    self._blue_box["tr_ox"], self._blue_box["tr_oy"]))'''
content = content.replace(old_load, new_load)

# 2. 修改 _save_blue_box 的 print
old_save_print = '''            print("[蓝色框] 保存成功: %dx%d" % (self._blue_box["width"], self._blue_box["height"]))'''
new_save_print = '''            print("[绿框] 保存成功: %dx%d 偏移(bl=%d,%d tr=%d,%d)" % (
                self._blue_box["width"], self._blue_box["height"],
                self._blue_box["bl_ox"], self._blue_box["bl_oy"],
                self._blue_box["tr_ox"], self._blue_box["tr_oy"]))'''
content = content.replace(old_save_print, new_save_print)

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
