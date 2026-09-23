# -*- coding: utf-8 -*-
"""施工补丁Step3: 上行上梯切换为小地图光点+录制梯 goto 状态机(选梯/分带/跑跳/微调/直跳/失败回退)。
- 新增 _ladder_mm_pin/_ladder_mm_start_jump/_ladder_mm_realign/_ladder_mm_fine_tick/_ladder_mm_goto_tick
- to_ladder 上行分支改为 post_jump看后脑 / 其余走 _ladder_mm_goto_tick(屏幕approach/align/伺服不再被调用)
- post_jump 满窗没抓住 由屏幕伺服 _ladder_realign_jump 改 _ladder_mm_realign
- rj/vl 默认与clamp改小地图口径(默认7/1)
保持 BOM(utf-8-sig)/CRLF,每处锚点唯一断言。"""
import io

P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(P, 'r', encoding='utf-8-sig', newline='') as f:
    text = f.read()

def crlf(s):
    return s.replace('\r\n', '\n').replace('\n', '\r\n')

def rep(old, new, tag, n=1):
    global text
    c = text.count(old)
    assert c == n, '[%s] anchor count=%d (want %d)' % (tag, c, n)
    text = text.replace(old, crlf(new), n)

# A) 补常量 NOPICK
rep(
    'LADDER_MM_DESC_ALIGN_TOL = 1    # 下行方式二:光点对齐录制梯X|差|<=1即按↓抓梯下滑',
    'LADDER_MM_DESC_ALIGN_TOL = 1    # 下行方式二:光点对齐录制梯X|差|<=1即按↓抓梯下滑\r\n'
    'LADDER_MM_NOPICK_TIMEOUT_MS = 1500  # 上行连续多久选不到合格录制梯->放弃回主线打怪(防发呆)',
    'A-NOPICK')

# B) reset 新增小地图对位字段
rep(
    "        self._ladder_realign_round = 0       # 直跳尝试次数(每进一次校准+1,最多LADDER_REALIGN_MAX_ROUNDS)",
    "        self._ladder_realign_round = 0       # 直跳尝试次数(每进一次校准+1,最多LADDER_REALIGN_MAX_ROUNDS)\r\n"
    "        self._ladder_mm_fine_phase = ''      # 小地图微调相位 ''/move/gap(用户2026-09-21)\r\n"
    "        self._ladder_mm_fine_t = 0           # 微调当前拍起始时刻ms\r\n"
    "        self._ladder_mm_fine_round = 0       # 微调已走拍数(最多LADDER_MM_FINE_MAX)\r\n"
    "        self._ladder_mm_no_pick_t = 0        # 连续选不到合格录制梯计时(0=本帧选到)",
    'B-RESET')

# C) 默认 jump cfg 改小地图 7/1
rep(
    '        self._ladder_jump_cfg = {"rj_l": LADDER_RUNJUMP_DX_DEFAULT, "rj_r": LADDER_RUNJUMP_DX_DEFAULT,\r\n'
    '                                 "vl_l": LADDER_VERT_LEAD_DEFAULT, "vl_r": LADDER_VERT_LEAD_DEFAULT}',
    '        self._ladder_jump_cfg = {"rj_l": LADDER_MM_RUNJUMP_DEFAULT, "rj_r": LADDER_MM_RUNJUMP_DEFAULT,\r\n'
    '                                 "vl_l": LADDER_MM_VERT_DEFAULT, "vl_r": LADDER_MM_VERT_DEFAULT}',
    'C-DEFAULTCFG')

# D) clamp 改小地图口径
rep(
    '        return {\r\n'
    '            "rj_l": _num(j.get("rj_l"), LADDER_RUNJUMP_DX_DEFAULT, LADDER_RUNJUMP_DX_MIN, 200),\r\n'
    '            "rj_r": _num(j.get("rj_r"), LADDER_RUNJUMP_DX_DEFAULT, LADDER_RUNJUMP_DX_MIN, 200),\r\n'
    '            "vl_l": _num(j.get("vl_l"), LADDER_VERT_LEAD_DEFAULT, LADDER_VERT_LEAD_MIN, LADDER_VERT_LEAD_MAX),\r\n'
    '            "vl_r": _num(j.get("vl_r"), LADDER_VERT_LEAD_DEFAULT, LADDER_VERT_LEAD_MIN, LADDER_VERT_LEAD_MAX),\r\n'
    '        }',
    '        return {\r\n'
    '            "rj_l": _num(j.get("rj_l"), LADDER_MM_RUNJUMP_DEFAULT, 3, 20),\r\n'
    '            "rj_r": _num(j.get("rj_r"), LADDER_MM_RUNJUMP_DEFAULT, 3, 20),\r\n'
    '            "vl_l": _num(j.get("vl_l"), LADDER_MM_VERT_DEFAULT, 0, 5),\r\n'
    '            "vl_r": _num(j.get("vl_r"), LADDER_MM_VERT_DEFAULT, 0, 5),\r\n'
    '        }',
    'D-CLAMP')

