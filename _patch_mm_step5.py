# -*- coding: utf-8 -*-
"""Step5: 下行方式二(实心台直接跳不下)小地图化,删白框lad_scr精对位依赖。
- check_drop第二次失败: _enter_desc_lad_scr(白框) -> _enter_desc_mm_ladder(小地图选下行梯)
- 删除从不进入的'to_ladder'死相 + 'lad_scr'白框精对位相,合并为新'mm_to_lad'相:
  每帧最新光点选下行合格梯(梯顶Y≈光点、下通)钉x,|x差|<=LADDER_MM_DESC_ALIGN_TOL(1)直接lad_grab按↓;
  没到按住_desc_horiz_walk走(带stall);连续选不到/走不到=放弃回主线,不发呆。
- 新增 _enter_desc_mm_ladder / _desc_mm_ladder_tick。方法本体 _enter_desc_lad_scr/_desc_align_ladder_screen
  本步后无调用,留 step6 物理删。保持BOM/CRLF。"""
import io
P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(P, 'r', encoding='utf-8-sig', newline='') as f:
    text = f.read()
def crlf(s): return s.replace('\r\n', '\n').replace('\n', '\r\n')

# 1) 新增两个方法(插在 _enter_desc_lad_grab 前)
anchor_grab = '    def _enter_desc_lad_grab(self, py, now_ms):'
assert text.count(anchor_grab) == 1, 'grab anchor %d' % text.count(anchor_grab)
new_methods = '''    def _enter_desc_mm_ladder(self, px, py, now_ms):
        """方式二入口(实心台方式一跳不下):改用小地图光点+录制梯选一把【向下】的梯,进mm_to_lad对位(用户2026-09-21,删白框lad_scr)。"""
        self._release_move_conflicts()
        self._key_up(VK_LEFT); self._key_up(VK_RIGHT); self._key_up(VK_DOWN)
        self._desc_phase = 'mm_to_lad'
        self._desc_phase_t = now_ms
        self._desc_mm_no_pick_t = 0
        self._ladder_precise_mode = True   # 方式二期间停锁怪(识怪照开),出段_reset_climb/落地重开
        _debug_log("[下行·方式二] 转小地图找下行梯(光点%.0f,%.0f)" % (px, py))

    def _desc_mm_ladder_tick(self, px, py, now_ms):
        """方式二小地图选梯+对位:选下行梯(梯顶Y差<=LADDER_MM_END_TOL、梯身下通)钉x;对齐<=LADDER_MM_DESC_ALIGN_TOL
        直接lad_grab按↓;没到按住朝梯走(_desc_horiz_walk带stall);连续选不到/走不到=放弃回主线打怪,不死等不发呆。"""
        ld = self._pick_ladder_minimap(getattr(self, 'ladders', None), px, py, -1, None)
        if ld is None:
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            if getattr(self, '_desc_mm_no_pick_t', 0) == 0:
                self._desc_mm_no_pick_t = now_ms
            elif now_ms - self._desc_mm_no_pick_t >= LADDER_MM_NOPICK_TIMEOUT_MS:
                _debug_log("[下行·方式二] 连续%.0fms小地图无下行合格梯,放弃回主线" % LADDER_MM_NOPICK_TIMEOUT_MS)
                self._rlog("小地图找不到下行梯,回主线打怪", LOG_RED, log='exception')
                self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
                self._reset_climb(); self._decide_climb_fail_action()
            return False
        self._desc_mm_no_pick_t = 0
        self._climb_ladder_x = float(ld['x'])
        self._climb_ladder_y_top = float(ld['y_top'])
        self._climb_ladder_y_bottom = float(ld['y_bottom'])
        dx = float(ld['x']) - float(px)
        if abs(dx) <= LADDER_MM_DESC_ALIGN_TOL:
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            _debug_log("[下行·方式二] 光点对齐梯X(差%.1f<=%d),直接按↓抓梯" % (dx, LADDER_MM_DESC_ALIGN_TOL))
            self._enter_desc_lad_grab(py, now_ms)
            return False

        def _on_stall():
            _debug_log("[下行·方式二] 小地图走不到梯X,放弃回主线")
            self._rlog("下行走不到梯子,回主线打怪", LOG_RED, log='exception')
            self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
            self._reset_climb(); self._decide_climb_fail_action()
        self._desc_horiz_walk(float(ld['x']), px, now_ms, _on_stall, "[下行·方式二] 小地图朝下行梯移动,走不到放弃")
        return False

'''
text = text.replace(anchor_grab, crlf(new_methods) + anchor_grab, 1)

# 2) 切片替换 'to_ladder'死相 + 'lad_scr'相 -> 'mm_to_lad'相
sa = '        # ②to_ladder【方式二·段1·小地图粗导航】'
ea = '        # ③lad_grab【方式二·步骤2】'
assert text.count(sa) == 1, 'slice-start %d' % text.count(sa)
assert text.count(ea) == 1, 'slice-end %d' % text.count(ea)
new_phase = crlf(
    '        # ②mm_to_lad【方式二·小地图选梯+对位(用户2026-09-21定稿,删白框lad_scr精对位)】实心台直接跳不下:\r\n'
    '        #   每帧最新光点选下行合格梯(梯顶与光点Y差<=LADDER_MM_END_TOL且梯身下通)钉x;对齐|x差|<=LADDER_MM_DESC_ALIGN_TOL\r\n'
    '        #   松键直接lad_grab按↓;没到按住走;走不到(stall)/连续选不到=放弃回主线,不发呆不死等。\r\n'
    '        if ph == \'mm_to_lad\':\r\n'
    '            return self._desc_mm_ladder_tick(px, py, now_ms)\r\n'
    '\r\n')
i0 = text.index(sa); i1 = text.index(ea)
text = text[:i0] + new_phase + text[i1:]

# 3) check_drop 第二次失败转方式二: 白框入口 -> 小地图入口(切片后该调用在_descend_step唯一)
old_call = '                self._enter_desc_lad_scr(now_ms)\r\n'
assert text.count(old_call) == 1, 'check_drop call %d' % text.count(old_call)
text = text.replace(old_call, '                self._enter_desc_mm_ladder(px, py, now_ms)\r\n', 1)

with io.open(P, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(text)
print('STEP5 OK: descend method-2 switched to minimap ladder (no white-frame align)')
