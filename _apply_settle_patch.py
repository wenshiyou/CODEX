# -*- coding: utf-8 -*-
# A:直跳最后松方向键后静止220ms才起跳(治带1px动量跳偏); B:直跳3次失败回主线补120ms压制窗先清下层。count==1。
import io, sys
PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    content = f.read()
edits = []

# 1) 新增静止门控常量
edits.append((
 u'LADDER_MM_ALIGN_OK_DX = 0.6  # 直跳起跳对齐门槛(小地图px,用户2026-09-26):|人梯X差|≤此值(≈0)才跳,治差1上不去',
 u'LADDER_MM_ALIGN_OK_DX = 0.6  # 直跳起跳对齐门槛(小地图px,用户2026-09-26):|人梯X差|≤此值(≈0)才跳,治差1上不去\nLADDER_MM_SETTLE_KEY_MS = 220  # 直跳最后一次松方向键后须再静止这么久才起跳(用户2026-09-26:点动带1px动量就跳=跳偏,留时间让脚步走完速度归零)'))

# 2) align_reset 初始化 last_move_t
edits.append((
 u'        self._ladder_mm_coast_still = 0\n        self._ladder_mm_nudge_count = 0',
 u'        self._ladder_mm_coast_still = 0\n        self._ladder_mm_nudge_count = 0\n        self._ladder_mm_last_move_t = 0'))

# 3) approach 松键记录时刻
edits.append((
 u'                self._ladder_mm_coast_in = (ad, v); self._ladder_mm_coast_still = 0\n                self._ladder_mm_brake_done = False',
 u'                self._ladder_mm_coast_in = (ad, v); self._ladder_mm_coast_still = 0\n                self._ladder_mm_brake_done = False\n                self._ladder_mm_last_move_t = now_ms'))

# 4) nudge 到期松键记录时刻
edits.append((
 u'        if ph == \'nudge\':\n            if now_ms - self._ladder_mm_align_t >= LADDER_MM_NUDGE_MS:\n                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)\n                self._ladder_mm_align_phase = \'coast\'; self._ladder_mm_align_t = now_ms\n                self._ladder_mm_coast_still = 0\n            return False',
 u'        if ph == \'nudge\':\n            if now_ms - self._ladder_mm_align_t >= LADDER_MM_NUDGE_MS:\n                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)\n                self._ladder_mm_align_phase = \'coast\'; self._ladder_mm_align_t = now_ms\n                self._ladder_mm_coast_still = 0\n                self._ladder_mm_last_move_t = now_ms\n            return False'))

# 5) goto 直跳条件加静止门控
edits.append((
 u'        if ad <= LADDER_MM_ALIGN_OK_DX and self._ladder_mm_still_frames >= LADDER_MM_STILL_FRAMES:',
 u'        if (ad <= LADDER_MM_ALIGN_OK_DX and self._ladder_mm_still_frames >= LADDER_MM_STILL_FRAMES\n                and now_ms - getattr(self, \'_ladder_mm_last_move_t\', 0) >= LADDER_MM_SETTLE_KEY_MS):'))

# 6) 失败回主线补压制窗
edits.append((
 u'        self._release_all_keys()\n        _debug_log("[跨层] 爬梯失败，丢弃目标回正常找怪（先锁下面Y相近的，清完再重新上）")',
 u'        self._release_all_keys()\n        self._climb_fail_pause_until = int(time.time() * 1000) + LADDER_FAIL_REENTER_MS  # 补压制窗(用户2026-09-26):别立刻又上梯,先让B锁同层怪\n        _debug_log("[跨层] 爬梯失败，丢弃目标回正常找怪（先锁下面Y相近的，清完再重新上）")'))

for i, (old, new) in enumerate(edits, 1):
    c = content.count(old)
    if c != 1:
        print("[FAIL] edit%d count=%d -> abort" % (i, c)); sys.exit(1)
    content = content.replace(old, new, 1)
with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("DONE: %d edits" % len(edits))
