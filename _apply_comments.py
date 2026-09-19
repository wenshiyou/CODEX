# -*- coding: utf-8 -*-
import io, sys
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(P, "r", encoding="utf-8-sig") as f:
    text = f.read()
R = []
R.append((
'''        # 人怪Y分层直接用"实时人物Y"(同2026-09-10及之前版本,用户确认那时一直正常)。
        # 2026-09-11曾改用"落地稳定基线_char_ground_y"(腾空时冻结),但人走上更高台阶/坡后脚Y永久抬高,
        # 被误判成起跳→基线冻结在旧低处、且要求Y回落才解锁,上台阶后永远解不开(实测实时脚528/基线卡620差92),
        # 导致几乎同高的怪被算成"上方99"一直误判跳高打。回退实时Y,与X用同一套坐标,简单不卡死。
        # 人怪Y分层用实时人物Y(用户2026-09-16:删除方案二Y变化率平滑,实测无效且污染地面Y)''',
'''        # 人怪Y分层用两态地面基线_layer_y(用户2026-09-19定稿,人物线程每帧维护):
        # 打怪态(最近1秒出过攻击键)=最近2秒人名中心Y最大值(屏幕最靠下=脚踩地面),跳起Y变小不污染分层、不误判怪在下方乱下跳;
        # 连续1秒没出手(走路/巡路/上下梯)=移动态,Y实时跟手;移动→打怪上升沿清窗重采,上高层不带旧层大Y。X永远实时不进窗。'''))
R.append((
'''        # 【巡路优先·一条线原则(用户2026-09-09)】流程严格按 识别→锁怪→巡路(走/跳/瞬移/上下梯)→打怪 串行循环：
        # 只要已进入攀爬动作(_climb_state!=none：抓梯/爬梯/上下跳/瞬移)，这一帧不管决策成cast/pursue还是cross，
        # 都先把巡路走完(到顶_reset_climb回none)，绝不在梯子上中途切去打怪，否则松↑/按跳会把人从梯上弄下来。
        # 【2026-09-09修复】独占只看_climb_state!=none,不再要求_combat_transit(旧条件在transit被取消分支清零后失效→爬梯中仍发攻击键)。
        # 跨层行进由_transit_step每帧唯一tick _climb_state_machine(持续按↑到顶)；非跨层爬梯(掉台归位/随机)由各自tick驱动,这里只松攻击、不碰移动键,return不抢动作。
        # 【不可打断态收窄·用户2026-09-11】只有"已抓梯在爬/已起跳/下落/瞬移中"才硬冻走完巡路(爬一半被近身怪
        # 拉下来会掉梯);to_ladder=平地走向/对齐梯子、还没抓上,不属于硬冻——放行到下面移动权裁决,
        # 让"近身技能范围内刷可直打怪→三步走解绑回主线先打"生效(原条件!=none把to_ladder也冻住=梯框合不上时干卡数秒的根因)。
        # (climbing/jump_up/jump_down/descend/teleport硬冻态已由帧首硬闸独占,此重复分支已删)

        # === 平地阶段移动权唯一裁决(用户2026-09-11:跨层怪=范围外怪,套范围外规则) ===
        # 锁定上层怪后锚点坐标固定保存;平地走向梯子/走台子(_climb_state=none,还没起跳,能走到这说明未硬冻)时:
        #  ·技能范围内刷出能直打的本层怪(决策state=cast)→严格三步走:解绑锚点→取消去梯子动作→松键回主线,下帧主线自然锁近身怪打;
        #  ·没有近身可直打怪(state=pursue/cross,都是范围外)→锚点不换不丢,一心_transit_step去上层;
        #  ·起跳抓梯后由上面 _climb_state!='none' 分支硬冻巡路优先,根本走不到这,近身怪也不打断。''',
'''        # === 跨层两档(用户2026-09-19主线合并,同一帧唯一司机) ===
        # 硬档(已起跳post_jump/校准realign/爬梯climbing/下跳descend):帧首唯一硬闸独占,本帧只_transit_step爬梯,
        #   打怪/走位/战斗瞬移/巡游全不碰(B识别不停、只清锁定不出包),根本走不到这里。
        # 软档(平地走向梯子to_ladder未起跳 / 选台平地走=transit且cs=none):B正常锁怪——
        #   仅state=cast(站定够得着的近身怪)物理松左右键、放行原地打(本帧不tick transit);其余(pursue/cross/switch/idle)一心_transit_step继续去梯/走台。
        #   近身怪打完、下帧B无cast,自然回到_transit_step接着走,不抢键、不左右拉扯。'''))
for i,(old,new) in enumerate(R,1):
    c=text.count(old)
    if c!=1:
        print("ANCHOR FAIL",i,c); sys.exit(1)
    text=text.replace(old,new,1)
assert "\r\n" not in text
with io.open(P,"wb") as f:
    f.write(b"\xef\xbb\xbf"+text.encode("utf-8"))
print("COMMENTS OK")
