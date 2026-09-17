lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找POST_STRIKE_CHECK_MS = 0这一行
for i in range(len(lines)):
    if 'POST_STRIKE_CHECK_MS = 0' in lines[i]:
        print('找到位置:', i+1)
        # 改回450
        lines[i] = 'POST_STRIKE_CHECK_MS = 450 # 攻击后反馈检测窗口(用户2026-09-11:130→450)：首次出手满450ms后才看血条/伤害判"打死没/是不是空怪";怪多/特效/掉帧(实测帧率曾掉到1-3fps)时130ms拿不到出手后稳定帧、真怪被当空怪清掉→一圈怪轮流锁左右抖;另须拿到出手之后的新帧才判,避免用出手前旧帧误丢真怪\n'
        break

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('修改完成')
