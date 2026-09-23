# -*- coding: utf-8 -*-
# 补丁(不提交git): _pick_ladder_minimap 选段规则根改
# 旧:过门候选只按X最近定唯一 -> 同列竖梯录成上下几段时会选到悬在头顶的上段
# 新:X最近定列 -> 同列上下段(X近+Y不重叠)并入 -> 上行取底端最靠下起步段/下行取顶端最靠上段
import io, sys
p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
raw = io.open(p, 'rb').read().decode('utf-8-sig')
s = raw.replace('\r\n', '\n')

# 1) 新增两个同列判定常量(紧跟 LADDER_MM_END_TOL 行)
old_const = ("LADDER_MM_END_TOL = 10      # 合格高度门:上行梯底y_bottom与光点Y差<=10"
             "(人跳起够得到底端)/下行梯顶y_top与光点Y差<=10")
new_const = old_const + (
    "\nLADDER_MM_SAME_COL_X = 15      # 同列判定:小地图X差<=15视为可能是同一竖梯的上下分段"
    "(实测同列段录制中心偏移<=12,如id8/x144与id1/x156差12首尾相接)"
    "\nLADDER_MM_SAME_COL_OV = 2      # 同列上下段Y区间重叠<=2(首尾相接/小间隙);"
    "重叠更大=同层并列两把梯(Y区间大面积重合),不并入同列"
)
assert s.count(old_const) == 1, "END_TOL常量锚点不唯一/未命中: %d" % s.count(old_const)
s = s.replace(old_const, new_const, 1)

# 2) 替换 _pick_ladder_minimap 定唯一梯的尾部
old_tail = (
"        cand = [t for t in ladders if _ok(t)]\n"
"        if not cand:\n"
"            return None\n"
"        if side_sign:\n"
"            side = [t for t in cand if (float(t['x']) - dx) * float(side_sign) > 0]\n"
"            if side:\n"
"                cand = side\n"
"        return min(cand, key=lambda t: abs(float(t['x']) - dx))\n"
)
new_tail = (
"        cand = [t for t in ladders if _ok(t)]\n"
"        if not cand:\n"
"            return None\n"
"        if side_sign:\n"
"            side = [t for t in cand if (float(t['x']) - dx) * float(side_sign) > 0]\n"
"            if side:\n"
"                cand = side\n"
"        # 定唯一一把(用户2026-09-23:光点够得着梯底端且X近才是正确梯;治同列竖梯录成上下几段时误选悬在头顶的上段):\n"
"        # 1)先按X最近定\"人该去的那一列竖梯\";2)同一条竖梯的上下分段(X极近、Y首尾相接/小间隙)并入同列,\n"
"        #   同层并列两把梯Y区间大面积重叠则不算同列;3)起步段:上行取同列梯底端最靠下(y_bottom最大=人当前层够得着\n"
"        #   起跳的那段),下行取梯顶端最靠上(y_top最小=往下接的第一段),端并列再取X近。单段列结果与旧\"X最近\"完全一致。\n"
"        best_x = min(cand, key=lambda t: abs(float(t['x']) - dx))\n"
"        _bx = float(best_x['x'])\n"
"\n"
"        def _same_col(t):\n"
"            if t is best_x:\n"
"                return True\n"
"            if abs(float(t['x']) - _bx) > LADDER_MM_SAME_COL_X:\n"
"                return False\n"
"            _ov = (min(float(t['y_bottom']), float(best_x['y_bottom']))\n"
"                   - max(float(t['y_top']), float(best_x['y_top'])))\n"
"            return _ov <= LADDER_MM_SAME_COL_OV\n"
"\n"
"        col = [t for t in cand if _same_col(t)] or [best_x]\n"
"        if cdir is not None and cdir < 0:\n"
"            return min(col, key=lambda t: (float(t['y_top']), abs(float(t['x']) - dx)))\n"
"        return max(col, key=lambda t: (float(t['y_bottom']), -abs(float(t['x']) - dx)))\n"
)
assert s.count(old_tail) == 1, "选梯尾部锚点不唯一/未命中: %d" % s.count(old_tail)
s = s.replace(old_tail, new_tail, 1)

out = s.replace('\n', '\r\n')
io.open(p, 'w', encoding='utf-8-sig', newline='').write(out)
print("PATCH WRITTEN OK")
