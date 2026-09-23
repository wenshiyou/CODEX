# -*- coding: utf-8 -*-
"""闸门1第一批(离线可验、不赌真机命门): 小地图上行 锁梯一次/跑跳跨线带速/直跳停稳/删run_hold死分支。
ast 整函数替换(含@staticmethod上扩) + 唯一锚点插常量/字段/删常量。保 utf-8-sig BOM + CRLF。"""
import ast, io, sys

PATH = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'

with io.open(PATH, 'r', encoding='utf-8-sig', newline='') as f:
    src = f.read()

# ---------- 6 个新函数(普通\n缩进4方法体) ----------
NEW_BAND = '''    @staticmethod
    def _ladder_mm_band(ad, rj, vl):
        """上行小地图人梯|X差|静态分带(只分三档;带速跑跳由goto按"跨rj下降沿+朝梯速度"单独触发,不在此):
        ad<=vl=vert原地直跳;vl<ad<=FINE_DX=fine微调点动;其余=walk持续按住朝梯走(旧far/near同动作合并)。"""
        if ad <= vl:
            return 'vert'
        if ad <= LADDER_MM_FINE_DX:
            return 'fine'
        return 'walk'
'''

NEW_START_JUMP = '''    def _ladder_mm_start_jump(self, kind, d, py, now_ms, jump_key, vx=0.0):
        """小地图对位起跳(用户2026-09-21定稿,坐标全=小地图光点)。
        kind='run'带速跑跳:【不松朝梯方向键】(只松对侧+松↓),跳120,朝梯键继续按住带水平速度腾空,
                 delay1到100ms才由post_jump统一_release_move_conflicts松左右+按↑抓绳(auto-maple FlashJump同时序;
                 修旧版起跳当帧就松左右=零水平速度,跑跳变原地跳永远蹭不到绳);
        kind='vert'原地直跳:起跳当帧松左右、跳120,50ms后按↑。
        起跳后统一交_ladder_post_jump_process看后脑(连续BACK_GRAB_FRAMES帧=抓住);基准Y=起跳前光点Y。vx=起跳帧朝梯位移(标定埋点)。"""
        _move_vk = VK_RIGHT if d > 0 else VK_LEFT
        _opp_vk = VK_LEFT if _move_vk == VK_RIGHT else VK_RIGHT
        if kind == 'run':
            if _opp_vk in self._random_move_keys:
                self._key_up(_opp_vk)            # 只松对侧,朝梯键保持按住=带水平速度
            if _move_vk not in self._random_move_keys:
                self._key_down(_move_vk)
        else:
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
        if VK_DOWN in self._random_move_keys:
            self._key_up(VK_DOWN)
        self._climb_start_y = py
        if kind == 'run':
            self._ladder_run_jumped = True
            self._ladder_vert_jumped = False
        else:
            self._ladder_vert_jumped = True
        self._ladder_back_peak = 0.0
        self._ladder_back_seen_frames = 0
        self._press_game_key(jump_key, duration=120)
        self._ladder_jump_phase = 'post_jump'
        self._ladder_post_jump_step = 'delay1'
        self._ladder_post_jump_t = now_ms
        _side = '右' if d > 0 else '左'
        _hold = _move_vk in self._random_move_keys
        _debug_log("[爬梯·小地图·%s] 朝%s起跳 人梯X差%.1f 朝梯帧位移%.1f 朝梯键按住=%s(光点Y=%.0f):跳120,%dms后松左右按↑判后脑" % (
            '跑跳' if kind == 'run' else '直跳', _side, abs(d), vx, _hold, py, (100 if kind == 'run' else 50)))
        if kind == 'run':
            self._rlog("小地图跑跳上梯(朝%s差%.1f)" % (_side, abs(d)), log='behavior')
        return False
'''

