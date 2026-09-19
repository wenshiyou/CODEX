# -*- coding: utf-8 -*-
"""
2026-09-19 误下跳治理 收尾原子脚本(复盘修正):
- 保护窗口径修正: 进descend+2s -> 下跳【落地】起2s(贴合用户"下跳后2秒"); 删除随之失去用途的 _descend_enter_t 字段/赋值
- 清 hold 失效残留(读取已删, 仅剩默认配置项+面板滑块=显示却不生效)
- 更正被删Y钉的过时注释(两态基线/冻结/停最后脚点 -> 实时Y); 只动注释与失效配置, 零逻辑改动
二进制 utf-8-sig 保BOM/LF; 逐处assert唯一; 任一失败不写盘。
"""
import sys, py_compile
MAPLE = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"

def load(p):
    raw = open(p, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf"), "maple缺BOM,停"
    return raw.decode("utf-8-sig")

def save(p, t):
    open(p, "wb").write((b"\xef\xbb\xbf" + t.encode("utf-8")))

E = []
# --- 常量注释: 进descend起 -> 落地起
E.append(("N1常量注释改落地起算",
"DESCEND_RELOCK_DELAY_MS = 2000  # 下跳(下台)后进descend起多少ms才许B重新锁怪(用户2026-09-19定稿:人落稳、Y回地面再锁,杜绝空中/下落旧Y锁错层又把人带下去;到顶/走台仍只150ms)",
"DESCEND_RELOCK_DELAY_MS = 2000  # 下跳(下台)【落地确认后】多少ms才许B重新锁怪(用户2026-09-19\"下跳后2秒\":人落稳、Y回地面再锁,杜绝下落/空中旧Y锁错层又把人带下去;到顶/走台/边界仍只150ms)", 1))

# --- 删 _descend_enter_t 字段与enter赋值(落地起算后不再需要)
E.append(("N2删_descend_enter_t字段",
"        self._descend_enter_t = 0          # 进下跳(descend)时刻ms:落地重锁保护期=此刻+DESCEND_RELOCK_DELAY_MS(用户2026-09-19)\n", "", 1))
E.append(("N3删enter_descend时刻赋值",
"        self._descend_enter_t = now_ms   # 进下跳时刻(用户2026-09-19):落地重锁保护到此刻+DESCEND_RELOCK_DELAY_MS(2秒),人落稳Y回地面再许B锁怪\n", "", 1))

# --- M20口径: 落地起2秒
E.append(("N4 reset保护窗改落地起算",
"        if source in ('下行自由落', '借梯侧跳落下', '下跳落地'):\n"
"            self._arrival_relock_until = max(_now_relock + 150, getattr(self, '_descend_enter_t', 0) + DESCEND_RELOCK_DELAY_MS)\n"
"        else:\n"
"            self._arrival_relock_until = _now_relock + 150",
"        if source in ('下行自由落', '借梯侧跳落下', '下跳落地'):\n"
"            self._arrival_relock_until = _now_relock + DESCEND_RELOCK_DELAY_MS   # 下跳【落地】起2秒才许B重锁(用户2026-09-19\"下跳后2秒\"):落稳Y回地面再锁,不把2秒耗在空中\n"
"        else:\n"
"            self._arrival_relock_until = _now_relock + 150", 1))

# --- hold 失效残留清理
E.append(("N5删hold默认配置",
'    "hold": 90,        # 丢失保持(帧):刚丢先保持上一可信点,不立刻乱跳\n', "", 1))
E.append(("N6删面板hold滑块",
'    ("research", "全图搜索ms", False), ("hold", "丢失保持", False),',
'    ("research", "全图搜索ms", False),', 1))

# --- 过时Y钉注释更正(只改注释)
E.append(("N7主线分层三行旧注释收敛",
"        # 人怪Y分层用两态地面基线_layer_y(用户2026-09-19定稿,人物线程每帧维护):\n"
"        # 打怪态(最近1秒出过攻击键)=最近2秒人名中心Y最大值(屏幕最靠下=脚踩地面),跳起Y变小不污染分层、不误判怪在下方乱下跳;\n"
"        # 连续1秒没出手(走路/巡路/上下梯)=移动态,Y实时跟手;移动→打怪上升沿清窗重采,上高层不带旧层大Y。X永远实时不进窗。",
"        # 人怪Y分层:Y实时不冻结(用户2026-09-19删地面Y钉),px/py都取当帧特征/黑框基点;误下跳改由\"跳高腾空窗2秒+下行必经cross+落地2秒重锁\"根治", 1))
E.append(("N8怪分类_dy注释",
"                _dy = _mcy - py_layer  # 怪脚Y - 人物落地基线Y（负=怪在上,正=怪在下;用基线不被腾空带偏）",
"                _dy = _mcy - py_layer  # 怪脚Y - 人物实时Y(负=怪在上,正=怪在下;腾空误判由跳高腾空窗/cross门控拦)", 1))
E.append(("N9竖直瞬移_dyv注释",
"            _dyv = t_cy - py_layer                                        # 正=怪在人物下方,负=在上方(用落地基线,腾空不误触发竖直瞬移)",
"            _dyv = t_cy - py_layer                                        # 正=怪在人物下方,负=在上方(实时Y)", 1))
E.append(("N10跳高_above2注释",
"        _above2 = py_layer - _ref_y   # 怪在人物落地基线上方多少px(正=怪上方;用基线,人跳起不误落进跳高打区间空打)",
"        _above2 = py_layer - _ref_y   # 怪在人物实时Y上方多少px(正=怪上方;跳高打只在high_slope分支,人腾空走该分支return,不落到此)", 1))
E.append(("N11 _below2注释",
'        _below2 = (t_cy - py_layer) > _atk_y_down   # 用落地基线:人跳起时地面怪不会瞬时变"正下方"误触发下跳(用户2026-09-11)',
'        _below2 = (t_cy - py_layer) > _atk_y_down   # 实时Y;正下方够不着不再原地按↓跳(旁路已删),由B判cross走完整下跳,腾空误判由跳高腾空窗2秒拦', 1))
E.append(("N12跳高段冻结基线注释",
"            # 群攻/普通模式共用这一套(用户2026-09-11)。人物Y基点用跳前冻结基线py_layer(人跳起时Y不变,治腾空误判)。",
"            # 群攻/普通模式共用这一套(用户2026-09-11)。人物Y用实时py_layer(2026-09-19删冻结基线),腾空误向下由跳高腾空窗2秒拦。", 1))
E.append(("N13主攻_dy_atk注释",
"            _dy_atk = t_cy - py_layer  # 主攻Y门控用落地基线:人腾空瞬时Y不决定出不出手",
"            _dy_atk = t_cy - py_layer  # 主攻Y门控用实时Y;人腾空_stance_ok不成立本就不出手,落地站稳才判定", 1))
E.append(("N14定位失配注释",
"        # 没定出:失配计数,全图没找到也重置全图计时(避免每帧全图);停在最后脚点继续等重搜",
"        # 没定出:失配计数,全图没找到也重置全图计时(避免每帧全图);黑框也缺就返回None不停旧点(用户2026-09-19),下帧靠局部窗快跟", 1))
E.append(("N15黑框docstring注释",
"        与特征点同为游戏窗口像素系;Y两态基线照喂此点;人名恢复当帧由_get_player_screen_pos自动切回特征。\"\"\"",
"        与特征点同为游戏窗口像素系;人物实时Y照喂此点;人名恢复当帧由_get_player_screen_pos自动切回特征。\"\"\"", 1))

def main():
    t = load(MAPLE)
    for label, old, new, cnt in E:
        c = t.count(old)
        if c != cnt:
            print("[FAIL] %s 命中%d(期望%d)" % (label, c, cnt)); sys.exit(1)
        t = t.replace(old, new); print("[OK]", label)
    for sym in ["_descend_enter_t", '"hold"', '("hold"', "两态地面基线", "冻结基线py_layer", "停在最后脚点"]:
        if sym in t:
            print("[FAIL] 残留: %s (%d)" % (sym, t.count(sym))); sys.exit(1)
    print("[OK] 收尾残留自检=EMPTY")
    save(MAPLE, t)
    py_compile.compile(MAPLE, doraise=True)
    print("[DONE] 收尾写回+py_compile通过")

if __name__ == "__main__":
    main()
