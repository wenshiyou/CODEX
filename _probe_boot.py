# -*- coding: utf-8 -*-
import io,time
P=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines=io.open(P,'r',encoding='utf-8',errors='replace').read().splitlines()
print("总行数",len(lines))
# 找最后一次启动标志(初始化/YOLO加载/冷启动)
tail=lines[-120:]
for l in tail:
    if any(k in l for k in ['[初始化]','[YOLO]','[冷启动]','Traceback','Error','异常','单实例','加载成功','忙档','性能档']):
        print(l[:160])
