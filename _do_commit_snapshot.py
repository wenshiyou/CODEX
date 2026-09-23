# -*- coding: utf-8 -*-
import io,datetime,os
base=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"
now=datetime.datetime.now()
t="%d-%d-%d %d点%02d分"%(now.year,now.month,now.day,now.hour,now.minute)
msg=(t+" CPU忙档让路闭环+主循环帧率反馈+战斗面板降帧+draw分段诊断埋点 "
     "同层打怪正常+光点小地图巡路选梯框架正常+锁怪Y近X近正常+血条伤害数字判定正常 "
     "(已知待修:锁梯选梯门10与锁后复核门14不一致+录制0/2/3px废梯未滤+解锁无退出,致锁解永振呆住,下一版修复)")
mp=os.path.join(base,"_commit_msg.txt")
io.open(mp,'w',encoding='utf-8').write(msg)
print(msg)
