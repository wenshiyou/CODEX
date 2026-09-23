# -*- coding: utf-8 -*-
import io, datetime, os
d = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"
ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
msg = (f"{ts} 锁梯锁后全程复核梯底Y:锁后每帧校验|梯底-光点Y|<=14且梯身上通,连续2帧不合格即解锁用最新光点重过X+Y门选梯(治锁后只看X、人漂到梯身/梯顶仍按X对位原地空跳/选错梯);单帧抖动不误解,选不到走1.5s超时回主线;选梯X+Y门/跑跳/直跳离线5断言+AST遮蔽扫描全过,待真机")
io.open(os.path.join(d, "_commit_msg.txt"), "w", encoding="utf-8").write(msg)
print(msg)
