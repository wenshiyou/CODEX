# -*- coding: utf-8 -*-
import io,re
base=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"
KW=['锁怪开关','关闭锁怪','恢复锁怪','拟人','休息','到达新平台','到顶','下跳','descend','climbing','teleport','瞬移','重锁','决策包','cross_need','本层无够得着']
for fn in ['debug.log.bak','debug.log']:
    try:
        L=io.open(base+'\\'+fn,'r',encoding='utf-8',errors='replace').read().splitlines()
    except Exception as e:
        print(fn,'读取失败',e); continue
    print("\n========== %s  行数%d =========="%(fn,len(L)))
    print("首",L[0][:40] if L else '-', "| 末", L[-1][:40] if L else '-')
    hit=[l for l in L if any(k in l for k in KW)]
    # 只打印最后 60 条相关行
    for l in hit[-60:]:
        # 去掉每秒统计噪声行
        if '识别B耗时' in l or '截图耗时' in l or 'FPS' in l: continue
        print(l[:150])
