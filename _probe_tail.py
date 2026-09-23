# -*- coding: utf-8 -*-
import io
P=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines=io.open(P,'r',encoding='utf-8',errors='replace').read().splitlines()
for l in lines[-30:]:
    print(l[:170])
