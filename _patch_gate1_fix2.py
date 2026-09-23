# -*- coding: utf-8 -*-
"""闸门1真机数据修复(第二批,根因级):
1) start_jump('vert') 补 run_jumped=False(与run互斥)。否则跑跳失败realign置run=True后,直跳post被误判成跑跳:
   100ms才按↑/why=跑跳满窗/realign不累计直跳轮次→3轮放弃失效→真机id=6梯底直跳死循环14s(日志21:55:36~50实证)。
2) 跑跳速度门:真机小地图光点走路~1px/帧且夹0帧,"连续2帧每帧>=MOVING_DX"被0帧反复清零、跨7线跑跳拖到ad≈2(日志朝左X差2才跳)。
   改:approach>0累计、<0倒退清零、==0(量化0帧)保持;跑跳门去掉本帧>=MOVING_DX(跨线本身需位移,streak≥2已证持续趋近),删死常量。"""
import io
PATH = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(PATH, 'r', encoding='utf-8-sig', newline='') as f:
    s = f.read()

def repl(text, old, new):
    n = text.count(old)
    assert n == 1, '锚点命中%d(应1): %r' % (n, old[:60])
    return text.replace(old, new)

# 1) vert 互斥置位
old1 = ("        else:\r\n"
        "            self._ladder_vert_jumped = True\r\n"
        "        self._ladder_back_peak = 0.0\r\n")
new1 = ("        else:\r\n"
        "            self._ladder_vert_jumped = True\r\n"
        "            self._ladder_run_jumped = False   # 与run互斥:realign后run=True,直跳必须清回False,否则post误判跑跳(50ms/直跳轮次/3轮放弃全失效→真机梯底14s死循环根因)\r\n"
        "        self._ladder_back_peak = 0.0\r\n")
s = repl(s, old1, new1)

# 2a) streak 三分支:0帧保持
old2 = ("        if approach > 0:\r\n"
        "            self._ladder_mm_approach_streak += 1\r\n"
        "        else:\r\n"
        "            self._ladder_mm_approach_streak = 0\r\n")
new2 = ("        if approach > 0:\r\n"
        "            self._ladder_mm_approach_streak += 1\r\n"
        "        elif approach < 0:\r\n"
        "            self._ladder_mm_approach_streak = 0\r\n"
        "        # approach==0(光点量化0帧/coast)保持累计不清零:真机走路约1px/帧且夹0帧,连续硬判把跨7线跑跳拖到ad≈2(真机实证);倒退才清零,静止光点正负抖动仍凑不齐\r\n")
s = repl(s, old2, new2)

# 2b) 跑跳门去 MOVING_DX
old3 = ("                and self._ladder_mm_approach_streak >= LADDER_MM_APPROACH_FRAMES\r\n"
        "                and approach >= LADDER_MM_MOVING_DX and (_cross or ad <= rj)):\r\n")
new3 = ("                and self._ladder_mm_approach_streak >= LADDER_MM_APPROACH_FRAMES\r\n"
        "                and (_cross or ad <= rj)):\r\n")
s = repl(s, old3, new3)

# 2c) docstring 同步
old4 = "          ·跑跳=上一拍ad>rj、本拍ad<=rj的跨线下降沿 且 连续朝梯 且 本拍仍带速(朝梯帧位移>=MOVING_DX),不松方向键带速跳(每把梯一次);\r\n"
new4 = "          ·跑跳=上一拍ad>rj、本拍ad<=rj的跨线下降沿(或已在线内) 且 累计≥APPROACH_FRAMES拍朝梯移动(光点0帧不清零、倒退清零,容忍真机~1px/帧夹0帧),不松方向键带速跳(每把梯一次);\r\n"
s = repl(s, old4, new4)

# 2d) 删死常量 LADDER_MM_MOVING_DX(按行名,断言恰好1行)
ls = s.splitlines(keepends=True)
ls2 = [ln for ln in ls if not ln.lstrip().startswith('LADDER_MM_MOVING_DX =')]
assert len(ls) - len(ls2) == 1, 'MOVING_DX 删除行数=%d(应1)' % (len(ls) - len(ls2))
s = ''.join(ls2)

with io.open(PATH, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(s)
print('GATE1 FIX2 OK')
