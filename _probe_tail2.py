# -*- coding: utf-8 -*-
import io
p=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines=io.open(p,'r',encoding='utf-8',errors='replace').read().splitlines()
print("总行数",len(lines))
# 找最后一个初始化/启动/F10/F12 标记位置
marks=[]
for i,l in enumerate(lines):
    if any(k in l for k in ['初始化','启动','F10','F12','Traceback','单实例','运行=']):
        marks.append(i)
start=marks[-1]-3 if marks else len(lines)-45
for l in lines[max(0,start):][:60]:
    print(l)
