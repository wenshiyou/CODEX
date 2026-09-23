import io
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(p, 'r', encoding='utf-8-sig') as f:
    c = f.read()

# 1. 冷却改回15000
c = c.replace(
    'ROAM_COOLDOWN_MS = 2000  # 一次巡游结束(遇怪/走完)后冷却,2秒后无怪再巡游(用户2026-09-21)',
    'ROAM_COOLDOWN_MS = 15000  # 一次巡游从开始计时,15秒内不再巡游(用户2026-09-21)'
)

# 2. 开始巡游时设冷却
old2 = '''            self._roam_active = True
            _debug_log("[巡游] 同层无怪,朝%s侧找怪:光点%.0f→目标%.0f(远侧%.0f小地图px,走%.0f%%)" % ('''
new2 = '''            self._roam_active = True
            self._roam_cd_until = now_ms + ROAM_COOLDOWN_MS  # 从开始巡游时计时,15秒内不再巡游
            _debug_log("[巡游] 同层无怪,朝%s侧找怪:光点%.0f→目标%.0f(远侧%.0f小地图px,走%.0f%%)" % ('''
c = c.replace(old2, new2)

# 3. _end里不设冷却了
old3 = '''        if start_cooldown:
            self._roam_cd_until = time.time() * 1000 + ROAM_COOLDOWN_MS
            _debug_log("[巡游] 本次结束(遇怪即停/走完不补),冷却%.0fs" % (ROAM_COOLDOWN_MS / 1000.0))'''
new3 = '''        _debug_log("[巡游] 本次结束(遇怪即停/走完不补)")'''
c = c.replace(old3, new3)

with io.open(p, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(c)
print('OK')
