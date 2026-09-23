# -*- coding: utf-8 -*-
# 微补丁(不提交git): 同列覆盖后新梯插回该列原最上位置(不append末尾), 保持列表物理顺序/UI编号不错位
import io
p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s = io.open(p, 'rb').read().decode('utf-8-sig').replace('\r\n', '\n')

old = (
'                    if same_idx:\n'
'                        keep_id = min(self.ladders[i].get("id", len(self.ladders)) for i in same_idx)\n'
'                        for i in sorted(same_idx, reverse=True):\n'
'                            _cov = self.ladders.pop(i)\n'
'                            _debug_log("[梯录D] 同列覆盖删除旧梯 id=%s x=%.1f top=%.1f bot=%.1f" % (\n'
'                                _cov.get("id"), _cov.get("x", 0.0), _cov.get("y_top", 0.0), _cov.get("y_bottom", 0.0)))\n'
'                        new_ld["id"] = keep_id  # 继承同列最小编号,不产生重复号\n'
'                        self.ladders.append(new_ld)\n'
'                        replaced = True\n'
)
new = (
'                    if same_idx:\n'
'                        keep_id = min(self.ladders[i].get("id", len(self.ladders)) for i in same_idx)\n'
'                        _first_pos = min(same_idx)\n'
'                        for i in sorted(same_idx, reverse=True):\n'
'                            _cov = self.ladders.pop(i)\n'
'                            _debug_log("[梯录D] 同列覆盖删除旧梯 id=%s x=%.1f top=%.1f bot=%.1f" % (\n'
'                                _cov.get("id"), _cov.get("x", 0.0), _cov.get("y_top", 0.0), _cov.get("y_bottom", 0.0)))\n'
'                        new_ld["id"] = keep_id  # 继承同列最小编号,不产生重复号\n'
'                        self.ladders.insert(_first_pos, new_ld)  # 插回该列原最上位置,保持列表物理顺序(UI编号显示不错位)\n'
'                        replaced = True\n'
)
assert s.count(old) == 1, "覆盖段锚点命中=%d" % s.count(old)
s = s.replace(old, new, 1)
io.open(p, 'w', encoding='utf-8-sig', newline='').write(s.replace('\n', '\r\n'))
print("MICRO PATCH OK: insert at first same-column position")
