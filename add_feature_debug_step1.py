# -*- coding: utf-8 -*-
"""修改匹配函数，保存每个特征的匹配结果，用于蒙板上显示点+数字"""
filepath = r"C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# === 1. 修改_match_character，在收集预测后保存到self._char_feature_matches ===
old_pred = '''        predictions = []  # [(foot_x, foot_y, confidence, tpl_id), ...]
        for tpl in self._char_templates:'''

new_pred = '''        predictions = []  # [(foot_x, foot_y, confidence, tpl_id), ...]
        # 初始化特征匹配调试列表（每帧清空，用于蒙板显示每个特征的匹配点+数字）
        if not hasattr(self, '_char_feature_matches'):
            self._char_feature_matches = []
        self._char_feature_matches = []  # 每帧清空
        for tpl in self._char_templates:'''

if old_pred in content:
    content = content.replace(old_pred, new_pred, 1)
    print("1. _match_character初始化调试列表")
else:
    print("1. 未找到_match_character预测收集位置")

# === 2. 在每个特征匹配成功后，保存到调试列表 ===
old_match = '''                foot_x = feat_cx + int(tpl.get("offset_x", 0))
                foot_y = feat_cy + int(tpl.get("offset_y", 0))
                predictions.append((foot_x, foot_y, max_val, tpl["id"], tpl.get("direction", "right")))'''

new_match = '''                foot_x = feat_cx + int(tpl.get("offset_x", 0))
                foot_y = feat_cy + int(tpl.get("offset_y", 0))
                predictions.append((foot_x, foot_y, max_val, tpl["id"], tpl.get("direction", "right")))
                # 保存到调试列表（特征中心点位置，用于蒙板显示点+数字）
                self._char_feature_matches.append({
                    "x": feat_cx, "y": feat_cy,  # 特征中心点位置（不是偏移后的脚位置）
                    "foot_x": foot_x, "foot_y": foot_y,  # 偏移后的脚位置
                    "id": tpl["id"], "conf": max_val,
                    "direction": tpl.get("direction", "right")
                })'''

if old_match in content:
    content = content.replace(old_match, new_match, 1)
    print("2. _match_character保存每个特征匹配结果")
else:
    print("2. 未找到特征匹配成功位置")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
print("人物特征匹配调试信息保存完成")
