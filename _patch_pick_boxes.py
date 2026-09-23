# -*- coding: utf-8 -*-
"""根因修复:_pick_climb_boxes 被误加 @staticmethod,但形参带 self 且函数体用 self._monsters 躲怪。
staticmethod 不绑 self -> self._pick_climb_boxes(ppos,fh,fw) 三实参按位填(self,ppos,fh),缺 fw,
下跳方式一 fall 落地检测每帧 TypeError(22:07后207次),tick 被战斗try吞掉中断。删除装饰器恢复实例方法。"""
import io
PATH = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(PATH, 'r', encoding='utf-8-sig', newline='') as f:
    s = f.read()

old = ("    @staticmethod\r\n"
       "    # ==================== 爬梯登顶·绑定人物基点的三背景点")
new = ("    # ==================== 爬梯登顶·绑定人物基点的三背景点")
n = s.count(old)
assert n == 1, '锚点命中%d(应1)' % n
s = s.replace(old, new)

with io.open(PATH, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(s)
print('PICK_BOXES FIX OK')