NEW_REALIGN = '''    def _ladder_mm_realign(self, py, now_ms, why):
        """起跳后满窗没抓住后脑:回小地图goto走近再直跳。跑跳失败不占直跳轮次(只回goto,人已在1~6段靠近、且本把梯不再跑跳);
        直跳失败每轮+1,满LADDER_REALIGN_MAX_ROUNDS放弃回主线打怪(不发呆)。
        锁定梯id【保留】(同一把梯走近重试,不重选不晃);只清速度/停稳基线(prev_ad=None)逼goto重新采帧判跨线/停稳。"""
        for _vk in (VK_UP, VK_LEFT, VK_RIGHT):
            if _vk in self._random_move_keys:
                self._key_up(_vk)
        if '跑跳' not in str(why):
            self._ladder_realign_round = getattr(self, '_ladder_realign_round', 0) + 1
            if self._ladder_realign_round >= LADDER_REALIGN_MAX_ROUNDS:
                _debug_log("[爬梯·小地图] 直跳%d次仍没抓住(%s,抓梯窗后脑峰值%.2f),放弃回主线打怪" % (
                    LADDER_REALIGN_MAX_ROUNDS, why, getattr(self, '_ladder_back_peak', 0.0)))
                self._rlog("小地图直跳%d次没挂上梯,回主线打怪" % LADDER_REALIGN_MAX_ROUNDS, LOG_RED, log='exception')
                self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
                self._reset_climb(); self._decide_climb_fail_action()
                return False
        else:
            _debug_log("[爬梯·小地图] 跑跳没抓住(%s,抓梯窗后脑峰值%.2f),回goto走近再直跳(不占直跳轮次)" % (
                why, getattr(self, '_ladder_back_peak', 0.0)))
        self._ladder_run_jumped = True
        self._ladder_vert_jumped = False
        self._ladder_jump_phase = 'mm_goto'
        self._ladder_post_jump_step = None
        self._ladder_mm_fine_phase = ''
        self._ladder_mm_fine_t = 0
        self._ladder_mm_fine_round = 0
        # 同梯重试:锁id保留,只重置速度/停稳基线与候选(候选对齐到已锁id),不重选梯
        self._ladder_mm_prev_px = None
        self._ladder_mm_prev_ad = None
        self._ladder_mm_approach_streak = 0
        self._ladder_mm_still_frames = 0
        self._ladder_mm_cand_id = getattr(self, '_ladder_mm_lock_id', None)
        self._ladder_mm_cand_streak = LADDER_MM_LOCK_FRAMES
        return False
'''

NEW_FINE = '''    def _ladder_mm_fine_tick(self, d, ad, vl, py, now_ms, jump_key):
        """小地图微调(vl<ad<=LADDER_MM_FINE_DX):点动 走MOVE_MS->抬键停GAP_MS检测,最多FINE_MAX拍;
        gap停稳后ad<=vl=微调到位【直接原地直跳】(少回goto一次往返;微调是60ms小步点动、残余惯性极小);
        拍满仍ad>vl=对不齐,放弃回主线打怪(不发呆)。"""
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
                self._ladder_mm_fine_phase = ''
                return self._ladder_mm_start_jump('vert', d, py, now_ms, jump_key)  # 微调到位直接直跳
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
'''

