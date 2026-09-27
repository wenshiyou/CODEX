# -*- coding: utf-8 -*-
# 离线单测:同层范围外"方向滞回 + 脱检宽限 + 重选方向锚点"(治锁怪全屏横跳)。纯函数 select_combat_target。
import sys
sys.path.insert(0, r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2')
from combat_logic import select_combat_target as sel

SKILL = 250      # atk1_distance
STOP = 200       # cast_range = 4/5
YUP, YDN = 100, 25

def mk(cx, cy, w=40, h=40, s=0.9):
    return (cx - w // 2, cy - h, cx + w // 2, cy, s)

def run(px, py, monsters, tx, ty, alive=False, grace=10**9, tier=None, anchor=None):
    return sel(px, py, monsters, [], SKILL, 500,
               tx, ty, alive, None, None, 1, False, None,
               YUP, YDN, True, 0, 0, False, tier,
               group_priority=False, group_radius=0,
               combat_mode='random', lock_grace_ms=grace, side_anchor_x=anchor)

fails = 0
def check(name, d, want_state, want_x):
    global fails
    tx = d['target'][0] if d['target'] else None
    ok = (d['state'] == want_state) and (tx == want_x)
    print(('PASS' if ok else 'FAIL'), name, '-> state=%s target=%s tier=%s (want %s x=%s)' % (
        d['state'], d['target'], d.get('tier'), want_state, want_x))
    if not ok:
        fails += 1

# 同侧延续怪放900(离旧锁800=100>容差40,确保旧锁"脱检";X差400范围外);反方向怪150
check('case1 脱检同侧滞回不横穿', run(500,500,[mk(150,503), mk(900,510)],800,505), 'pursue', 900)
check('case2 同侧空则换边',       run(500,500,[mk(150,503)],800,505), 'pursue', 150)
check('case3 近身怪优先cast',     run(500,500,[mk(515,495), mk(150,503)],800,505), 'cast', 515)
check('case4 近身脱检原位补打',   run(500,500,[mk(150,503)],560,495), 'cast', 560)
check('case5 在表维持旧锁',       run(500,500,[mk(800,505), mk(150,503)],800,505), 'pursue', 800)
check('case6 宽限内沿用旧锁不横穿', run(500,500,[mk(150,503), mk(900,510)],800,505,grace=100), 'pursue', 800)
check('case7 超宽限走同侧延续',   run(500,500,[mk(150,503), mk(900,510)],800,505,grace=600), 'pursue', 900)
check('case8 超宽限同侧空换边',   run(500,500,[mk(150,503)],800,505,grace=600), 'pursue', 150)
check('case9 宽限内近身仍优先',   run(500,500,[mk(515,495), mk(150,503)],800,505,grace=100), 'cast', 515)

# cross锁不粘坐标宽限,但重选仍受方向锚点约束:旧cross在右(800,上层),同侧上层900 vs 反侧150
d10 = run(500,500,[mk(150,331), mk(900,309)],800,309,grace=100,tier='cross')
tx10 = d10['target'][0] if d10['target'] else None
ok10 = tx10 == 900
print(('PASS' if ok10 else 'FAIL'), 'case10 cross漏检同侧不横穿 -> target=%s (want 900)' % (d10['target'],))
if not ok10: fails += 1

# drop当帧 target=None、combat_step 传上一锁坐标做锚:近身空,反方向怪Y差更小也不横穿,选同侧900
check('case11 drop重选同侧不横穿', run(500,500,[mk(150,503), mk(900,510)],None,None,anchor=858), 'pursue', 900)
# drop重选但近身(哪怕反方向)有怪:近身cast无条件接管,锚点不拦
check('case12 drop近身怪优先cast', run(500,500,[mk(450,495), mk(900,510)],None,None,anchor=858), 'cast', 450)
# 无锁无锚(开局):全局按(|Y|,X)正常选,不被方向约束
check('case13 开局无锚全局选最近', run(500,500,[mk(150,503), mk(900,510)],None,None), 'pursue', 150)
# drop(target None)+锚在右+宽限内(grace63)+右侧当帧空(漏检)、只有左侧怪:不横穿,idle站住等恢复
d14 = run(500,500,[mk(150,503)],None,None,grace=63,anchor=900)
ok14 = d14['state'] == 'idle' and d14['target'] is None
print(('PASS' if ok14 else 'FAIL'), 'case14 宽限内同侧空不横穿->idle -> state=%s target=%s (want idle None)' % (
    d14['state'], d14['target']))
if not ok14: fails += 1
# 同上但持续超宽限(grace600,右侧真空):允许换向选左150,不呆住
check('case15 超宽限同侧真空才换向', run(500,500,[mk(150,503)],None,None,grace=600,anchor=900), 'pursue', 150)
# 有target脱检、宽限内、同侧空异侧有怪:宽限sticky只对同层out沿用旧坐标(本例target900右、X差400范围外)->沿用900
check('case16 有锁宽限内沿用旧锁', run(500,500,[mk(150,503)],900,510,grace=63), 'pursue', 900)

print('HYST fails =', fails)
sys.exit(1 if fails else 0)
