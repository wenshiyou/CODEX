# -*- coding: utf-8 -*-
import io,sys,time
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
time.sleep(24)
P=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines=io.open(P,encoding='utf-8',errors='ignore').read().splitlines()
keys=('[文件触发]','[台界带核对]','[打怪决策]','[空怪诊断]','[锁怪开关]','[平台边界]','[平台复核]','[巡游]','Traceback')
hit=[l for l in lines if any(k in l for k in keys)]
print("=== 启动后关键行(末40) ===")
for l in hit[-40:]: print(l[:175])
# 怪物特征点是否仍0(抽样最近蒙板同步)
mb=[l for l in lines[-120:] if '[蒙板同步]' in l]
print("\n=== 最近蒙板同步(末5) ===")
for l in mb[-5:]: print(l[:120])
print("\n最后一行:",lines[-1][:120])