NEW_GOTO = '''    def _ladder_mm_goto_tick(self, px, py, now_ms, jump_key):
        """上行小地图【锁梯→走近→带速跑跳/停稳直跳】(用户2026-09-21定稿,取代屏幕白框approach/align/伺服;坐标全=小地图光点)。
        锁梯:未锁每帧_pick,连续LADDER_MM_LOCK_FRAMES拍同一条录制梯(id相同)才锁定+钉端点;锁后整条上梯(跑跳/realign/直跳)不重选,
             治"人移动时怪侧side_sign翻向→每帧换梯→左右晃";锁的梯从录制表消失才解锁重选;候选id抖动超LOCK_FORCE_MS按当前最近强锁(不呆住)。
        起跳(距离+速度,修旧1px跑跳窗在~21fps下必被一帧跨过、以及零速原地跳):
          ·跑跳=上一拍ad>rj、本拍ad<=rj的跨线下降沿 且 连续朝梯 且 本拍仍带速(朝梯帧位移>=MOVING_DX),不松方向键带速跳(每把梯一次);
          ·直跳=ad<=vl 且 连续STILL_FRAMES拍帧间位移<=STILL_DX(真停稳,不在滑行中跳);
          ·fine=vl<ad<=FINE_DX点动走停;ad<=vl但还在滑=松键等停不跳;其余walk持续按住朝梯走。选不到梯NOPICK超时放弃回主线,不发呆。"""
        ladders = getattr(self, 'ladders', None) or []
        # ---- 1) 取已锁梯;未锁则本帧候选+连续拍确认 ----
        ld = None
        lock_id = getattr(self, '_ladder_mm_lock_id', None)
        if lock_id is not None:
            for _x in ladders:
                _id = _x.get('id', (_x['x'], _x['y_top'], _x['y_bottom']))
                if _id == lock_id:
                    ld = _x
                    break
            if ld is None:
                self._ladder_mm_lock_id = None
                self._ladder_mm_cand_id = None
                self._ladder_mm_cand_streak = 0
                _debug_log("[选梯·小地图] 已锁梯id=%s不在录制表(被删/重载),解锁重选" % str(lock_id))
        if ld is None:
            side_sign = None
            _fx = getattr(self, '_ladder_target_mon_x', None)
            _sp = self._player_screen_pos
            if _fx is not None and _sp is not None:
                _dsx = float(_fx) - float(_sp[0])
                if abs(_dsx) > 1.0:
                    side_sign = 1 if _dsx > 0 else -1
            picked = self._pick_ladder_minimap(ladders, px, py, +1, side_sign)
            self._ladder_mm_prev_px = px    # 未锁期间不走向/不判速度,基线随帧刷新
            self._ladder_mm_prev_ad = None
            if picked is None:
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                self._ladder_mm_cand_id = None; self._ladder_mm_cand_streak = 0
                if self._ladder_mm_no_pick_t == 0:
                    self._ladder_mm_no_pick_t = now_ms
                elif now_ms - self._ladder_mm_no_pick_t >= LADDER_MM_NOPICK_TIMEOUT_MS:
                    _debug_log("[选梯·小地图] 光点(%.0f,%.0f)连续%.0fms无合格录制梯(X±%d/梯底Y差≤%d/上通),放弃回主线打怪" % (
                        px, py, LADDER_MM_NOPICK_TIMEOUT_MS, LADDER_MM_X_HALF, LADDER_MM_END_TOL))
                    self._rlog("小地图找不到够得着的梯,回主线打怪", LOG_RED, log='exception')
                    self._reset_climb(); self._decide_climb_fail_action()
                return False
            self._ladder_mm_no_pick_t = 0
            cid = picked.get('id', (picked['x'], picked['y_top'], picked['y_bottom']))
            if cid == getattr(self, '_ladder_mm_cand_id', None):
                self._ladder_mm_cand_streak += 1
            else:
                self._ladder_mm_cand_id = cid; self._ladder_mm_cand_streak = 1
            if self._ladder_mm_pick_t == 0:
                self._ladder_mm_pick_t = now_ms
            if self._ladder_mm_cand_streak >= LADDER_MM_LOCK_FRAMES:
                ld = picked; self._ladder_mm_lock_id = cid; self._ladder_mm_pin(ld)
                _debug_log("[选梯·小地图] 连续%d拍同梯,锁定梯id=%s x=%.0f top=%.0f bot=%.0f(光点%.0f,%.0f),整条上梯不重选" % (
                    LADDER_MM_LOCK_FRAMES, cid, ld['x'], ld['y_top'], ld['y_bottom'], px, py))
                self._rlog("锁定小地图梯id=%s" % str(cid), log='behavior')
            elif now_ms - self._ladder_mm_pick_t >= LADDER_MM_LOCK_FORCE_MS:
                ld = picked; self._ladder_mm_lock_id = cid; self._ladder_mm_pin(ld)
                _debug_log("[选梯·小地图] 候选抖动%.0fms未稳定,按当前最近强锁梯id=%s(不呆住)" % (LADDER_MM_LOCK_FORCE_MS, cid))
            else:
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)  # 未锁不走向,等下拍确认
                return False
        # ---- 2) 已锁:算人梯差/朝梯速度/停稳 ----
        d = float(ld['x']) - float(px)
        ad = abs(d)
        _right = d > 0
        rj = int(self._ladder_jump_cfg.get('rj_r' if _right else 'rj_l', LADDER_MM_RUNJUMP_DEFAULT))
        vl = int(self._ladder_jump_cfg.get('vl_r' if _right else 'vl_l', LADDER_MM_VERT_DEFAULT))
        _prev_px = getattr(self, '_ladder_mm_prev_px', None)
        dpx = (px - _prev_px) if _prev_px is not None else 0.0
        approach = (1.0 if _right else -1.0) * dpx    # >0=朝梯移动
        if approach > 0:
            self._ladder_mm_approach_streak += 1
        else:
            self._ladder_mm_approach_streak = 0
        if abs(dpx) <= LADDER_MM_STILL_DX:
            self._ladder_mm_still_frames += 1
        else:
            self._ladder_mm_still_frames = 0
        prev_ad = getattr(self, '_ladder_mm_prev_ad', None)
        # ---- 3) 跑跳:跨rj下降沿+连续朝梯+本拍带速(每把梯一次;高速一帧从rj外冲到ad<=vl也在此捕获) ----
        _cross = (prev_ad is not None and prev_ad > rj and ad <= rj)
        if (not getattr(self, '_ladder_run_jumped', False)
                and self._ladder_mm_approach_streak >= LADDER_MM_APPROACH_FRAMES
                and approach >= LADDER_MM_MOVING_DX and (_cross or ad <= rj)):
            self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return self._ladder_mm_start_jump('run', d, py, now_ms, jump_key, vx=approach)
        # ---- 4) 直跳:ad<=vl 且连续停稳 ----
        if ad <= vl and self._ladder_mm_still_frames >= LADDER_MM_STILL_FRAMES:
            self._ladder_mm_fine_phase = ''
            self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return self._ladder_mm_start_jump('vert', d, py, now_ms, jump_key, vx=approach)
        band = self._ladder_mm_band(ad, rj, vl)
        if band == 'fine':
            self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return self._ladder_mm_fine_tick(d, ad, vl, py, now_ms, jump_key)
        if ad <= vl:
            # 进了直跳距离但还在滑(高速冲到正下)/停稳帧不足:松键等停,不零速原地跳
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return False
        if self._ladder_mm_fine_phase:
            self._ladder_mm_fine_phase = ''
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
        # ---- 5) walk 持续按住朝梯走 ----
        self._hold_toward_ladder(d)
        self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
        return False
'''

