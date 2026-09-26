# -*- coding: utf-8 -*-
import io, re, time
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines = io.open(P, encoding='utf-8', errors='ignore').read().splitlines()
SKIP = ('光点锁定', '光点测速', '光门模糊', 'HP', 'MP', '绘制', 'FPS', '蓝框', '黑框', '绿框偏移')
KEY = ('瞬移', '平台', '台端', '台界', '越线', '回退', 'manual_tp', 'edge', '锁', '空打', '空', '攻击', '主攻', '群攻',
       '决策', '方向', '血条', '伤害', '巡游', 'roam', 'B决策', '怪', '到边', '硬闸', '拉回', '边缘')
# 只看最近的行(尾部),并按时间窗
tail = lines[-4000:]
out = []
for l in tail:
    if any(s in l for s in SKIP):
        continue
    if any(k in l for k in KEY):
        out.append(l)
for l in out[-160:]:
    print(l[-240:])
