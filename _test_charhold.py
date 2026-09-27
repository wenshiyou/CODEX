# -*- coding: utf-8 -*-
# 离线验证 _apply_char_detection 三分支（真实模块未绑定方法 + 假self），不弹窗不连游戏
import io, sys, threading, types
sys.path.insert(0, r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2")
import maple_route_ui as M

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
src = io.open(P, encoding="utf-8-sig").read()

# ---- 静态断言：新逻辑唯一、旧逻辑物理删除、常量正确 ----
static = [
    ("新方法唯一定义", src.count("def _apply_char_detection") == 1),
    ("旧 _char_pos_hold_ok 方法已删", "def _char_pos_hold_ok" not in src),
    ("旧 _char_pos_hold_ok 调用已删", "self._char_pos_hold_ok(" not in src),
    ("识别线程不再产生 hold 源", "self._role_pos_src = 'hold'" not in src),
    ("攻击窗=500", "ATTACT_STANCE_MS = 500" in src and "ATTACT_STANCE_MS = 700" not in src),
]
assert M.ATTACT_STANCE_MS == 500, M.ATTACT_STANCE_MS
assert M.CHAR_HOLD_MAX_MS == 1500, M.CHAR_HOLD_MAX_MS
assert M.CHAR_STANCE_JUMP_PX == 50, M.CHAR_STANCE_JUMP_PX

Cls = M.MinimapRouteRecorder
NOW = 100000

def fake_self():
    s = types.SimpleNamespace()
    s._wd_lock = threading.Lock()
    s._mv_intent = {}
    s._climb_state = 'none'
    s._slope_air_until = 0
    s._wd_jump_gate_until = 0
    s._attack_last = {}
    s._player_screen_pos = None
    s._player_screen_t = 0
    s._raw_char_t = NOW
    s._char_last_real_t = 0
    s._role_pos_src = 'none'
    s._rlog_throttle = lambda *a, **k: None
    for _m in ('_char_stance_locked', '_char_anchor_trustable', '_apply_char_detection'):
        setattr(s, _m, types.MethodType(getattr(Cls, _m), s))
    return s

def run(rawp, psrc, atk_ago=None, last_real_ago=None, pos=(500, 500), atk_key="atk1"):
    s = fake_self()
    s._player_screen_pos = pos
    s._role_pos_src = psrc
    if atk_ago is not None:
        s._attack_last = {atk_key: NOW - atk_ago}
    s._char_last_real_t = (NOW - last_real_ago) if last_real_ago is not None else 0
    r = s._apply_char_detection(rawp, NOW)
    return r, s

cases = []
r, s = run(None, 'none', atk_ago=None, last_real_ago=100)
cases.append(("a 非攻击丢点→立刻放空不钉", r == 'none' and s._player_screen_pos is None))

r, s = run((505, 500), 'name', atk_ago=100, last_real_ago=40)
cases.append(("b 攻击中人名稳(偏移5)→采信并刷新真实时间",
              r == 'name' and s._player_screen_pos == (505, 500) and s._char_last_real_t == NOW))

r, s = run(None, 'none', atk_ago=100, last_real_ago=500)
cases.append(("c 攻击中丢人名500ms→钉原地且不刷新真实时间",
              r == 'hold' and s._player_screen_pos == (500, 500) and s._char_last_real_t == NOW - 500))

r, s = run((505, 500), 'face_r', atk_ago=100, last_real_ago=300)
cases.append(("d 攻击中只给脸点→不顶替仍钉原地", r == 'hold' and s._player_screen_pos == (500, 500)))

r, s = run(None, 'none', atk_ago=100, last_real_ago=2000)
cases.append(("e 攻击钉点超1.5s→释放放空", r == 'none' and s._player_screen_pos is None))

r, s = run((560, 500), 'name', atk_ago=None, last_real_ago=100)
cases.append(("f 非攻击人名跳变60→实时跟(非站桩不门控)", r == 'name' and s._player_screen_pos == (560, 500)))

r, s = run((700, 500), 'name', atk_ago=100, last_real_ago=40)
cases.append(("g 攻击中人名一帧跳200→特效误匹配被拦、钉原地", r == 'hold' and s._player_screen_pos == (500, 500)))

r, s = run(None, 'none', atk_ago=100, last_real_ago=0, pos=None)
cases.append(("h 冷启动无旧点攻击中丢→放空不崩", r == 'none' and s._player_screen_pos is None))

r, s = run(None, 'none', atk_ago=100, last_real_ago=500, atk_key="aoe")
cases.append(("i 群攻aoe键出手→同样算攻击中钉点", r == 'hold' and s._player_screen_pos == (500, 500)))

r, s = run(None, 'none', atk_ago=600, last_real_ago=600)
cases.append(("j 出手600ms已超500攻击窗→解除钉点放空", r == 'none' and s._player_screen_pos is None))

print("== 静态 ==")
for n, ok in static:
    print(("PASS" if ok else "FAIL"), n)
print("== 场景 ==")
for n, ok in cases:
    print(("PASS" if ok else "FAIL"), n)
print("STATIC_ALL", all(ok for _, ok in static))
print("CASE_ALL", all(ok for _, ok in cases))
