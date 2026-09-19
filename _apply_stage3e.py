# -*- coding: utf-8 -*-
"""阶段3c: 绘制层梯子框 X+Y 双判——锁梯这把实时帧被双判剔除白框只画红框(同点),空帧冻块补位红框,始终只一个框。"""
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s = open(P, "rb").read().decode("utf-8-sig")
log = []
def rep(old, new, n=1, tag=""):
    global s
    c = s.count(old)
    assert c == n, "[%s] 命中%d次(期望%d) old=%r" % (tag, c, n, old[:80])
    s = s.replace(old, new); log.append("OK " + tag)

# 取锁点Y
rep(
'''                                _ld_sel = data.get('ladder_sel')
                                _sel_x = _ld_sel[0] if _ld_sel else None''',
'''                                _ld_sel = data.get('ladder_sel')
                                _sel_x = _ld_sel[0] if _ld_sel else None
                                _sel_y = _ld_sel[1] if _ld_sel else None''',
    tag="取锁点Y")

# 白框剔除锁: X单判 → X+Y双判(同合并阈值),根治同X不同Y两把梯误剔/红白双框
rep(
'''                                        if _sel_x is not None and abs(_lmx - _sel_x) <= LADDER_MARK_NMS_X:
                                            continue   # 被选中的这把白框不画(下面原地转红框)''',
'''                                        if _sel_x is not None and _sel_y is not None and abs(_lmx - _sel_x) <= LADDER_MERGE_DX and abs(_lmy - _sel_y) <= LADDER_MERGE_DY:
                                            continue   # 被选中的这把白框不画(X+Y双判同一把,下面原地转红框;用户2026-09-19根治红白双框)''',
    tag="白框双判")

# 红框编号反查同步双判
rep(
'''                                        if len(_lm) > 2 and _lm[2] and abs(_lm[0] - _sx) <= LADDER_MARK_NMS_X and abs(_lm[1] - _sy) <= 60:''',
'''                                        if len(_lm) > 2 and _lm[2] and abs(_lm[0] - _sx) <= LADDER_MERGE_DX and abs(_lm[1] - _sy) <= LADDER_MERGE_DY:''',
    tag="红框编号双判")

open(P, "wb").write(s.encode("utf-8-sig"))
import py_compile
py_compile.compile(P, doraise=True)
print("\n".join(log)); print("阶段3c写回并编译通过")