NEW_POST = '''    def _ladder_post_jump_process(self, py, now_ms):
        """起跳后统一流程(2026-09-21小地图定稿;抓住判据=【后脑勺】,旧"光点Y变小"已删):
        delay1:跑跳跳后100ms/直跳50ms,到点_release_move_conflicts松左右(跑跳这100ms朝梯键继续按住=带速飞行)+松↓按↑→check;
        check:抓梯窗LADDER_GRAB_WINDOW_MS内只看后脑,连续BACK_GRAB_FRAMES帧看到=挂上梯,立刻_grab_to_climbing(跑跳/直跳统一,提前于满窗);
               窗内记录后脑峰值分数(标定0.55阈值用,纯埋点);满窗仍无后脑=没抓住,松↑进_ladder_mm_realign(跑跳不占轮次回goto、直跳累计满轮放弃)。
        到顶判据在climbing段:后脑连续BACK_TOP_LOST_MS消失为主、小地图光点重合梯端兜底、录梯时长+2s总超时保命。"""
        step = getattr(self, '_ladder_post_jump_step', 'delay1')
        start_t = getattr(self, '_ladder_post_jump_t', now_ms)

        if step == 'delay1':
            _is_run = getattr(self, '_ladder_run_jumped', False)
            _up_delay = 100 if _is_run else 50
            if now_ms - start_t >= _up_delay:
                self._release_move_conflicts()  # 跑跳在此才松朝梯方向键(已带速腾空100ms);直跳起跳当帧已松,这里幂等
                if VK_DOWN in self._random_move_keys:
                    self._key_up(VK_DOWN)  # 上下互斥,再松一次↓
                if VK_UP not in self._random_move_keys:
                    self._key_down(VK_UP)
                self._ladder_post_jump_step = 'check'
                self._ladder_post_jump_t = now_ms
                if not self._climb_start_y:
                    self._climb_start_y = py
                _debug_log("[爬梯] %s起跳后%dms松左右按↑(光点Y=%.0f),抓梯窗%dms只看后脑" % (
                    '跑跳' if _is_run else '直跳', _up_delay, py, LADDER_GRAB_WINDOW_MS))
            return False

        # check【抓住判据·后脑】:连续BACK_GRAB_FRAMES帧看到=挂上梯(不可逆,提前转climbing);满窗无后脑=没抓住进realign
        _bv, _bs = self._back_head_visible()
        if _bs and _bs > getattr(self, '_ladder_back_peak', 0.0):
            self._ladder_back_peak = _bs
        if _bv:
            self._ladder_back_seen_frames += 1
            if self._ladder_back_seen_frames >= BACK_GRAB_FRAMES:
                _via = '跑跳' if getattr(self, '_ladder_run_jumped', False) else '直跳'
                self._grab_to_climbing(_via, py, now_ms, _bs)
                return False
        else:
            self._ladder_back_seen_frames = 0
        _el = now_ms - start_t
        if _el < LADDER_GRAB_WINDOW_MS:
            if VK_UP not in self._random_move_keys:
                self._key_down(VK_UP)  # 抓梯窗内还没看到后脑:继续按住↑等
            return False
        # 满窗仍无后脑=没抓住,松↑进校准(跑跳回goto走近不占轮次、直跳累计满LADDER_REALIGN_MAX_ROUNDS回主线)
        if VK_UP in self._random_move_keys:
            self._key_up(VK_UP)
        _is_run = getattr(self, '_ladder_run_jumped', False)
        _debug_log("[爬梯·小地图] %s%dms后仍看不到后脑(窗内峰值%.2f)=没抓住,进校准" % (
            '跑跳' if _is_run else '直跳', _el, getattr(self, '_ladder_back_peak', 0.0)))
        return self._ladder_mm_realign(py, now_ms, ("跑跳满窗没后脑" if _is_run else "直跳满窗没后脑"))
'''

