# -*- coding: utf-8 -*-
import io,sys,json,os
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
base=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"
cfg=os.path.join(base,"data","route_config.json")
print("=== route_config ===")
try:
    print(io.open(cfg,encoding='utf-8-sig').read().strip())
except Exception as e: print("读配置失败",e)
P=os.path.join(base,"debug.log")
lines=io.open(P,encoding='utf-8',errors='ignore').read().splitlines()
# 最近状态: 文件触发/锁怪开关/打怪决策/MP/运行 相关, 最后60行非田字
import re
keep=[]
for l in lines[-400:]:
    if '[田字诊断]' in l: continue
    keep.append(l)
print("\n=== 最近非田字日志(末40) ===")
for l in keep[-40:]: print(l[:160])