# E) enter 末尾置 mm_goto 相位 + 字段初始化
rep(
    "        self._climb_direction = 1\r\n        self._climb_action_time = now_ms\r\n        self._lad_scr_enter_t = 0\r\n",
    "        self._climb_direction = 1\r\n        self._climb_action_time = now_ms\r\n        self._lad_scr_enter_t = 0\r\n"
    "        self._ladder_jump_phase = 'mm_goto'   # 小地图选梯/对位中(post_jump=起跳后看后脑)\r\n"
    "        self._ladder_mm_fine_phase = ''\r\n"
    "        self._ladder_mm_fine_t = 0\r\n"
    "        self._ladder_mm_fine_round = 0\r\n"
    "        self._ladder_mm_no_pick_t = 0\r\n"
    "        self._ladder_realign_round = 0\r\n",
    'E-ENTER')

# F) 新增5个小地图方法(插在 _ladder_post_jump_process 前)
methods = '''    def _ladder_mm_pin(self, ld):
        """小地图选中录制梯那一刻即钉死端点x/y_top/y_bottom+录制爬升时长(不等抓梯后反查;用户2026-09-21)。"""
        self._climb_ladder_x = float(ld['x'])
        self._climb_ladder_y_top = float(ld['y_top'])
        self._climb_ladder_y_bottom = float(ld['y_bottom'])
        _dur = ld.get('duration_sec')
        self._climb_ladder_duration = float(_dur) if isinstance(_dur, (int, float)) and float(_dur) >= 1.0 else None

    def _ladder_mm_start_jump(self, kind, d, py, now_ms, jump_key):
        """小地图对位起跳:kind='run'带速跑跳(松左右、跳120、100ms后按↑)/'vert'原地直跳(松左右、跳120、50ms后按↑)。
        起跳后统一交_ladder_post_jump_process看后脑(连续BACK_GRAB_FRAMES帧=抓住);基准Y=起跳前光点Y。"""
        self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
        if VK_DOWN in self._random_move_keys:
            self._key_up(VK_DOWN)
        self._climb_start_y = py
        if kind == 'run':
            self._ladder_run_jumped = True
            self._ladder_vert_jumped = False
        else:
            self._ladder_vert_jumped = True
        self._press_game_key(jump_key, duration=120)
        self._ladder_jump_phase = 'post_jump'
        self._ladder_post_jump_step = 'delay1'
        self._ladder_post_jump_t = now_ms
        self._ladder_back_seen_frames = 0
        _side = '右' if d > 0 else '左'
        _debug_log("[爬梯·小地图·%s] 朝%s起跳 人梯X差%.1f(光点Y=%.0f):松左右跳120,%dms后按↑判后脑" % (
            '跑跳' if kind == 'run' else '直跳', _side, abs(d), py, (100 if kind == 'run' else 50)))
        if kind == 'run':
            self._rlog("小地图跑跳上梯(朝%s差%.1f)" % (_side, abs(d)), log='behavior')
        return False

    def _ladder_mm_realign(self, py, now_ms, why):
        """起跳后满窗没抓住后脑:回小地图goto走近再直跳。跑跳失败不占直跳轮次(只回goto,人已在1~6段靠近);
        直跳失败每轮+1,满LADDER_REALIGN_MAX_ROUNDS放弃回主线打怪(不发呆)。"""
        for _vk in (VK_UP, VK_LEFT, VK_RIGHT):
            if _vk in self._random_move_keys:
                self._key_up(_vk)
        if '跑跳' not in str(why):
            self._ladder_realign_round = getattr(self, '_ladder_realign_round', 0) + 1
            if self._ladder_realign_round > LADDER_REALIGN_MAX_ROUNDS:
                _debug_log("[爬梯·小地图] 直跳%d次仍没抓住(%s),放弃回主线打怪" % (LADDER_REALIGN_MAX_ROUNDS, why))
                self._rlog("小地图直跳%d次没挂上梯,回主线打怪" % LADDER_REALIGN_MAX_ROUNDS, LOG_RED, log='exception')
                self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
                self._reset_climb(); self._decide_climb_fail_action()
                return False
        else:
            _debug_log("[爬梯·小地图] 跑跳没抓住(%s),回goto走近再直跳(不占直跳轮次)" % why)
        self._ladder_run_jumped = True
        self._ladder_vert_jumped = False
        self._ladder_jump_phase = 'mm_goto'
        self._ladder_post_jump_step = None
        self._ladder_mm_fine_phase = ''
        self._ladder_mm_fine_t = 0
        self._ladder_mm_fine_round = 0
        return False

    def _ladder_mm_fine_tick(self, d, ad, vl, py, now_ms, jump_key):
        """小地图微调(vl<ad<=LADDER_MM_FINE_DX):点动 走MOVE_MS->抬键停GAP_MS检测,最多FINE_MAX拍;
        停后ad<=vl=进直跳窗(交主goto下帧vert起跳);拍满仍ad>vl=对不齐,放弃回主线打怪。"""
        ph = getattr(self, '_ladder_mm_fine_phase', '')
        vk = VK_RIGHT if d > 0 else VK_LEFT
        ovk = VK_LEFT if vk == VK_RIGHT else VK_RIGHT
        if ph == '':
            self._ladder_mm_fine_phase = 'move'; self._ladder_mm_fine_t = now_ms
            self._ladder_mm_fine_round = 1
            if ovk in self._random_move_keys: self._key_up(ovk)
            if vk not in self._random_move_keys: self._key_down(vk)
            return False
        if ph == 'move':
            if now_ms - self._ladder_mm_fine_t >= LADDER_MM_FINE_MOVE_MS:
                if vk in self._random_move_keys: self._key_up(vk)
                self._ladder_mm_fine_phase = 'gap'; self._ladder_mm_fine_t = now_ms
            return False
        if now_ms - self._ladder_mm_fine_t >= LADDER_MM_FINE_GAP_MS:
            if ad <= vl:
                self._ladder_mm_fine_phase = ''   # 下帧主goto判vert直跳
                return False
            if self._ladder_mm_fine_round >= LADDER_MM_FINE_MAX:
                _debug_log("[爬梯·小地图] 微调%d拍仍进不了0~%d直跳窗(剩%.1f),放弃回主线打怪" % (
                    LADDER_MM_FINE_MAX, vl, ad))
                self._rlog("小地图微调对不齐梯,回主线打怪", LOG_RED, log='exception')
                if vk in self._random_move_keys: self._key_up(vk)
                self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
                self._reset_climb(); self._decide_climb_fail_action()
                return False
            self._ladder_mm_fine_round += 1
            self._ladder_mm_fine_phase = 'move'; self._ladder_mm_fine_t = now_ms
            if vk not in self._random_move_keys: self._key_down(vk)
        return False

    def _ladder_mm_goto_tick(self, px, py, now_ms, jump_key):
        """上行小地图选梯+对位+起跳(用户2026-09-21最终定稿,取代屏幕白框approach/align/伺服realign三套)。
        每帧用最新光点(px,py)在self.ladders选梯(静态录制数据不闪,不要二帧稳/站定),锁定即钉录制梯端点。
        分带(人梯小地图|X差|ad,面板rj跑跳默认7/vl直跳默认1):ad>rj按住走;rj-1~rj且朝梯键正按住=带速跑跳;
        rj-1>ad>FINE_DX按住走;vl<ad<=FINE_DX微调点动;ad<=vl原地直跳。选不到梯连续NOPICK超时放弃回主线,不发呆。"""
        side_sign = None
        _fx = getattr(self, '_ladder_target_mon_x', None)
        _sp = self._player_screen_pos
        if _fx is not None and _sp is not None:
            _dsx = float(_fx) - float(_sp[0])
            if abs(_dsx) > 1.0:
                side_sign = 1 if _dsx > 0 else -1
        ld = self._pick_ladder_minimap(getattr(self, 'ladders', None), px, py, +1, side_sign)
        if ld is None:
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            if self._ladder_mm_no_pick_t == 0:
                self._ladder_mm_no_pick_t = now_ms
            elif now_ms - self._ladder_mm_no_pick_t >= LADDER_MM_NOPICK_TIMEOUT_MS:
                _debug_log("[选梯·小地图] 光点(%.0f,%.0f)连续%.0fms无合格录制梯(X±%d/梯底Y差≤%d/上通),放弃回主线打怪" % (
                    px, py, LADDER_MM_NOPICK_TIMEOUT_MS, LADDER_MM_X_HALF, LADDER_MM_END_TOL))
                self._rlog("小地图找不到够得着的梯,回主线打怪", LOG_RED, log='exception')
                self._reset_climb(); self._decide_climb_fail_action()
            return False
        self._ladder_mm_no_pick_t = 0
        self._ladder_mm_pin(ld)
        d = float(ld['x']) - float(px)
        ad = abs(d)
        _right = d > 0
        rj = int(self._ladder_jump_cfg.get('rj_r' if _right else 'rj_l', LADDER_MM_RUNJUMP_DEFAULT))
        vl = int(self._ladder_jump_cfg.get('vl_r' if _right else 'vl_l', LADDER_MM_VERT_DEFAULT))
        band = self._ladder_mm_band(ad, rj, vl)
        if band == 'vert':
            self._ladder_mm_fine_phase = ''
            return self._ladder_mm_start_jump('vert', d, py, now_ms, jump_key)
        if band == 'fine':
            return self._ladder_mm_fine_tick(d, ad, vl, py, now_ms, jump_key)
        if self._ladder_mm_fine_phase:
            self._ladder_mm_fine_phase = ''
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
        _move_vk = VK_RIGHT if _right else VK_LEFT
        if band == 'run' and (not getattr(self, '_ladder_run_jumped', False)) and _move_vk in self._random_move_keys:
            return self._ladder_mm_start_jump('run', d, py, now_ms, jump_key)
        self._hold_toward_ladder(d)
        return False

'''
rep('    def _ladder_post_jump_process(self, py, now_ms):',
    methods + '    def _ladder_post_jump_process(self, py, now_ms):',
    'F-METHODS')

