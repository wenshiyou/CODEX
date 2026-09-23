# -*- coding: utf-8 -*-
# 上梯规则改造(用户2026-09-23定稿):选梯/锁后高度门收为光点与梯端重合±1;
# 好梯到顶=光点与梯顶重合±1 且 当下后脑不可见(补按150ms开打,不干等450ms);坏梯保留纯后脑450+总超时;下行不动。
import io, sys

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
raw = io.open(P, "rb").read().decode("utf-8-sig")
s = raw.replace("\r\n", "\n")

REPL = []

# 1) 高度门常量 10 -> 1
REPL.append((
"LADDER_MM_END_TOL = 10      # 合格高度门:上行梯底y_bottom与光点Y差<=10(人跳起够得到底端)/下行梯顶y_top与光点Y差<=10",
"LADDER_MM_END_TOL = 1       # 合格高度门=光点与梯连接端重合±1(用户2026-09-23定稿\"直接选光点和梯底重合的,容差都不用\"):上行|y_bottom-光点Y|<=1且梯身在人上方/下行|y_top-光点Y|<=1且梯身下通;差>=2即非本层梯排除(旧值10会选到悬在头顶的上段)"
))

# 2) 到顶位置门注释 + hold 200 -> 150 (686-688 三行)
REPL.append((
"""LADDER_TOP_ARRIVE_TOL = 1  # 爬梯到顶验证(用户2026-09-11晚)：光点与梯顶重合或高于梯顶即到,容差只留1px当检测误差；
# 且用"到达/越过"单向判定(上行 py<=y_top+2),人还在顶端下方(差>2)绝不判到顶——旧版abs≤8会提前8px松手导致没翻上平台就掉下
LADDER_TOP_HOLD_MS = 200    # 到顶多按(用户2026-09-15):光点与录制梯端完全重合后,继续按住↑/↓200ms再松,确保整个人翻上台/踩稳""",
"""LADDER_TOP_ARRIVE_TOL = 1  # 爬梯到顶位置门(用户2026-09-23定稿):光点与录制梯顶【重合】|光点y-梯顶y|<=1(差0/1到、差>=2还在梯中继续按↑);录的是最高点不越过,废弃旧\"到达/越过py<=y_top+2\"
# 到顶双判:位置重合±1只是前提,还要【当下后脑不可见】(已翻出梯)才判到顶;位置没到(差>=2)后脑丢失按漏检处理继续爬(用户2026-09-23)
LADDER_TOP_HOLD_MS = 150    # 到顶多按(用户2026-09-23:200->150):重合±1且后脑当下不可见后继续按住↑/↓150ms再松,立即开主线开打,不干等450ms"""
))

# 3) climbing 主判据注释 (6215-6216)
REPL.append((
"""            # === 到顶主判据(用户2026-09-18,仅上行):后脑勺连续BACK_TOP_LOST_MS看不到=人已翻出台子到顶。
            # 小地图光点重合梯端仅作兜底(后脑漏检/没录到梯端时);下行不接后脑,仍只认光点对y_bottom。总超时保命不变。 ===""",
"""            # === 到顶判据(用户2026-09-23定稿,仅上行):好梯=光点与梯顶重合±1 且 当下后脑不可见(已翻台)即到顶,补按150ms开打,不干等450ms;
            # 梯中(光点距梯顶差>=2)以光点距离为主、后脑丢失按漏检继续按↑;坏梯(没录到梯端)才用纯后脑连续BACK_TOP_LOST_MS+总超时兜底。下行不接后脑,仍只认光点对y_bottom。 ==="""
))

# 4) _dot_at_top 单向越过 -> 双向重合±1 (6240)
REPL.append((
"            _dot_at_top = bool(_end_y) and py <= _end_y + LADDER_TOP_ARRIVE_TOL",
"            _dot_at_top = bool(_end_y) and abs(py - _end_y) <= LADDER_TOP_ARRIVE_TOL  # 上行位置门=光点与梯顶重合±1(差0/1);差>=2还在梯中不判顶(用户2026-09-23,废弃单向越过py<=top+1)"
))

