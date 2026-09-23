# -*- coding: utf-8 -*-
# 修复：锁后只看X不看Y -> 锁错梯/原地空跳。让"梯底Y门"贯穿锁后对位全程,连续2帧Y不合格即解锁重选。
import io, sys

p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
raw = io.open(p, "rb").read().decode("utf-8-sig")
norm = raw.replace("\r\n", "\n")
edits = []

# 1) 常量：紧跟 LADDER_MM_END_TOL 后新增锁后Y复核容差与连续帧
A_OLD = "LADDER_MM_END_TOL = 10      # 合格高度门:上行梯底y_bottom与光点Y差<=10(人跳起够得到底端)/下行梯顶y_top与光点Y差<=10\n"
A_NEW = A_OLD + (
    "LADDER_MM_GOTO_END_TOL = 14    # 锁后对位/起跳前Y复核容差(比选梯10略宽,抗走动光点量化):上行|梯底y_bottom-光点Y|<=此值且梯身上通才继续,否则解锁重选(用户2026-09-22:锁后只看X会锁错梯空跳)\n"
    "LADDER_MM_GOTO_UNLOCK_FRAMES = 2  # 锁后连续几帧Y不合格才解锁重选(与锁梯2帧对称,防光点单帧抖动误解锁)\n"
)
edits.append(("常量", A_OLD, A_NEW))

# 2) _reset_climb 清全套锁状态处,加新计数复位
B_OLD = "        self._ladder_mm_still_frames = 0    # 连续停稳拍数(直跳门槛)\n"
B_NEW = B_OLD + "        self._ladder_mm_ybad_streak = 0    # 锁后梯底Y不合格连续帧(出梯/换梯清零,用户2026-09-22)\n"
edits.append(("reset计数", B_OLD, B_NEW))

# 3) goto_tick 已锁段 ad=abs(d) 后插入每帧Y复核
C_OLD = "        # ---- 2) 已锁:算人梯差/朝梯速度/停稳 ----\n        d = float(ld['x']) - float(px)\n        ad = abs(d)\n"
C_NEW = C_OLD + (
    "        # ---- 2.0) 锁后全程Y复核(用户2026-09-22:锁后只看X不看Y,人漂到梯身/梯顶高度仍按X对位起跳=锁错梯空跳) ----\n"
    "        # 上行合格=梯底贴光点(容差GOTO_END_TOL,比选梯略宽抗量化)且梯身上通;连续GOTO_UNLOCK_FRAMES帧不合格才解锁,\n"
    "        # 用最新光点重新过X+Y门选当前够得着的梯(选不到走NOPICK超时回主线);不足连续帧本帧不起跳/不走向,松键等下一帧复核。\n"
    "        _goto_yb = float(ld['y_bottom']); _goto_yt = float(ld['y_top']); _goto_py = float(py)\n"
    "        if (abs(_goto_yb - _goto_py) <= LADDER_MM_GOTO_END_TOL\n"
    "                and _goto_yt <= _goto_py - LADDER_MM_GOTO_END_TOL):\n"
    "            self._ladder_mm_ybad_streak = 0\n"
    "        else:\n"
    "            self._ladder_mm_ybad_streak = getattr(self, '_ladder_mm_ybad_streak', 0) + 1\n"
    "            if self._ladder_mm_ybad_streak >= LADDER_MM_GOTO_UNLOCK_FRAMES:\n"
    "                _debug_log(\"[选梯·小地图] 锁后Y不合格连续%d帧(梯底%.0f/梯顶%.0f/光点Y%.0f,|底-光|=%.0f 容差%d):这把已够不着底,解锁用最新光点重选\" % (\n"
    "                    LADDER_MM_GOTO_UNLOCK_FRAMES, _goto_yb, _goto_yt, _goto_py, abs(_goto_yb - _goto_py), LADDER_MM_GOTO_END_TOL))\n"
    "                self._ladder_mm_lock_id = None\n"
    "                self._ladder_mm_cand_id = None\n"
    "                self._ladder_mm_cand_streak = 0\n"
    "                self._ladder_mm_pick_t = 0\n"
    "                self._ladder_mm_ybad_streak = 0\n"
    "                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)\n"
    "            else:\n"
    "                # 不足连续帧:松键停一拍等下一帧复核,绝不在错误Y上起跳\n"
    "                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)\n"
    "                self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad\n"
    "            return False\n"
)
edits.append(("gotoY复核", C_OLD, C_NEW))

for name, old, new in edits:
    c = norm.count(old)
    if c != 1:
        print("ANCHOR FAIL [%s] count=%d" % (name, c)); sys.exit(3)
    norm = norm.replace(old, new)

io.open(p, "w", encoding="utf-8-sig", newline="").write(norm.replace("\n", "\r\n"))
print("PATCH OK 3处:", ", ".join(n for n, _, _ in edits))