# G) post_jump 两处满窗回退改小地图
rep('            return self._ladder_realign_jump(py, now_ms, "跑跳满窗没后脑")',
    '            return self._ladder_mm_realign(py, now_ms, "跑跳满窗没后脑")', 'G-RUN')
rep('        return self._ladder_realign_jump(py, now_ms, "直跳满窗没后脑")',
    '        return self._ladder_mm_realign(py, now_ms, "直跳满窗没后脑")', 'G-VERT')

# H) 切片替换 to_ladder 上行分支
sa = '        if self._climb_state == "to_ladder":\r\n'
ea = '        if self._climb_state == "climbing":\r\n'
assert text.count(sa) == 1, 'to_ladder anchor %d' % text.count(sa)
assert text.count(ea) == 1, 'climbing anchor %d' % text.count(ea)
new_block = crlf(
    '        if self._climb_state == "to_ladder":\r\n'
    '            fight_cfg = self._get_fight_config()\r\n'
    '            jump_key = fight_cfg.get("jump_key", "") or "c"\r\n'
    '            now_ms = time.time() * 1000\r\n'
    '            # 下行方式二(下跳失败转走梯下降)全程在state=descend的_descend_step内,不进这里;\r\n'
    '            # 上行:起跳后(post_jump)统一看后脑判抓梯;其余每帧小地图选梯/对位/起跳(用户2026-09-21定稿,屏幕白框一套已废)\r\n'
    '            if getattr(self, \'_ladder_jump_phase\', None) == \'post_jump\':\r\n'
    '                return self._ladder_post_jump_process(py, now_ms)\r\n'
    '            return self._ladder_mm_goto_tick(px, py, now_ms, jump_key)\r\n'
    '\r\n')
i0 = text.index(sa); i1 = text.index(ea)
text = text[:i0] + new_block + text[i1:]

with io.open(P, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(text)
print('STEP3 OK: minimap goto state machine wired into to_ladder')
