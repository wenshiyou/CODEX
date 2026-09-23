# -*- coding: utf-8 -*-
"""2026-09-22 补丁:
A 田字框上移时身后(下方)偏移500->150; B 下跳横跳错开梯子(改_pick_desc_side+三处调用);
C 战斗时钟诊断负数->max(0,..); D F10/F12启停落盘+行为栏; E 判活汇总未运行不刷。
逐锚点 assert count, 全过才写盘, 否则 exit3 不动文件。"""
import io, sys, os
P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(P, 'r', encoding='utf-8-sig', newline='') as f:
    s = f.read()
s = s.replace('\r\n', '\n')
edits = []

def add(old, new, n):
    edits.append((old, new, n))

# A1 田字常量
add(
"        FLOW_LIFT_Y = 150   # 水平移动时田字框在吊身后基础上再上移的像素(斜后方、不平齐人物;用户2026-09-20)",
"        FLOW_LIFT_Y = 150   # 水平移动时田字框在吊身后基础上再上移的像素(斜后方、不平齐人物;用户2026-09-20)\n"
"        FLOW_TAIL_GAP_UP_Y = 150  # 垂直【向上】移动时田字框吊在身后(下方)的偏移(用户2026-09-22:原500太靠底改150);向下移动仍吊上方FLOW_TAIL_GAP",
1)
# A2 田字垂直定位
add(
"                    _cx = _px; _cy = (_py - FLOW_TAIL_GAP) if _d > 0 else (_py + FLOW_TAIL_GAP)",
"                    _cx = _px; _cy = (_py - FLOW_TAIL_GAP) if _d > 0 else (_py + FLOW_TAIL_GAP_UP_Y)  # 上移(d<0)身后下方只偏150(用户2026-09-22)",
1)
# B0 避梯阈值常量
add(
"DESC_Y_MOVE_TOL = 5            # 方式二lad_grab:光点Y比基准增大>5=抓住梯子向下动了",
"DESC_Y_MOVE_TOL = 5            # 方式二lad_grab:光点Y比基准增大>5=抓住梯子向下动了\n"
"DESC_AVOID_LADDER_MM = 18     # 下跳横跳错开梯子:小地图光点X这一半径内、梯身竖向覆盖光点Y的梯=该侧有梯,横跳优先选无梯侧(用户2026-09-22);实心台两侧都跳不下仍由check_drop两次失败转方式二走梯",
1)
# B1 重写 _pick_desc_side
old_side = (
"    def _pick_desc_side(self):\n"
"        \"\"\"下行横跳方向:怪在右边选右(1),怪在左边选左(-1),没怪随机\"\"\"\n"
"        try:\n"
"            tx = getattr(self, '_target_monster_x', None)\n"
"            px = getattr(self, '_player_x', None)\n"
"            if tx is not None and px is not None:\n"
"                return 1 if tx > px else -1\n"
"        except Exception:\n"
"            pass\n"
"        return random.choice([-1, 1])"
)
new_side = (
"    def _pick_desc_side(self, px=None, py=None):\n"
"        \"\"\"下行横跳方向(用户2026-09-22改):第一优先【错开梯子】。横跳是为下穿平台,朝梯子跳会抓住梯=没跳下去还误转方式二。\n"
"        用小地图光点(px,py)与录制蓝梯self.ladders([{x,y_top,y_bottom}]):统计左右两侧 DESC_AVOID_LADDER_MM 内、\n"
"        梯身竖向覆盖光点Y 的最近梯距;仅一侧有梯->跳无梯侧;两侧都无->按怪方向、无怪参照随机;两侧都有->跳梯距更远侧。\n"
"        实心台真跳不下仍由check_drop两次失败后自动转方式二走到梯子位置下去,不在动作中途判。px/py必须是小地图坐标。\"\"\"\n"
"        try:\n"
"            if px is None or py is None:\n"
"                _mp = getattr(self, '_player_map_pos', None)\n"
"                if _mp:\n"
"                    px = _mp[0] if px is None else px\n"
"                    py = _mp[1] if py is None else py\n"
"            lds = getattr(self, 'ladders', None)\n"
"            left_gap = right_gap = None\n"
"            if lds and px is not None and py is not None:\n"
"                _pfx, _pfy = float(px), float(py)\n"
"                for _t in lds:\n"
"                    try:\n"
"                        tx = float(_t['x']); tt = float(_t['y_top']); tb = float(_t['y_bottom'])\n"
"                    except Exception:\n"
"                        continue\n"
"                    # 只看梯身竖向覆盖光点当前高度的梯(同层台边能被抓住的),别层梯不参与\n"
"                    if not (tt - DESC_AVOID_LADDER_MM <= _pfy <= tb + DESC_AVOID_LADDER_MM):\n"
"                        continue\n"
"                    if tx < _pfx:\n"
"                        g = _pfx - tx\n"
"                        left_gap = g if left_gap is None else min(left_gap, g)\n"
"                    else:\n"
"                        g = tx - _pfx\n"
"                        right_gap = g if right_gap is None else min(right_gap, g)\n"
"            l_near = left_gap is not None and left_gap <= DESC_AVOID_LADDER_MM\n"
"            r_near = right_gap is not None and right_gap <= DESC_AVOID_LADDER_MM\n"
"            if l_near and not r_near:\n"
"                _d = 1; _why = '左侧%.0f有梯,错开跳右' % left_gap\n"
"            elif r_near and not l_near:\n"
"                _d = -1; _why = '右侧%.0f有梯,错开跳左' % right_gap\n"
"            elif l_near and r_near:\n"
"                _d = 1 if right_gap >= left_gap else -1\n"
"                _why = '两侧皆有梯(左%.0f/右%.0f),跳更远的%s侧' % (left_gap, right_gap, '右' if _d > 0 else '左')\n"
"            else:\n"
"                tx = getattr(self, '_target_monster_x', None)\n"
"                if tx is not None and px is not None:\n"
"                    _d = 1 if tx > float(px) else -1\n"
"                    _why = '两侧无梯,按怪方向跳%s' % ('右' if _d > 0 else '左')\n"
"                else:\n"
"                    _d = random.choice([-1, 1]); _why = '两侧无梯无怪参照,随机'\n"
"            _debug_log('[下行·避梯] 横跳方向=%s (%s)' % ('右' if _d > 0 else '左', _why))\n"
"            return _d\n"
"        except Exception:\n"
"            return random.choice([-1, 1])"
)
add(old_side, new_side, 1)
# B2 方式一(5837)+方式二补跳(5978) 两处无参调用 -> 传小地图光点
add(
"                    self._desc_leap_dir = self._pick_desc_side()",
"                    self._desc_leap_dir = self._pick_desc_side(px, py)",
2)
# B3 方式二离梯(5935) 随机 -> 避梯
add(
"                self._desc_leap_dir = random.choice([-1, 1])   # 随机左/右拟人,避免每次同方向离梯",
"                self._desc_leap_dir = self._pick_desc_side(px, py)   # 用户2026-09-22:离梯侧跳也错开梯子,别又跳回另一把梯",
1)
# C 战斗时钟诊断负数
add(
"                int(self._combat_react_until - now), int(self._combat_turn_until - now),\n"
"                int(self._combat_busy_until - now), self._combat_locked_target,",
"                max(0, int(self._combat_react_until - now)), max(0, int(self._combat_turn_until - now)),\n"
"                max(0, int(self._combat_busy_until - now)), self._combat_locked_target,",
1)
# D1 F12 停止落盘+行为栏
add(
'                print("[停止] 脚本已停止 (F12)")\n'
'                self._add_log("脚本已停止 F12")',
'                print("[停止] 脚本已停止 (F12)")\n'
'                self._add_log("脚本已停止 F12")\n'
'                _debug_log("[停止] F12 已触发, _running=False, 运行层已停")\n'
'                try:\n'
'                    self._rlog("战斗已停止(F12)", LOG_RED, log=\'behavior\')\n'
'                except Exception:\n'
'                    pass',
1)
# D2 F10 启动行为栏
add(
'                _debug_log("[启动] F10 已触发, _running=True, hwnd=%s" % self.hwnd)',
'                _debug_log("[启动] F10 已触发, _running=True, hwnd=%s" % self.hwnd)\n'
'                try:\n'
'                    self._rlog("战斗已启动(F10)", LOG_OK, log=\'behavior\')\n'
'                except Exception:\n'
'                    pass',
1)
# E 判活汇总未运行不刷
add(
"            if now_ms - P['t0'] >= 5000:\n"
'                _debug_log("[判活汇总] 近5秒',
"            if not getattr(self, '_running', False):\n"
"                # 未运行(没点开始/F12或已停止):不统计不打印战斗判活;识别常开层照跑,照旧刷会造成'主攻0却血条命中=在打怪'假象(用户2026-09-22实锤长发呆根因)\n"
"                P['t0'] = now_ms\n"
"                for _kP in ('atk','aoe','win','probe_dmg','gate_dmg','hpframe','abhit','misalign','early','notskill'):\n"
"                    P[_kP] = 0\n"
"            elif now_ms - P['t0'] >= 5000:\n"
'                _debug_log("[判活汇总] 近5秒',
1)

# 逐锚点校验
for i, (old, new, n) in enumerate(edits):
    c = s.count(old)
    if c != n:
        print("ANCHOR FAIL #%d expect=%d got=%d\n--- old ---\n%s" % (i, n, c, old[:200]))
        sys.exit(3)
for old, new, n in edits:
    s = s.replace(old, new)
s = s.replace('\n', '\r\n')
with io.open(P, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(s)
print("PATCH OK, %d edits applied" % len(edits))
