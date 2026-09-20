# -*- coding: utf-8 -*-
"""判活时间窗改:POST_STRIKE_CHECK_MS 450→100(开始看血条/伤害);加STRIKE_DEADLINE_MS=500(判死截止)。
maple_route_ui.py(utf-8-sig/LF),唯一锚点assert。"""
import io, py_compile
CP = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(CP, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()

old = "POST_STRIKE_CHECK_MS = 450 # 攻击后反馈检测窗口(用户2026-09-11:130→450)：首次出手满450ms后才看血条/伤害判\"打死没/是不是空怪\";怪多/特效/掉帧(实测帧率曾掉到1-3fps)时130ms拿不到出手后稳定帧、真怪被当空怪清掉→一圈怪轮流锁左右抖;另须拿到出手之后的新帧才判,避免用出手前旧帧误丢真怪"
new = ("POST_STRIKE_CHECK_MS = 100 # 攻击后开始检测血条/伤害(用户2026-09-20:450→100):首次出手满100ms就开始看头顶血条/伤害,不再干等\n"
"STRIKE_DEADLINE_MS = 500   # 判死截止(2026-09-20定稿):首次出手满500ms仍无血条无伤害=空怪/已死才drop;100~500ms间出现血条/伤害=打着怪")
assert s.count(old) == 1, "锚点命中%d次" % s.count(old)
s = s.replace(old, new)
with io.open(CP, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
py_compile.compile(CP, doraise=True)
print("TIMEWIN_OK")
