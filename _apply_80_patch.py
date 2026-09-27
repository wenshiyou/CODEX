# -*- coding: utf-8 -*-
# 直跳:松键80ms观察窗+停稳2帧+尝试上限2次;回主线删压制窗、直接开锁怪。count==1。
import io, sys
PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    content = f.read()
edits = [
 (u'LADDER_MM_SETTLE_KEY_MS = 220  # 直跳最后一次松方向键后须再静止这么久才起跳(用户2026-09-26:点动带1px动量就跳=跳偏,留时间让脚步走完速度归零)',
  u'LADDER_MM_SETTLE_KEY_MS = 80   # 直跳最后一次松方向键后的短观察窗(用户2026-09-26:220太久改80):80ms后检测,对齐就跳、不齐继续点动对准'),
 (u'LADDER_MM_STILL_FRAMES = 4       # 直跳需连续几拍停稳才原地跳(用户2026-09-26:2帧太短没停透,改4≈180ms真停稳,goto/coast共用)',
  u'LADDER_MM_STILL_FRAMES = 2       # 直跳停稳帧数(用户2026-09-26:配合80ms观察窗约2帧,80ms后检测对齐才跳、不齐继续点动,goto/coast共用)'),
 (u'LADDER_REALIGN_MAX_ROUNDS = 3     # 直跳尝试上限(用户2026-09-19):每"进一次校准并起跳没抓住"算1次,满3次回主线(旧精修轮次语义废弃)',
  u'LADDER_REALIGN_MAX_ROUNDS = 2     # 直跳尝试上限(用户2026-09-26改2次):2次没抓住就回主线,直接开锁怪、不压制'),
 (u'        self._release_all_keys()\n        self._climb_fail_pause_until = int(time.time() * 1000) + LADDER_FAIL_REENTER_MS  # 补压制窗(用户2026-09-26):别立刻又上梯,先让B锁同层怪\n        _debug_log("[跨层] 爬梯失败，丢弃目标回正常找怪（先锁下面Y相近的，清完再重新上）")',
  u'        self._release_all_keys()\n        _debug_log("[跨层] 爬梯失败，丢弃目标回正常找怪（直接开锁怪、不压制）")'),
]
for i, (old, new) in enumerate(edits, 1):
    c = content.count(old)
    if c != 1:
        print("[FAIL] edit%d count=%d -> abort" % (i, c)); sys.exit(1)
    content = content.replace(old, new, 1)
with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("DONE: %d edits" % len(edits))