NEW_FUNCS = {
    '_ladder_mm_band': NEW_BAND,
    '_ladder_mm_start_jump': NEW_START_JUMP,
    '_ladder_mm_realign': NEW_REALIGN,
    '_ladder_mm_fine_tick': NEW_FINE,
    '_ladder_mm_goto_tick': NEW_GOTO,
    '_ladder_post_jump_process': NEW_POST,
}

# ---------- ast 定位整函数区间(含上一行@staticmethod),从后往前替换 ----------
tree = ast.parse(src)
targets = []
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in NEW_FUNCS:
        start0 = node.lineno - 1
        # 上扩装饰器
        lines_tmp = src.splitlines()
        k = node.lineno - 2  # 0基、def上一行
        while k >= 0 and lines_tmp[k].lstrip().startswith('@'):
            start0 = k
            k -= 1
        end0 = node.end_lineno  # 切片右界(1基end_lineno)=保留到该0基行
        targets.append((start0, end0, node.name))
missing = set(NEW_FUNCS) - {t[2] for t in targets}
if missing:
    print('!! 未定位到函数:', missing); sys.exit(1)

lines = src.splitlines(keepends=True)
for start0, end0, name in sorted(targets, key=lambda t: -t[0]):
    new_lines = [ln + '\r\n' for ln in NEW_FUNCS[name].split('\n')]
    if new_lines and new_lines[-1] == '\r\n':
        new_lines.pop()  # split末尾空串产生的孤立换行
    lines[start0:end0] = new_lines
