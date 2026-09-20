# -*- coding: utf-8 -*-
"""
原子改动: 上行锁梯 人梯Y差200硬门 (用户2026-09-20定稿, 只做这一处功能)
1) 上行选梯调用 y_far 由寻怪范围 far_range_y_up(实测350) 改回常量 LADDER_DIR_Y_UP_FAR(200), y_near=0 不变
   -> 人上方0~200外的梯段不进候选(原0~350致锁到离人306px的高梯)
2) 二帧稳梯建锁前再卡一次 人Y-锁点Y: 上行且>200 不建锁/丢弃重观察/计失败节拍(3拍走挪位/回主线,不发呆)
   建锁日志增加"人梯Y差%d"作为真机证据
3) 删掉选梯段被取代的死变量 _fc/_far_x/_far_yu 三行(grep确认该段无其它引用)
4) 同步过时注释
已锁后(align/爬梯)漂移门本次不加(无真机证据,不堆代码); X±300门已有三重,不动。
保 BOM + LF; 每处 assert 唯一命中; 末尾 py_compile。
"""
import sys
import py_compile

P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'

raw = open(P, 'rb').read()
assert raw.startswith(b'\xef\xbb\xbf'), '主文件必须带 UTF-8 BOM'
text = raw.decode('utf-8-sig')
assert '\r\n' not in text, '主文件必须 LF'
lines = text.splitlines(keepends=True)

# ---------- 步骤3: 删选梯段死变量 _fc/_far_x/_far_yu 三行 ----------
iyu = [i for i, l in enumerate(lines) if '_far_yu = max(20, int(_fc.get(' in l]
assert len(iyu) == 1, '定位 _far_yu 定义行失败: %r' % (iyu,)
iyu = iyu[0]
assert '_far_yu' in lines[iyu], lines[iyu]
assert '_far_x = max(50, int(_fc.get("far_range_x")' in lines[iyu - 1], lines[iyu - 1]
assert '_fc = self._get_fight_config()' in lines[iyu - 2], lines[iyu - 2]
del lines[iyu - 2:iyu + 1]
print('[1/4] 删除选梯段死变量 _fc/_far_x/_far_yu 三行 OK')

# ---------- 步骤2: 建锁前插 Y差硬门(程序化定位, 不手数缩进) ----------
ibc = [i for i, l in enumerate(lines) if 'if _beats >= LADDER_PICK_STABLE_BEATS:' in l]
assert len(ibc) == 1, '定位建锁 if 失败: %r' % (ibc,)
ib = ibc[0]
ind = len(lines[ib]) - len(lines[ib].lstrip(' '))
je = None
for j in range(ib + 1, len(lines)):
    s = lines[j]
    if s.strip() == 'else:' and (len(s) - len(s.lstrip(' '))) == ind:
        je = j
        break
assert je is not None, '找不到建锁 if 的同缩进 else'
block = ''.join(lines[ib + 1:je])
assert block.count('self._ladder_lock = (_bx, _by, _now_lm)') == 1
assert block.count('二帧稳梯:建锁') == 1
assert block.count('[选梯·建锁] 二帧稳定向%s') == 1

old_fmt = '[选梯·建锁] 二帧稳定向%s 人=(%d,%d) 怪X=%s 带内%d把[%s] 选中(%d,%d),已关怪扫一心上梯'
new_fmt = '[选梯·建锁] 二帧稳定向%s 人=(%d,%d) 怪X=%s 带内%d把[%s] 选中(%d,%d) 人梯Y差%d,已关怪扫一心上梯'
assert block.count(old_fmt) == 1, '建锁日志格式串未唯一命中'
block = block.replace(old_fmt, new_fmt)

old_args = "'上' if _cdir > 0 else '下', _psx, _psy, _tmox, len(_db_band), _pick_reason, _bx, _by))"
new_args = "'上' if _cdir > 0 else '下', _psx, _psy, _tmox, len(_db_band), _pick_reason, _bx, _by, _dy_lock))"
assert block.count(old_args) == 1, '建锁日志参数未唯一命中'
block = block.replace(old_args, new_args)

