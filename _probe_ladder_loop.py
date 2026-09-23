# -*- coding: utf-8 -*-
import io, re
p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines = io.open(p, "rb").read().decode("utf-8", "replace").splitlines()

def sec(ln):
    m = re.match(r"\[(\d{2}):(\d{2}):(\d{2})\]", ln)
    return int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)) if m else None

# 末尾时间
last_t = None
for ln in reversed(lines):
    t = sec(ln)
    if t is not None:
        last_t = t; break
cut = last_t - 180
win = [ln for ln in lines if (sec(ln) is not None and sec(ln) >= cut)]
print("末尾时间=%s 最后3分钟行数=%d" % (last_t, len(win)))

# 运行切换点(F10/F12/运行)
print("\n=== 运行切换(最后12条) ===")
run_sw = [ln for ln in win if re.search(r"F10|F12|开始运行|停止运行|运行=True|运行=False|启动|初始化", ln)]
for ln in run_sw[-12:]:
    print(ln)

# 关键词计数
kws = ["选梯","爬梯","Y不合格","没抓住","校准","realign","放弃","cross","跨层","上梯",
       "跑跳","直跳","锁定小地图梯","锁定梯","打怪决策","锁定怪","锁怪","跳高","后脑","抓梯"]
print("\n=== 关键词计数(最后3分钟) ===")
for k in kws:
    c = sum(ln.count(k) for ln in win)
    if c:
        print("%-12s %d" % (k, c))

# 关键事件行(梯/cross/锁怪/Y不合格/没抓住/放弃)
print("\n=== 梯/跨层/锁/Y复核 事件行(最多260条) ===")
ev = [ln for ln in win if re.search(r"选梯|爬梯|Y不合格|没抓住|校准|放弃|cross|跨层|上梯|跑跳|直跳|锁定|锁梯|后脑|抓梯|跳", ln)]
# 去掉纯绘制/MP噪声
ev = [ln for ln in ev if "底部横带匹配度" not in ln]
for ln in ev[-260:]:
    print(ln)