src2 = ''.join(lines)

def repl(text, old, new, cnt=1):
    n = text.count(old)
    assert n == cnt, '锚点命中%d(应%d): %r' % (n, cnt, old[:60])
    return text.replace(old, new)

# ---------- 新增常量(CRLF) ----------
anchor_const = "LADDER_MM_NOPICK_TIMEOUT_MS = 1500  # 上行连续多久选不到合格录制梯->放弃回主线打怪(防发呆)"
add_const = anchor_const + "\r\n" + "\r\n".join([
    "LADDER_MM_LOCK_FRAMES = 2        # 锁梯:连续几拍选到同一条录制梯(id相同)才锁定,锁后整条上梯不重选(治怪侧side_sign翻向导致左右晃)",
    "LADDER_MM_LOCK_FORCE_MS = 300    # 候选梯id抖动超过此时仍未2拍稳定=按当前最近强锁(防侧别反复横跳锁不定而呆住)",
    "LADDER_MM_MOVING_DX = 1.0        # 跑跳带速:朝梯相邻帧位移>=此值=仍在移动(小地图px,真机帧位移标定,先给1)",
    "LADDER_MM_STILL_DX = 1.0         # 直跳停稳:相邻帧位移<=此值=不滑(小地图px,真机站定抖动标定,先给1)",
    "LADDER_MM_STILL_FRAMES = 2       # 直跳需连续几拍停稳才原地跳(不在滑行中零速跳)",
    "LADDER_MM_APPROACH_FRAMES = 2    # 跑跳需连续几拍朝梯移动才认(防单帧光点抖动误触发)",
])
src2 = repl(src2, anchor_const, add_const)

# ---------- 删除跑跳专用窗常量(run_hold死分支已随post整换删除,全仓无引用) 按行名过滤 ----------
_ls = src2.splitlines(keepends=True)
_ls2 = [ln for ln in _ls if not ln.lstrip().startswith('RUNJUMP_GRAB_WINDOW_MS = ')]
assert len(_ls) - len(_ls2) == 1, 'RUNJUMP_GRAB_WINDOW_MS 删除行数=%d(应1)' % (len(_ls) - len(_ls2))
src2 = ''.join(_ls2)

# ---------- reset 新增字段(锚 reset 带注释那行,唯一) ----------
anchor_reset = "        self._ladder_mm_no_pick_t = 0        # 连续选不到合格录制梯计时(0=本帧选到)"
add_reset = anchor_reset + "\r\n" + "\r\n".join([
    "        self._ladder_mm_lock_id = None      # 已锁定录制梯id(连续2拍同梯锁定,整条上梯不重选;None=未锁)",
    "        self._ladder_mm_cand_id = None      # 当前候选梯id(锁梯2拍确认用)",
    "        self._ladder_mm_cand_streak = 0     # 候选梯连续拍数",
    "        self._ladder_mm_pick_t = 0          # 本把梯首次选到时刻ms(候选抖动强锁宽限)",
    "        self._ladder_mm_prev_px = None      # 上一拍光点X(算朝梯帧位移/停稳)",
    "        self._ladder_mm_prev_ad = None      # 上一拍人梯|X差|(跑跳跨rj下降沿判定)",
    "        self._ladder_mm_approach_streak = 0 # 连续朝梯移动拍数",
    "        self._ladder_mm_still_frames = 0    # 连续停稳拍数(直跳门槛)",
    "        self._ladder_back_peak = 0.0        # 本次起跳抓梯窗内后脑分数峰值(标定0.55阈值,纯观测)",
])
src2 = repl(src2, anchor_reset, add_reset)

# ---------- 写回(保BOM+CRLF) ----------
with io.open(PATH, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(src2)
print('PATCH OK, funcs replaced:', sorted(NEW_FUNCS))
