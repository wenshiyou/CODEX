# -*- coding: utf-8 -*-
# 离线验证:田字双信号原地钉基点 _char_pos_hold_ok 真值表 + _flow_idle_match 图像判定
import threading
import numpy as np
import maple_route_ui as M

Cls = M.MinimapRouteRecorder
fails = []
def ck(name, got, exp):
    ok = (got == exp)
    print(("PASS " if ok else "FAIL ") + name + " got=%s exp=%s" % (got, exp))
    if not ok:
        fails.append(name)

def mk(now, pos, last_real_age, intents, fs):
    s = Cls.__new__(Cls)
    s._player_screen_pos = pos
    s._char_last_real_t = now - last_real_age
    s._mv_intent = intents
    s._wd_lock = threading.RLock()
    s._flow_lock = threading.RLock()
    s._flow_state = fs
    return s

NOW = 100000
STILL_FRESH = dict(still=True, t=NOW - 100)
def intent(held_ms, axis='x'):
    return {axis: {'dir': 1, 'start_t': NOW - held_ms}}

# 1 无旧点
ck("1 无旧点->不钉", Cls._char_pos_hold_ok(mk(NOW, None, 0, {}, STILL_FRESH), NOW), False)
# 2 超时(2000ms前最后真实坐标)
ck("2 超1500ms->不钉", Cls._char_pos_hold_ok(mk(NOW, (100, 100), 2000, {}, STILL_FRESH), NOW), False)
# 3 有效移动键(按1000ms)
ck("3 有效移动键->不钉", Cls._char_pos_hold_ok(mk(NOW, (100, 100), 100, intent(1000), STILL_FRESH), NOW), False)
# 4 轻点60ms转身 + 静止 + 新鲜 + 未超时 -> 钉
ck("4 轻点60ms+静止->钉", Cls._char_pos_hold_ok(mk(NOW, (100, 100), 100, intent(60), STILL_FRESH), NOW), True)
# 5 无键但田字测到背景动 still=False
ck("5 背景在动->不钉", Cls._char_pos_hold_ok(mk(NOW, (100, 100), 100, {}, dict(still=False, t=NOW-100)), NOW), False)
# 6 无键但 still=None(样本不足/未定)
ck("6 still未定->不钉", Cls._char_pos_hold_ok(mk(NOW, (100, 100), 100, {}, dict(still=None, t=NOW-100)), NOW), False)
# 7 静止但田字状态过期600ms
ck("7 田字过期->不钉", Cls._char_pos_hold_ok(mk(NOW, (100, 100), 100, {}, dict(still=True, t=NOW-600)), NOW), False)
# 8 无田字状态
ck("8 无flow状态->不钉", Cls._char_pos_hold_ok(mk(NOW, (100, 100), 100, {}, {}), NOW), False)
# 9 无键+静止+新鲜+未超时 -> 钉
ck("9 标准原地->钉", Cls._char_pos_hold_ok(mk(NOW, (100, 100), 100, {}, STILL_FRESH), NOW), True)
# 10 双轴:x轻点 y有效长按
ck("10 任一轴有效移动->不钉",
   Cls._char_pos_hold_ok(mk(NOW, (100, 100), 100, {'x': {'dir':1,'start_t':NOW-60}, 'y': {'dir':1,'start_t':NOW-1000}}, STILL_FRESH), NOW), False)
# 11 临界:恰好100ms按住=有效移动
ck("11 按住恰好100ms->不钉", Cls._char_pos_hold_ok(mk(NOW, (100, 100), 100, intent(100), STILL_FRESH), NOW), False)
# 12 临界:按住99ms=轻点
ck("12 按住99ms->钉", Cls._char_pos_hold_ok(mk(NOW, (100, 100), 100, intent(99), STILL_FRESH), NOW), True)

# ---- _flow_idle_match 合成图 ----
rng = np.random.RandomState(0)
tex = (rng.rand(160, 160) * 255).astype(np.float32)
# 叠一些大块纹理提升结构化程度
for i in range(0, 160, 16):
    tex[i:i+8, :] += 40
    tex[:, i:i+8] -= 20
tex = np.clip(tex, 0, 255).astype(np.float32)

m0 = Cls._flow_idle_match(Cls.__new__(Cls), tex, tex.copy())
print("\n[同图] moved=%s dx=%.2f dy=%.2f resp=%.2f mscore=%.2f std=%.1f trusted=%s" % (m0[0], m0[1], m0[2], m0[3], m0[6], m0[7], m0[8]))
ck("13 同帧->无位移", m0[0], False)
ck("14 纹理图->可信", m0[8], True)

shift = np.roll(tex, 3, axis=1).astype(np.float32)  # 水平平移3px
m1 = Cls._flow_idle_match(Cls.__new__(Cls), tex, shift)
print("[平移3px] moved=%s dx=%.2f dy=%.2f resp=%.2f mx=%.2f my=%.2f mscore=%.2f trusted=%s" % (m1[0], m1[1], m1[2], m1[3], m1[4], m1[5], m1[6], m1[8]))
ck("15 背景平移3px->moved", m1[0], True)

flat = np.full((160, 160), 128.0, dtype=np.float32)
m2 = Cls._flow_idle_match(Cls.__new__(Cls), flat, flat.copy())
print("[纯色] moved=%s std=%.2f trusted=%s" % (m2[0], m2[7], m2[8]))
ck("16 纯色低纹理->不可信", m2[8], False)

print("\n==== %s: %d/%d 通过 ====" % ("全部通过" if not fails else "有失败", 16-len(fails), 16))
raise SystemExit(1 if fails else 0)