# 5) 好梯/坏梯 _ladder_back_top (6242-6249)
REPL.append((
"""            if _up:
                if _end_y:
                    # 好梯(录到梯端):光点没到顶(还在梯中/梯底)时后脑丢失=漏检,绝不判顶、继续按↑;
                    # 光点到顶后,后脑连续丢满BACK_TOP_LOST_MS才确认翻台(_top_by_back)
                    self._ladder_back_top = bool(_lost_enough and _dot_at_top)
                else:
                    # 坏梯(没录到梯端):无光点判据,纯后脑连续丢满=到顶,总超时(录制时长+2s)保命
                    self._ladder_back_top = bool(_lost_enough)""",
"""            if _up:
                if _end_y:
                    # 好梯(录到梯端,用户2026-09-23):到顶交下面_map_ok_up快判(光点与梯顶重合±1且当下后脑不可见),不再要求后脑连续丢满450ms;
                    # 梯中(差>=2)_dot_at_top=False,后脑丢失=漏检绝不判顶、继续按↑。此慢标志好梯恒False,仅坏梯用
                    self._ladder_back_top = False
                else:
                    # 坏梯(没录到梯端):无光点位置判据,才用纯后脑连续丢满BACK_TOP_LOST_MS=到顶,总超时(录制时长+2s)保命
                    self._ladder_back_top = bool(_lost_enough)"""
))

# 6) _map_ok_up 快判: 重合±1 且 当下后脑不可见 (6251-6253)
REPL.append((
"""            # 上行快判:光点已到梯顶且后脑刚开始消失(lost已起算,哪怕1帧)=立即到顶,不干等BACK_TOP_LOST_MS;
            # 光点没到顶不成立(梯中漏检不误判);坏梯(_end_y=0)不走快判,退回纯后脑/总超时
            _map_ok_up = bool(_up and bool(_end_y) and self._ladder_back_lost_since > 0 and _dot_at_top)""",
"""            # 上行快判(用户2026-09-23定稿):光点与梯顶重合±1(_dot_at_top)且【当下后脑不可见】(_bv=False)=已翻台到顶,立即hold补按150ms开打,不干等450ms;
            # 梯中(差>=2)_dot_at_top=False不成立(后脑漏检不误判);重合但后脑仍可见=还没翻出去,不成立继续按↑;坏梯(_end_y=0)不走快判退回纯后脑/总超时
            _map_ok_up = bool(_up and bool(_end_y) and _dot_at_top and not _bv)"""
))

# 7) 快判到顶日志措辞 (6263)
REPL.append((
'                        _why0 = "光点到梯顶且后脑已消失=快判到顶,补按%dms" % LADDER_TOP_HOLD_MS',
'                        _why0 = "光点与梯顶重合±1且后脑当下不可见=到顶,补按%dms开打" % LADDER_TOP_HOLD_MS'
))

# 8) 总超时注释 hold 200 -> 150 (6270)
REPL.append((
"            # 总超时保命(没录到梯端/后脑误判防永久卡梯);已进hold(200ms内必收尾)不再被超时打断",
"            # 总超时保命(没录到梯端/后脑误判防永久卡梯);已进hold(150ms内必收尾)不再被超时打断"
))

# 9) 后脑常量区注释 716 (450 仅坏梯)
REPL.append((
"#   抓住=起跳后连续2帧看到后脑;到顶=climbing中连续450ms看不到后脑(已翻出台子,再补按↑LADDER_TOP_HOLD_MS翻稳;光点没到顶=漏检不判顶),",
"#   抓住=起跳后连续2帧看到后脑;好梯到顶=光点与梯顶重合±1且当下后脑不可见(补按↑LADDER_TOP_HOLD_MS=150ms翻稳,不干等450);坏梯(没录到梯端)才用连续450ms看不到后脑;光点没到顶=漏检不判顶,"
))

# 10) BACK_TOP_LOST_MS 注释 721
REPL.append((
"BACK_TOP_LOST_MS = 450          # climbing中连续多久看不到后脑=翻出平台到顶(用户2026-09-22:333→450调长抗低帧漏检;新逻辑光点没到顶=梯中漏检不判顶继续爬,仅光点到顶后才用此时长确认翻台,坏梯纯后脑+总超时兜底)",
"BACK_TOP_LOST_MS = 450          # 仅【坏梯(没录到梯端)】用:climbing连续多久看不到后脑=翻出平台到顶;好梯到顶走光点重合±1+当下后脑不可见快判(用户2026-09-23),不用此时长;好梯若后脑误检恒可见则总超时保命"
))

for i, (old, new) in enumerate(REPL, 1):
    c = s.count(old)
    if c != 1:
        print("ANCHOR FAIL #%d count=%d" % (i, c))
        print("---- OLD ----")
        print(old[:200])
        sys.exit(1)
    s = s.replace(old, new)
    print("ok #%d" % i)

out = s.replace("\n", "\r\n")
io.open(P, "w", encoding="utf-8-sig", newline="").write(out)
print("WROKEN", len(out))
