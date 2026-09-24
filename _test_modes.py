# -*- coding: utf-8 -*-
"""
两套锁怪规则 + 删除 cross 续命 + 脱检补打门槛 —— 专项离线回归（真实 select_combat_target + 合成数据）。
规则（用户2026-09-24定稿）:
  random 随机=全图自由打,近的先打,双向可跨层(行为与改前一致);
  single 手动单台=只锁屏幕|Y差|<50同台怪,不跨层不上梯不产跳高;
  multi  手动多台=同层正常打,跨层只放行"还有更高/更低选中台"的方向(allow_cross_up/down),原地跳高不受方向限制;
  就近优先(Y近再X近)永远主规则;
  锁定怪脱检/锁背景:当帧怪表非空且旧坐标在同层技能位→照原位补打一下(没血没伤下一拍drop重锁);怪表全空→待机,绝不续旧cross坐标。
跑法: python _test_modes.py
"""
import combat_logic as cl

PX, PY, SKILL, FAR = 500, 300, 150, 500
P = F_ = 0


def mon(cx, cy, w=30, h=40):
    return (cx - w // 2, cy - h, cx + w // 2, cy, 0.9)


def sel(monsters, mode='random', lock=None, alive=False, tier=None, cur=None,
        yup=100, ydn=100, slope=None, allow=True, cup=True, cdn=True,
        px=PX, py=PY):
    return cl.select_combat_target(
        px, py, monsters, [], SKILL, FAR,
        lock[0] if lock else None, lock[1] if lock else None, alive,
        (lambda cx, cy: True), (lambda cx, cy: None),
        1, False, cur, yup, ydn, allow, 1000, 0, False, tier,
        False, 0, None, None, False, None, None, slope,
        combat_mode=mode, allow_cross_up=cup, allow_cross_down=cdn)


def chk(name, cond, got, want):
    global P, F_
    if cond:
        P += 1; print('[PASS]', name)
    else:
        F_ += 1; print('[FAIL]', name, '-> got=', got, ' want=', want)


def st(name, d, estate, etarget=None):
    t = d['target']
    ok = d['state'] == estate
    if etarget is None:
        ok = ok and t is None
    else:
        ok = ok and t is not None and abs(t[0] - etarget[0]) <= 5 and abs(t[1] - etarget[1]) <= 5
    chk(name, ok, (d['state'], t), (estate, etarget))


print('==== A. random 随机模式回归(行为与改前一致) ====')
st('A1 左右各怪=锁最近', sel([mon(400, 300), mon(580, 300)]), 'cast', (580, 300))
st('A2 同层X差400>=300=先走近pursue', sel([mon(900, 300)]), 'pursue', (900, 300))
st('A3 上层超攻击带=cross', sel([mon(600, 100)]), 'cross', (600, 100))
st('A4 无怪=idle', sel([]), 'idle', None)
_d = sel([mon(400, 100), mon(600, 100)], lock=(600, 100), tier='cross', cur=(600, 100))
st('A5 已锁cross仍在候选=维持不摇摆', _d, 'cross', (600, 100))

print('==== B. 删除 cross 续命(钉死呆住根因) ====')
# 事故复现:人(585,523) 锁着已不在怪表的cross(293,522),身边刷同层怪
_b1 = sel([mon(617, 500)], lock=(293, 522), tier='cross', alive=False, px=585, py=523)
st('B1 旧cross脱检+身边同层怪=立刻接管身边怪(不钉旧cross)', _b1, 'cast', (617, 500))
_b2 = sel([mon(400, 300)], lock=(293, 522), tier='cross', alive=False, px=585, py=523)
st('B2 旧cross脱检+只剩别的上层怪=重选新cross(不续旧坐标)', _b2, 'cross', (400, 300))
_b3 = sel([], lock=(293, 522), tier='cross', alive=False, px=585, py=523)
st('B3 旧cross脱检+怪表空=idle(绝不续旧坐标)', _b3, 'idle', None)

print('==== C. 脱检补打一下 + 怪表空门槛 ====')
_c1 = sel([mon(700, 300)], lock=(560, 300), tier='in', alive=False)
st('C1 怪表非空+旧锁在技能位脱检=原位补打一下cast', _c1, 'cast', (560, 300))
_c2 = sel([], lock=(560, 300), tier='in', alive=False)
st('C2 怪表全空+旧锁脱检=不凭空打,idle', _c2, 'idle', None)
_c3 = sel([], lock=(600, 300), tier='in', alive=True)
st('C3 锁定怪活着漏帧=续锁不误丢', _c3, 'cast', (600, 300))

print('==== D. single 手动单台(只锁|Y差|<50同台,不跨层不跳高) ====')
st('D1 同台近怪=cast', sel([mon(530, 280)], mode='single'), 'cast', (530, 280))
st('D2 只有上层怪=丢弃idle(不上梯)', sel([mon(550, 100)], mode='single'), 'idle', None)
st('D3 跳高带怪也不产slope', sel([mon(550, 170)], mode='single', slope=150), 'idle', None)
st('D4 同台远处X350 Y20=走近pursue', sel([mon(850, 280)], mode='single'), 'pursue', (850, 280))
st('D5 远处别台X350 Y120=丢弃idle', sel([mon(850, 180)], mode='single'), 'idle', None)
st('D6 同台怪+上层怪并存=只锁同台', sel([mon(530, 280), mon(550, 100)], mode='single'), 'cast', (530, 280))

print('==== E. multi 手动多台(按选中台方向放行跨层,跳高不受限) ====')
st('E1 顶层无更高台=上层cross不放行idle',
   sel([mon(550, 100)], mode='multi', slope=150, cup=False, cdn=True), 'idle', None)
st('E2 顶层下层怪=放行向下cross',
   sel([mon(550, 500)], mode='multi', slope=150, cup=False, cdn=True), 'cross', (550, 500))
st('E3 跳高带怪=slope原地跳高(不受向上跨层关闭影响)',
   sel([mon(550, 170)], mode='multi', slope=150, cup=False, cdn=True), 'slope', (550, 170))
st('E4 中层有更高台=上层cross放行',
   sel([mon(550, 100)], mode='multi', slope=150, cup=True, cdn=True), 'cross', (550, 100))

print('==== F. random 对照(上层怪正常cross,不受single限制) ====')
st('F1 random上层怪=cross(对照D2)', sel([mon(550, 100)], mode='random'), 'cross', (550, 100))

print('\n==== 结果: PASS=%d FAIL=%d ====' % (P, F_))
import sys
sys.exit(1 if F_ else 0)
