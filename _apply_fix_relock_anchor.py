# -*- coding: utf-8 -*-
"""
2026-09-19 下跳/跳高窗 锚点定稿 原子脚本(用户最新拍板):
1. 跳高打腾空窗 SLOPE_HIGH_DOWN_BLOCK_MS 2000->3000, 起跳(17412已接线)即计时3秒, 窗内禁向下cross
2. 下跳重锁保护窗不判落地: 锚点改到"横跳"——方式一第二跳(5864)/方式二侧跳离梯(5986)那一刻起2秒
3. 落地reset只清锁, max()保留横跳窗剩余不缩短; 识别扫描全程不关(B总闸窗内只清锁不出包,怪表/YOLO照刷)
二进制 utf-8-sig 保BOM/LF; 逐处assert唯一; 任一失败不写盘; 末尾py_compile。
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
# 1. 腾空窗常量 2000->3000
E.append(("R1腾空窗常量3000",
"SLOPE_HIGH_DOWN_BLOCK_MS = 2000  # 跳高打最后一次起跳后多少ms内禁向下跳/向下cross(用户2026-09-19定稿600→2000:覆盖连续跳+落地站稳,人跳起Y变小期间绝不把脚下/同层怪误判成下方而下台;只拦向下,向上cross不拦;窗过期自然恢复)",
"SLOPE_HIGH_DOWN_BLOCK_MS = 3000  # 跳高打最后一次【起跳】起多少ms内禁向下跳/向下cross(用户2026-09-19定稿600→2000→3000:起跳即计时3秒,人跳起Y变小期间绝不把脚下/同层怪误判成下方而下台;只拦向下,向上cross不拦;窗过期自然恢复)", 1))
# 1b. 17412 起跳赋值注释更正(数值不写死)
E.append(("R2起跳点注释更正",
"                    self._slope_high_last_jump = now   # 记跳高打起跳:余温窗600ms内禁向下跳(用户2026-09-18)",
"                    self._slope_high_last_jump = now   # 记跳高打起跳时刻:起跳起3秒窗(SLOPE_HIGH_DOWN_BLOCK_MS)内禁向下cross(用户2026-09-19)", 1))
# 2a. DESCEND常量注释: 落地->横跳
E.append(("R3 DESCEND常量注释改横跳锚点",
'DESCEND_RELOCK_DELAY_MS = 2000  # 下跳(下台)【落地确认后】多少ms才许B重新锁怪(用户2026-09-19"下跳后2秒":人落稳、Y回地面再锁,杜绝下落/空中旧Y锁错层又把人带下去;到顶/走台/边界仍只150ms)',
'DESCEND_RELOCK_DELAY_MS = 2000  # 下跳(下台)【横跳(方式一第二跳/方式二侧跳离梯)后】多少ms才许B重新锁怪(用户2026-09-19定稿:不判落地,横跳起计时2秒,窗内B只清锁不出包、识别照开,到期用热怪表重锁;到顶/走台/边界仍只150ms)', 1))
# 2b. 方式一 第二跳(横跳)置窗
E.append(("R4方式一横跳起2秒窗",
"                    self._desc_j2 = True\n"
"                    self._desc_phase = 'check_drop'\n"
"                    self._desc_phase_t = now_ms\n"
"                    self._key_up(VK_LEFT)\n"
"                    self._key_up(VK_RIGHT)",
"                    self._desc_j2 = True\n"
"                    self._desc_phase = 'check_drop'\n"
"                    self._desc_phase_t = now_ms\n"
"                    self._arrival_relock_until = now_ms + DESCEND_RELOCK_DELAY_MS   # 横跳(第二跳)起2秒:窗内B只清锁不出包、识别照开,到期热怪表重锁(用户2026-09-19:不判落地,横跳后计时)\n"
"                    self._key_up(VK_LEFT)\n"
"                    self._key_up(VK_RIGHT)", 1))
# 2c. 方式二 侧跳离梯(横跳)置窗
E.append(("R5方式二侧跳横跳起2秒窗",
"                self._desc_jumped = True\n"
"                self._key_up(VK_LEFT)\n"
"                self._key_up(VK_RIGHT)   # 侧按100ms给个初速度即可,跳后松侧键避免落地还在横走\n"
"                self._desc_phase = 'lad_fall_wait'\n"
"                self._desc_phase_t = now_ms",
"                self._desc_jumped = True\n"
"                self._key_up(VK_LEFT)\n"
"                self._key_up(VK_RIGHT)   # 侧按100ms给个初速度即可,跳后松侧键避免落地还在横走\n"
"                self._desc_phase = 'lad_fall_wait'\n"
"                self._desc_phase_t = now_ms\n"
"                self._arrival_relock_until = now_ms + DESCEND_RELOCK_DELAY_MS   # 侧跳离梯(横跳)起2秒:窗内B只清锁不出包、识别照开,到期热怪表重锁(用户2026-09-19:不判落地,横跳后计时)", 1))
# 3. reset: 下跳来源max保留横跳窗, 不落地重算
E.append(("R6 reset保横跳窗不缩短",
"        # 重锁保护窗(用户2026-09-19定稿):到顶/走台/边界只挡150ms旧帧cross;唯独\"下跳(下台)落地\"保护到进descend+2秒——\n"
"        # 人落稳、Y回到地面值才许B锁怪,杜绝下落/空中旧Y把同层怪判成下层又把人带下去(方式二借梯侧跳耗时>2s,落地即按150ms)。\n"
"        _now_relock = time.time() * 1000\n"
"        if source in ('下行自由落', '借梯侧跳落下', '下跳落地'):\n"
"            self._arrival_relock_until = _now_relock + DESCEND_RELOCK_DELAY_MS   # 下跳【落地】起2秒才许B重锁(用户2026-09-19\"下跳后2秒\"):落稳Y回地面再锁,不把2秒耗在空中\n"
"        else:\n"
"            self._arrival_relock_until = _now_relock + 150",
"        # 重锁保护窗(用户2026-09-19定稿):下跳不判落地,2秒窗在\"横跳(方式一第二跳/方式二侧跳离梯)\"那一刻已起算;\n"
"        # 此处落地reset只清锁、用max保留横跳窗剩余(不被落地时刻缩短),横跳窗已过才给150ms短兜底;到顶/走台/边界一律150ms挡旧帧cross。\n"
"        _now_relock = time.time() * 1000\n"
"        if source in ('下行自由落', '借梯侧跳落下', '下跳落地'):\n"
"            self._arrival_relock_until = max(getattr(self, '_arrival_relock_until', 0), _now_relock + 150)   # 保留横跳起算的2秒窗剩余\n"
"        else:\n"
"            self._arrival_relock_until = _now_relock + 150", 1))

def main():
    t = load(MAPLE)
    for label, old, new, cnt in E:
        c = t.count(old)
        if c != cnt:
            print("[FAIL] %s 命中%d(期望%d)" % (label, c, cnt)); sys.exit(1)
        t = t.replace(old, new); print("[OK]", label)
    # 自检
    assert "SLOPE_HIGH_DOWN_BLOCK_MS = 3000" in t
    assert t.count("self._arrival_relock_until = now_ms + DESCEND_RELOCK_DELAY_MS") == 2, "两处横跳置窗"
    assert "落地】起2秒" not in t and "落地确认后" not in t
    print("[OK] 自检通过(腾空3000/两处横跳置窗/落地锚点已清)")
    save(MAPLE, t)
    py_compile.compile(MAPLE, doraise=True)
    print("[DONE] 写回+py_compile通过")

if __name__ == "__main__":
    main()
