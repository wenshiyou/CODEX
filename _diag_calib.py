# -*- coding: utf-8 -*-
# 解析 debug.log,定位录制窗口(录制C/梯录),并提取窗口内光点坐标与人物屏幕坐标,复现死区采集比例
import re, io

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
lines = io.open(P, encoding="utf-8", errors="replace").read().splitlines()

ts_re = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\]")
dot_re = re.compile(r"\[光点\] 中心=\(([-\d]+),([-\d]+)\)")
name_re = re.compile(r"name=\(([-\d]+),([-\d]+)\)")
state_re = re.compile(r"\[镜头检测诊断\].*?state=(\w+)")

# 1) 先定位录制相关行的时间戳
print("==== 录制相关行(定位窗口) ====")
for ln in lines:
    if ("[录制C]" in ln) or ("[梯录" in ln) or ("录制" in ln and "平台" in ln):
        m = ts_re.match(ln)
        if m:
            print(m.group(0), ln.split("] ", 1)[1][:80])

def in_win(ts, lo, hi):
    return lo <= ts <= hi

windows = [
    ("平台1(11:46:02-08)", "11:46:02", "11:46:09"),
    ("长梯Y(11:46:50-59)", "11:46:50", "11:46:59"),
    ("平台2(11:47:03-09)", "11:47:03", "11:47:10"),
]
for title, lo, hi in windows:
    print("\n==== %s 逐帧(光点/屏幕name/镜头state) ====" % title)
    for ln in lines:
        m = ts_re.match(ln)
        if not m or not in_win(m.group(0)[1:-1], lo, hi):
            continue
        dm = dot_re.search(ln); nm = name_re.search(ln); sm = state_re.search(ln)
        tag = None
        if dm: tag = "光点(%s,%s)" % dm.group(1, 2)
        if nm: tag = "屏幕name(%s,%s)" % nm.group(1, 2)
        if sm: tag = "镜头state=%s" % sm.group(1)
        if tag:
            print(m.group(0), tag)

