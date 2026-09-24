# -*- coding: utf-8 -*-
# 离线验证:站桩纯距离门钉基点 _char_stance_locked/_char_anchor_trustable/_char_pos_hold_ok 真值表
#         + 保留的 _flow_idle_match 田字图像判定(田字即将搬小地图,函数本体未删,回归其不被破坏)
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

NOW = 100000
ATK_RECENT = {'atk1': NOW - 500}                          # 500ms前放过主攻=站桩输出中(< ATTACT_STANCE_MS=700)
ATK_OLD = {'atk1': NOW - (M.ATTACT_STANCE_MS + 500)}      # 早于攻击窗(>700ms,已停手走位)=非站桩
def intent(held_ms, axis='x'):
    return {axis: {'dir': 1, 'start_t': NOW - held_ms}}

def mk(pos=(100, 100), age=100, intents=None, atk=None, climb='none', air=0, gate=0):
    s = Cls.__new__(Cls)
    s._player_screen_pos = pos
    s._char_last_real_t = NOW - age
    s._mv_intent = intents if intents is not None else {}
    s._wd_lock = threading.RLock()
    s._attack_last = atk if atk is not None else dict(ATK_RECENT)
    s._climb_state = climb          # none/to_ladder/climbing/jump_down/jump_up/teleport/descend
    s._slope_air_until = air        # 跳高打腾空窗截止(ms);>NOW=空中
    s._wd_jump_gate_until = gate    # 通用跳后静默窗截止(ms);>NOW=刚起跳
    return s

# ---- _char_stance_locked 站桩态 ----
ck("S1 无移动键+近期攻击=站桩", Cls._char_stance_locked(mk(), NOW), True)
ck("S2 有效移动键(按1000ms)=非站桩", Cls._char_stance_locked(mk(intents=intent(1000)), NOW), False)
ck("S3 轻点60ms掰脸=仍站桩", Cls._char_stance_locked(mk(intents=intent(60)), NOW), True)
ck("S4 按住恰好100ms=非站桩", Cls._char_stance_locked(mk(intents=intent(M.MOVE_KEY_MIN_MS)), NOW), False)
ck("S5 按住99ms=仍站桩", Cls._char_stance_locked(mk(intents=intent(M.MOVE_KEY_MIN_MS - 1)), NOW), True)
ck("S6 双轴x轻点/y长按=非站桩",
   Cls._char_stance_locked(mk(intents={'x': {'dir': 1, 'start_t': NOW - 60},
                                       'y': {'dir': 1, 'start_t': NOW - 1000}}), NOW), False)
ck("S7 从没攻击过=非站桩", Cls._char_stance_locked(mk(atk={}), NOW), False)
ck("S8 攻击超过心跳窗=非站桩", Cls._char_stance_locked(mk(atk=ATK_OLD), NOW), False)
ck("S9 攻击在攻击窗边界内(差%dms)=站桩" % (M.ATTACT_STANCE_MS - 1),
   Cls._char_stance_locked(mk(atk={'atk1': NOW - (M.ATTACT_STANCE_MS - 1)}), NOW), True)
ck("S10 攻击刚出攻击窗(差%dms)=非站桩" % (M.ATTACT_STANCE_MS + 1),
   Cls._char_stance_locked(mk(atk={'atk1': NOW - (M.ATTACT_STANCE_MS + 1)}), NOW), False)
# ---- 起跳/爬梯/瞬移/腾空:即使刚攻击也绝不钉原点(用户2026-09-24:没起跳才钉) ----
ck("J1 刚攻击但爬梯中(climbing)->不钉", Cls._char_stance_locked(mk(climb='climbing'), NOW), False)
ck("J2 刚攻击但跳高打腾空在途->不钉", Cls._char_stance_locked(mk(air=NOW + 100), NOW), False)
ck("J3 刚攻击但通用跳后静默在途->不钉", Cls._char_stance_locked(mk(gate=NOW + 100), NOW), False)
ck("J4 刚攻击+已落地(在地上/腾空窗过)->站桩", Cls._char_stance_locked(mk(air=NOW - 1, gate=NOW - 1), NOW), True)

# ---- _char_pos_hold_ok 钉住(点丢失/错点时) ----
ck("H1 无上一可信点->不钉", Cls._char_pos_hold_ok(mk(pos=None), NOW), False)
ck("H2 超CHAR_HOLD_MAX_MS->不钉", Cls._char_pos_hold_ok(mk(age=M.CHAR_HOLD_MAX_MS + 1), NOW), False)
ck("H3 站桩+未超时+有点->钉", Cls._char_pos_hold_ok(mk(), NOW), True)
ck("H4 站桩但有效移动键->不钉", Cls._char_pos_hold_ok(mk(intents=intent(1000)), NOW), False)
ck("H5 站桩但久未攻击->不钉", Cls._char_pos_hold_ok(mk(atk=ATK_OLD), NOW), False)
ck("H6 轻点60ms站桩->钉", Cls._char_pos_hold_ok(mk(intents=intent(60)), NOW), True)