old_cmt = '# 二帧稳梯:建锁+冻像素块身份,这一帧才关怪扫(关扫窗口最短),转align对位'
new_cmt = '# 二帧稳梯且Y差合格:建锁+冻像素块身份,这一帧才关怪扫(关扫窗口最短),转align对位'
assert block.count(old_cmt) == 1, '建锁注释未唯一命中'
block = block.replace(old_cmt, new_cmt)

# 原建锁块整体再缩进4(放进新 else 下); 空行不缩进
reindented = [('    ' + l) if l.strip() else l for l in block.splitlines(keepends=True)]
p4 = ' ' * (ind + 4)
p8 = ' ' * (ind + 8)
gate = [
    p4 + '_dy_lock = _psy - _by        # 上行=人名基点Y-锁点Y(>0梯在人上方);锁梯人梯Y差硬门 LADDER_DIR_Y_UP_FAR=200(用户2026-09-20)\n',
    p4 + 'if _cdir > 0 and _dy_lock > LADDER_DIR_Y_UP_FAR:\n',
    p8 + '# 二帧稳到的锁点仍在人上方200外=这把当前够不着(跨拍漂到高梯/选错):不建锁,丢弃重观察并计失败节拍(连续3拍走挪位/回主线,不发呆、不锁高梯)\n',
    p8 + 'self._ladder_pick_stable = None\n',
    p8 + 'self._ladder_pick_fail_beats += 1\n',
    p8 + "_stage = '人梯Y差%d>%d放弃重选' % (_dy_lock, LADDER_DIR_Y_UP_FAR)\n",
    p8 + '_debug_log("[选梯·Y门] 稳梯锁点(%d,%d) 人Y=%d 人梯Y差%d>%d,放弃这把不建锁(连续%d拍无合格梯→挪位/回主线重锁)" % (\n',
    p8 + '    _bx, _by, _psy, _dy_lock, LADDER_DIR_Y_UP_FAR, LADDER_PICK_FAIL_BEATS))\n',
    p4 + 'else:\n',
]
lines[ib + 1:je] = gate + reindented
print('[2/4] 建锁前 人梯Y差200硬门 插入 OK')

text = ''.join(lines)

# ---------- 步骤1: 上行选梯调用 y_far 改常量200 ----------
old_a = 'x_half=LADDER_DIR_X_HALF, y_far=_far_yu, y_near=0)  # 锁梯必须人梯|X差|<=300(用户2026-09-20);原_far_x=1300会锁到离人451够不着的远梯'
new_a = 'x_half=LADDER_DIR_X_HALF, y_far=LADDER_DIR_Y_UP_FAR, y_near=0)  # X半宽300 + 上行人梯Y差硬门200(用户2026-09-20:锁梯第一时间卡人Y-梯Y,>=200放弃;原y_far传寻怪far_range_y_up=350,锁到离人306高梯)'
assert text.count(old_a) == 1, '上行选梯调用未唯一命中'
text = text.replace(old_a, new_a)
assert '_far_yu' not in text, '仍残留 _far_yu'
print('[3/4] 上行选梯 y_far 350->LADDER_DIR_Y_UP_FAR(200) OK')

# ---------- 步骤4: 同步过时注释 ----------
old_b = '(蒙板段传寻怪范围且y_near=0含脚边,用户2026-09-19)'
new_b = '(蒙板段传LADDER_DIR_Y_UP_FAR=200作人梯Y差硬门、y_near=0含脚边,用户2026-09-20)'
assert text.count(old_b) == 1, '选梯函数上行注释未唯一命中'
text = text.replace(old_b, new_b)

old_c = '上行头顶Y-150~-20/下行脚下0~+150'
new_c = '上行头顶0~-200人梯Y差硬门/下行脚下0~+150'
assert text.count(old_c) == 1, '选梯流程大注释未唯一命中'
text = text.replace(old_c, new_c)
print('[4/4] 注释同步 OK')

# ---------- 写回(保BOM/LF) + 编译 ----------
out = b'\xef\xbb\xbf' + text.encode('utf-8')
with open(P, 'wb') as f:
    f.write(out)
py_compile.compile(P, doraise=True)
print('完成: 已写回(BOM/LF) + py_compile 通过')
