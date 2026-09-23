# -*- coding: utf-8 -*-
"""修闸门1方向bug: 朝梯方向在ad>FINE_DX时锁定、近距保持,冲过梯X(d=0/轻微越线)不翻向;
否则高速冲到梯正下当帧d=0会把朝梯速度算反、跑跳不触发。新增_ladder_mm_dir_sign(reset/realign清零)。"""
import io
PATH = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(PATH, 'r', encoding='utf-8-sig', newline='') as f:
    s = f.read()

def repl(text, old, new):
    n = text.count(old)
    assert n == 1, '锚点命中%d(应1): %r' % (n, old[:70])
    return text.replace(old, new)

# 1) goto 段2: 方向解耦瞬时d符号
old = ("        d = float(ld['x']) - float(px)\r\n"
       "        ad = abs(d)\r\n"
       "        _right = d > 0\r\n"
       "        rj = int(self._ladder_jump_cfg.get('rj_r' if _right else 'rj_l', LADDER_MM_RUNJUMP_DEFAULT))\r\n"
       "        vl = int(self._ladder_jump_cfg.get('vl_r' if _right else 'vl_l', LADDER_MM_VERT_DEFAULT))\r\n"
       "        _prev_px = getattr(self, '_ladder_mm_prev_px', None)\r\n"
       "        dpx = (px - _prev_px) if _prev_px is not None else 0.0\r\n"
       "        approach = (1.0 if _right else -1.0) * dpx    # >0=朝梯移动\r\n")
new = ("        d = float(ld['x']) - float(px)\r\n"
       "        ad = abs(d)\r\n"
       "        # 朝梯方向只在人还离梯有距离(ad>微调带)时按d符号更新;进微调/直跳带后保持,冲过梯X(d=0或轻微越线)不翻向\r\n"
       "        if ad > LADDER_MM_FINE_DX:\r\n"
       "            self._ladder_mm_dir_sign = 1 if d > 0 else -1\r\n"
       "        _dir_sign = getattr(self, '_ladder_mm_dir_sign', None)\r\n"
       "        if _dir_sign not in (1, -1):\r\n"
       "            _dir_sign = 1 if d >= 0 else -1\r\n"
       "        _right = _dir_sign > 0\r\n"
       "        rj = int(self._ladder_jump_cfg.get('rj_r' if _right else 'rj_l', LADDER_MM_RUNJUMP_DEFAULT))\r\n"
       "        vl = int(self._ladder_jump_cfg.get('vl_r' if _right else 'vl_l', LADDER_MM_VERT_DEFAULT))\r\n"
       "        _prev_px = getattr(self, '_ladder_mm_prev_px', None)\r\n"
       "        dpx = (px - _prev_px) if _prev_px is not None else 0.0\r\n"
       "        approach = float(_dir_sign) * dpx    # >0=朝梯移动(用锁定的靠近方向,不被d=0翻向)\r\n")
s = repl(s, old, new)

# 2) reset 字段块加 dir_sign(锚 prev_ad 那行,带注释唯一)
old2 = "        self._ladder_mm_prev_ad = None      # 上一拍人梯|X差|(跑跳跨rj下降沿判定)\r\n"
new2 = old2 + "        self._ladder_mm_dir_sign = None      # 锁定的朝梯方向±1(ad>FINE_DX才更新,冲过梯X不翻向);None=首帧按d定\r\n"
s = repl(s, old2, new2)

# 3) realign 清基线处加 dir_sign=None(无注释三连,唯一)
old3 = ("        self._ladder_mm_prev_px = None\r\n"
        "        self._ladder_mm_prev_ad = None\r\n"
        "        self._ladder_mm_approach_streak = 0\r\n")
new3 = old3 + "        self._ladder_mm_dir_sign = None\r\n"
s = repl(s, old3, new3)

with io.open(PATH, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(s)
print('DIRSIGN PATCH OK')
