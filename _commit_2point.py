# -*- coding: utf-8 -*-
# 一次性提交(不提交git): 梯子二点式录制+同列整条覆盖
import io, os, subprocess, datetime
repo = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"
t = datetime.datetime.now().strftime("%Y-%m-%d号 %H点%M分")
msg = ("%s 梯子改二点式录制+同列整条覆盖(用户2026-09-23):"
       "①录制只留首尾两个光点(梯底端/梯顶端)成一条竖直线,中间爬梯轨迹点一帧不存,x=首尾X均值不再被爬梯晃动带偏;"
       "②extract_ladder两点式取min/max;"
       "③同列覆盖:新录梯与旧录梯|X差|<LADDER_REC_SAME_COL_X(=8)判同一列,删除同列全部旧碎段、新端到端整条插回原列位置并继承最小编号,并排梯(实测最小间距9)不吞;"
       "④新增常量LADDER_REC_SAME_COL_X=8。离线route_005真实碎段验证:右列碎段id2/3/4/5合并一条、id1/8合并、并排id6保留、物理顺序正确,ALL PASS真机待验 "
       "同层打怪正常+光点小地图巡路正常+选梯定列同列起步段修复在版+跑跳直跳正常+血条伤害判定正常" % t)
mp = os.path.join(repo, "_commit_msg.txt")
io.open(mp, "w", encoding="utf-8", newline="").write(msg)
def run(a):
    r = subprocess.run(["git","-C",repo]+a, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("$ git", " ".join(a))
    if r.stdout: print(r.stdout.strip())
    if r.stderr: print("ERR:", r.stderr.strip())
run(["add","maple_route_ui.py"])
run(["commit","-F",mp])
try: os.remove(mp)
except OSError: pass
run(["log","-1","--oneline"])
run(["status","--short","--","maple_route_ui.py"])
