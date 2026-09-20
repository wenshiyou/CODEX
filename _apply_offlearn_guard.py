# -*- coding: utf-8 -*-
"""2026-09-20 补充: 锚点偏移学习·几何合理性门控(取证: 姿势门控后face仍0.54误匹配在人名外134px, 要把off_face从(3,61)拉到(134,22))。
已有偏移时新样本与现偏移相差>ANCHOR_OFF_LEARN_MAXDEV 即判误匹配丢弃不学; 冷启动首帧仍采用。"""
import os
ROOT = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(ROOT, "maple_route_ui.py")
raw = open(PY, "rb").read()
bom = raw.startswith(b"\xef\xbb\xbf")
s = raw.decode("utf-8-sig"); orig = s
def rep(old, new, tag):
    global s
    n = s.count(old); assert n == 1, "[%s]命中%d次" % (tag, n)
    s = s.replace(old, new); print("[OK]", tag)

rep(
    'AUX_ANCHOR_MAX_MOVE = 80   # 脸/后脑/宠物这些【兜底锚点】映射点相对上一可信基点的最大合法跳变px(用户2026-09-20):兜底锚点误匹配多,不能像人名那样允许maxmove=250的瞬移,>80且弱匹配(<0.75)即当误匹配丢弃,全图重搜帧也生效',
    'AUX_ANCHOR_MAX_MOVE = 80   # 脸/后脑/宠物这些【兜底锚点】映射点相对上一可信基点的最大合法跳变px(用户2026-09-20):兜底锚点误匹配多,不能像人名那样允许maxmove=250的瞬移,>80且弱匹配(<0.75)即当误匹配丢弃,全图重搜帧也生效\n'
    'ANCHOR_OFF_LEARN_MAXDEV = 70  # 脸/后脑学"→人名"偏移时,新量几何差与已学/固化偏移允许的最大偏离px(用户2026-09-20):超过=锚点本帧误匹配在人名外、丢弃不学,锁死固化几何(实测误匹配偏离可达134px,正常帧间抖动<30)',
    "常量ANCHOR_OFF_LEARN_MAXDEV")

rep(
    '                _dx, _dy = _nloc[0] - _g[1][0], _nloc[1] - _g[1][1]\n'
    '                _o = tr.get("off_" + _kk)\n'
    '                if _o is None:\n'
    '                    tr["off_" + _kk] = [float(_dx), float(_dy)]; tr["off_n_" + _kk] = 1\n'
    '                else:  # EMA平滑,避免单帧抖动让基点飘\n'
    '                    _o[0] = _o[0] * 0.7 + _dx * 0.3; _o[1] = _o[1] * 0.7 + _dy * 0.3\n'
    '                    tr["off_n_" + _kk] = tr.get("off_n_" + _kk, 0) + 1',
    '                _dx, _dy = _nloc[0] - _g[1][0], _nloc[1] - _g[1][1]\n'
    '                _o = tr.get("off_" + _kk)\n'
    '                # 几何合理性门控(用户2026-09-20取证补):姿势门控过了锚点仍可能低分误匹配在人名外(实测平地face 0.54命中点离人名134px)\n'
    '                # 已有偏移时,新样本与现偏移相差>ANCHOR_OFF_LEARN_MAXDEV即判本帧误匹配、丢弃不学,锁死固化几何;冷启动(无偏移)首帧仍采用,之后由门控+EMA收敛。\n'
    '                if _o is not None and np.hypot(_dx - _o[0], _dy - _o[1]) > ANCHOR_OFF_LEARN_MAXDEV:\n'
    '                    continue\n'
    '                if _o is None:\n'
    '                    tr["off_" + _kk] = [float(_dx), float(_dy)]; tr["off_n_" + _kk] = 1\n'
    '                else:  # EMA平滑,避免单帧抖动让基点飘\n'
    '                    _o[0] = _o[0] * 0.7 + _dx * 0.3; _o[1] = _o[1] * 0.7 + _dy * 0.3\n'
    '                    tr["off_n_" + _kk] = tr.get("off_n_" + _kk, 0) + 1',
    "偏移学习几何合理性门控")

assert s != orig
open(PY, "wb").write((b"\xef\xbb\xbf" if bom else b"") + s.replace("\r\n", "\n").encode("utf-8"))
print("[DONE] BOM=%s" % bom)