# ---- _char_anchor_trustable 采信门(站桩只接受小渐变) ----
ck("T1 非站桩(移动键)大跳变->仍采信(实时跟随)",
   Cls._char_anchor_trustable(mk(intents=intent(1000)), (400, 400), NOW), True)
ck("T2 非站桩(无攻击)大跳变->仍采信",
   Cls._char_anchor_trustable(mk(atk={}), (400, 400), NOW), True)
ck("T3 站桩小渐变20px->采信", Cls._char_anchor_trustable(mk(), (120, 100), NOW), True)
ck("T4 站桩恰好%dpx边界->采信" % M.CHAR_STANCE_JUMP_PX,
   Cls._char_anchor_trustable(mk(), (100 + M.CHAR_STANCE_JUMP_PX, 100), NOW), True)
ck("T5 站桩超%dpx大跳变->丢弃" % M.CHAR_STANCE_JUMP_PX,
   Cls._char_anchor_trustable(mk(), (100 + M.CHAR_STANCE_JUMP_PX + 1, 100), NOW), False)
ck("T6 站桩实测特效跳变(486,552)->(247,638)约254px->丢弃",
   Cls._char_anchor_trustable(mk(pos=(486, 552)), (247, 638), NOW), False)
ck("T7 冷启动无上一可信点->直接采信",
   Cls._char_anchor_trustable(mk(pos=None), (999, 999), NOW), True)

# ---- _flow_idle_match 田字图像判定(函数本体保留,回归不被破坏) ----
rng = np.random.RandomState(0)
tex = (rng.rand(160, 160) * 255).astype(np.float32)
for i in range(0, 160, 16):
    tex[i:i + 8, :] += 40
    tex[:, i:i + 8] -= 20
tex = np.clip(tex, 0, 255).astype(np.float32)
m0 = Cls._flow_idle_match(Cls.__new__(Cls), tex, tex.copy())
ck("F1 同帧->无位移", m0[0], False)
ck("F2 纹理图->可信", m0[8], True)
shift = np.roll(tex, 3, axis=1).astype(np.float32)
m1 = Cls._flow_idle_match(Cls.__new__(Cls), tex, shift)
ck("F3 背景平移3px->moved", m1[0], True)
flat = np.full((160, 160), 128.0, dtype=np.float32)
m2 = Cls._flow_idle_match(Cls.__new__(Cls), flat, flat.copy())
ck("F4 纯色低纹理->不可信", m2[8], False)

# ---- _char_disp_plausible 统一位移速度门(方案A:主匹配/全图/黑框重捕三通道共用) ----
def gate(last, bx, by, dt_ms=33, persistent=False, reloc=False):
    _tr = {'last_t': NOW - dt_ms}
    if persistent:
        _tr['_full_persistent'] = True
    return Cls._char_disp_plausible(Cls.__new__(Cls), last, bx, by, NOW, _tr, relocate_win=reloc)[0]
ck("G1 无上一可信点(冷启动)->放行", gate(None, 900, 900), True)
ck("G2 33fps小步30px(限60)->采信", gate((100, 100), 130, 100), True)
ck("G3 33fps飞点200px(限60)->拒采", gate((100, 100), 300, 100), False)
ck("G4 瞬移重定位窗内800px大跳变->放行", gate((100, 100), 900, 100, reloc=True), True)
ck("G5 局部连续1秒找不到(真丢/过图)->放行重定位", gate((100, 100), 900, 100, persistent=True), True)
ck("G6a 低帧500ms(限150)位移160px->拒采", gate((100, 100), 100, 260, dt_ms=500), False)
ck("G6b 低帧500ms(限150)位移140px->采信", gate((100, 100), 100, 240, dt_ms=500), True)
ck("G7a 高帧16ms(限60)位移80px->拒采", gate((100, 100), 180, 100, dt_ms=16), False)
ck("G7b 高帧16ms(限60)位移50px->采信", gate((100, 100), 150, 100, dt_ms=16), True)
ck("G8 dt<=0同帧重入归一30fps->原位采信", gate((100, 100), 100, 100, dt_ms=0), True)
ck("G9 真机事故复现(375,372)->(924,427)约551px黑框洗白->拒采", gate((375, 372), 924, 427), False)

total = 14 + 6 + 7 + 4 + 11   # S1-S10+J1-J4=14; H6; T7; F4; G1-G9共11断言
print("\n==== %s: %d/%d 通过 ====" % ("全部通过" if not fails else "有失败", total - len(fails), total))
raise SystemExit(1 if fails else 0)
