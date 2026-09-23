# -*- coding: utf-8 -*-
"""Step6b: 物理删除蒙板段白框消费/绘制下发与运行态选梯建锁大脑(约216行)。
- 常开(停止态)层: 删 ladder_marks 白框候选/ladder_sel/ladder_rect 下发,保留停止态清锁定红框;
- 运行态 try 块: 删 18655~18870 整段白框选梯/二帧稳建锁/实时跟踪/冻结块补位/漂出清锁/ladder_sel下发;
  保留 _climb_hide_mon 红框唯一逻辑与外层 except。新上/下梯选梯已全部走小地图(_ladder_mm_goto_tick/_desc_mm_ladder_tick)。
保持BOM/CRLF。"""
import io
P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(P, 'r', encoding='utf-8-sig', newline='') as f:
    text = f.read()
def crlf(s): return s.replace('\r\n', '\n').replace('\n', '\r\n')

# 块A: 常开(停止态)层白框下发 -> 只保留停止态清锁定红框
startA = '            # 梯子白框【常开显示】'
endA = crlf('            if not self._running:\r\n'
            '                self._monster_overlay_data["ladder_sel"] = None\r\n'
            '                self._monster_overlay_data["ladder_rect"] = None\r\n'
            '                self._monster_overlay_data["locked_rect"] = None\r\n')
assert text.count(startA) == 1, 'startA %d' % text.count(startA)
assert text.count(endA) == 1, 'endA %d' % text.count(endA)
i0a = text.index(startA); i1a = text.index(endA) + len(endA)
newA = crlf('            # 白框特征梯整套已删(用户2026-09-21改小地图光点+录制梯);停止态只清残留锁定红框\r\n'
            '            if not self._running:\r\n'
            '                self._monster_overlay_data["locked_rect"] = None\r\n')
text = text[:i0a] + newA + text[i1a:]

# 块B: 运行态选梯建锁大脑整段(从"=== 梯子选框"注释到 ladder_rect 下发行)
startB = '                    # === 梯子选框(用户2026-09-15:不锁定,每帧实时选) ==='
endB = '                    self._monster_overlay_data["ladder_rect"] = None  # 旧洋红16宽全长框停用,统一为120x50红框ladder_sel\r\n'
assert text.count(startB) == 1, 'startB %d' % text.count(startB)
assert text.count(endB) == 1, 'endB %d' % text.count(endB)
i0b = text.index(startB); i1b = text.index(endB) + len(endB)
text = text[:i0b] + text[i1b:]

with io.open(P, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(text)
print('STEP6b OK: overlay white-frame publish & runtime lock brain removed')
