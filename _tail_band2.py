# -*- coding: utf-8 -*-
import io,sys,re,datetime
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
P=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines=io.open(P,encoding='utf-8',errors='ignore').read().splitlines()
# 启动报错/Traceback 最近
tb=[l for l in lines[-400:] if ('Traceback' in l or 'Error' in l or 'Exception' in l or 'reach_left' in l or 'manual_x_band' in l)]
print("=== 最近400行内报错/关键字 ===")
for l in tb[-15:]: print(l[:160])
# 最近关键决策行(台界带/打怪决策/平台复核/空怪),最后90行命中
keys=('[台界带核对]','[打怪决策]','[平台复核]','[空怪诊断]','[锁怪开关]','[平台边界]')
hit=[l for l in lines if any(k in l for k in keys)]
print("\n=== 最后25条关键决策 ===")
for l in hit[-25:]: print(l[:170])
print("\n总行数",len(lines),"最后一行:",lines[-1][:120] if lines else "")
