# -*- coding: utf-8 -*-
"""清 P9 切片残留的旧 sticky/另找参照注释尸(6行),逻辑已物理删除,注释不得留。"""
import io, ast
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
raw = io.open(p, 'rb').read()
cc = raw.decode('utf-8-sig').replace('\r\n', '\n')
old = (
'        # 跳高打判定(用户2026-09-10晚简化)：两框都填(_slope_on)即开启,【不分群攻优先/就近,统一一套就近机制】;\n'
'        # 怪比人高落在[_sj_min,_sj_max]且X差≤技能射程才"走-跳-打"。群攻模式锁定点是怪群窗中心、Y差会被平均到区间外\n'
'        # →永不触发(用户实锤),故锁定点高度不在区间时,就近在X射程内另找一只Y差正好落在区间的高处怪做跳高打参照(主锁定不变)。\n'
'        # 高处参照怪sticky钉住(用户2026-09-11):上层一排怪Y都在跳打区间时,旧逻辑每帧选"X最近"那只当参照,\n'
'        # 人物一动参照就在左右怪间跳→_hmove/出手方向左右碎步、还每帧"换新目标"清跳打节奏。改为:钉住上一只参照,\n'
'        # 只要它本帧仍被检测到(±30X/±40Y容差)、Y仍在跳打区间、X仍≤技能射程就沿用;脱检/离开区间/走远才重选X最近。\n'
)
assert cc.count(old) == 1, "旧sticky注释锚命中%d" % cc.count(old)
cc = cc.replace(old, '')
ast.parse(cc)
io.open(p, 'wb').write(b'\xef\xbb\xbf' + cc.replace('\n', '\r\n').encode('utf-8'))
print("OK 旧sticky注释尸已清")
