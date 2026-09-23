# -*- coding: utf-8 -*-
# 一次性提交脚本(不提交git): 仅提交 maple_route_ui.py 选梯修复快照
import io, os, subprocess, datetime
repo = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"
t = datetime.datetime.now().strftime("%Y-%m-%d号 %H点%M分")
msg = ("%s 选梯定列+同列起步段修复(治同列竖梯录成上下几段时误选悬在头顶的上段:"
       "X最近定列->同列(X差<=15且Y区间不重叠)上下段并入->上行取梯底端最靠下y_bottom最大/下行取梯顶端最靠上y_top最小起步段) "
       "新增常量LADDER_MM_SAME_COL_X=15/SAME_COL_OV=2 离线route_005真实录制数据2850格单段零回归真机待验 "
       "同层打怪正常+光点小地图巡路正常+锁梯永振修复在版+跑跳直跳正常+血条伤害判定正常" % t)
mp = os.path.join(repo, "_commit_msg.txt")
io.open(mp, "w", encoding="utf-8", newline="").write(msg)
def run(args):
    r = subprocess.run(["git", "-C", repo] + args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("$ git", " ".join(args))
    if r.stdout: print(r.stdout.strip())
    if r.stderr: print("ERR:", r.stderr.strip())
    return r.returncode
run(["add", "maple_route_ui.py"])
run(["commit", "-F", mp])
try: os.remove(mp)
except OSError: pass
run(["log", "-1", "--oneline"])
run(["status", "--short", "--", "maple_route_ui.py"])
