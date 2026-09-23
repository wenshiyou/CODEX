# -*- coding: utf-8 -*-
import io, os, re, time
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
st = os.stat(P)
print("debug.log mtime=%s size=%d" % (time.strftime('%H:%M:%S', time.localtime(st.st_mtime)), st.st_size))
lines = io.open(P, 'rb').read().decode('utf-8', 'replace').replace('\r\n','\n').split('\n')
# 找最后一个启动锚点
anchors = [i for i,l in enumerate(lines) if re.search(r'(\[初始化\]|单实例|启动|线程.*start|开始运行|mainloop|Tk\)|====)', l)]
start = anchors[-1]-3 if anchors else max(0,len(lines)-200)
tail = lines[start:]
print("==== 最后启动段(锚点行%d起, 共%d行) ====" % (start+1, len(tail)))
kw = re.compile(r'(Traceback|Error|Exception|错误|异常|截图耗时|周期|帧率|忙|闲|精|线程|光点|跳变|角色跟踪|忙帧|初始化|启动|FPS|fps)', re.I)
shown=0
for l in tail:
    if kw.search(l):
        print(l[:200]); shown+=1
print("---- 该段原始最后25行 ----")
for l in [x for x in tail if x.strip()][-25:]:
    print(l[:200])
