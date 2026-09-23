# -*- coding: utf-8 -*-
import io
p=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s=io.open(p,'rb').read().decode('utf-8-sig').replace('\r\n','\n')

anchors=[]

# 锚1: 常量区——删 GOTO_END_TOL=14(错误复用源), 加 MIN_LEN / BAD_COOLDOWN
anchors.append(("常量",
"""LADDER_MM_END_TOL = 10      # 合格高度门:上行梯底y_bottom与光点Y差<=10(人跳起够得到底端)/下行梯顶y_top与光点Y差<=10
LADDER_MM_GOTO_END_TOL = 14    # 锁后对位/起跳前Y复核容差(比选梯10略宽,抗走动光点量化):上行|梯底y_bottom-光点Y|<=此值且梯身上通才继续,否则解锁重选(用户2026-09-22:锁后只看X会锁错梯空跳)
LADDER_MM_GOTO_UNLOCK_FRAMES = 2  # 锁后连续几帧Y不合格才解锁重选(与锁梯2帧对称,防光点单帧抖动误解锁)""",
"""LADDER_MM_END_TOL = 10      # 合格高度门:上行梯底y_bottom与光点Y差<=10(人跳起够得到底端)/下行梯顶y_top与光点Y差<=10
LADDER_MM_MIN_LEN = 5       # 录制梯最小梯身长度(y_bottom-y_top):数据里0/2/3px=起终点重合的误录噪点直接判否,真机可爬梯>=7(2026-09-22锁解永振根因之一)
LADDER_MM_BAD_COOLDOWN_MS = 2000  # 锁后Y复核否决的梯拉黑时长ms:本次上梯不再选它,逼改选别的合格梯或选空走NOPICK超时回主线,治锁-解永振呆住(2026-09-22)
LADDER_MM_GOTO_UNLOCK_FRAMES = 2  # 锁后连续几帧Y不合格才解锁重选(与锁梯2帧对称,防光点单帧抖动误解锁)"""))

# 锚2: 新增统一高度判定 staticmethod + _pick 签名加 bad_ids
anchors.append(("统一判定函数+签名",
"""    @staticmethod
    def _pick_ladder_minimap(ladders, dot_x, dot_y, cdir, side_sign):""",
"""    @staticmethod
    def _ladder_mm_height_ok(t, dot_y, cdir):
        \"\"\"小地图录制梯对当前光点是否"够得着端且梯身通向目标层"。选梯(_pick_ladder_minimap)与锁后复核
        (_ladder_mm_goto_tick)必须共用本函数、同一结果——旧版选梯容差10、锁后容差14两套门,真机出现"选时合格、
        锁后必挂"的锁-解永振(2026-09-22 debug.log:锁422/解锁420/回主线0,人物钉住不打怪)。坐标全=小地图块像素。
        梯身长度(y_bottom-y_top)<LADDER_MM_MIN_LEN=录制0/2/3px起终点重合噪点,直接否;上行梯底端贴光点且整把梯
        在人上方(y_top<=光点Y),下行梯顶端贴光点且整把梯在人下方(保留旧y_bottom>=光点Y+端容差,不改下行行为)。\"\"\"
        tt, tb, dy = float(t['y_top']), float(t['y_bottom']), float(dot_y)
        if (tb - tt) < LADDER_MM_MIN_LEN:
            return False
        if cdir is not None and cdir < 0:
            return abs(tt - dy) <= LADDER_MM_END_TOL and tb >= dy + LADDER_MM_END_TOL
        return abs(tb - dy) <= LADDER_MM_END_TOL and tt <= dy

    @staticmethod
    def _pick_ladder_minimap(ladders, dot_x, dot_y, cdir, side_sign, bad_ids=None):"""))

# 锚3: _pick docstring 高度门描述
anchors.append(("选梯docstring",
"""        规则:X带|梯x-光点x|<=LADDER_MM_X_HALF;高度门 上行|y_bottom-光点Y|<=END_TOL且梯身上通(y_top<=光点Y-END_TOL),""",
"""        规则:X带|梯x-光点x|<=LADDER_MM_X_HALF;高度门统一走_ladder_mm_height_ok(梯身长度>=LADDER_MM_MIN_LEN排0/2/3噪点;上行|y_bottom-光点Y|<=END_TOL且y_top<=光点Y),"""))

# 锚4: _ok 体改走统一判定 + bad 排除
anchors.append(("选梯_ok体",
"""        def _ok(t):
            tx, tt, tb = float(t['x']), float(t['y_top']), float(t['y_bottom'])
            if abs(tx - dx) > LADDER_MM_X_HALF:
                return False
            if cdir is not None and cdir < 0:
                return abs(tt - dy) <= LADDER_MM_END_TOL and tb >= dy + LADDER_MM_END_TOL
            return abs(tb - dy) <= LADDER_MM_END_TOL and tt <= dy - LADDER_MM_END_TOL""",
"""        def _ok(t):
            if abs(float(t['x']) - dx) > LADDER_MM_X_HALF:
                return False
            if bad_ids and t.get('id', (t['x'], t['y_top'], t['y_bottom'])) in bad_ids:
                return False
            return MinimapRouteRecorder._ladder_mm_height_ok(t, dy, cdir)"""))

# 锚5: goto_tick 选梯调用传拉黑集合
anchors.append(("选梯调用传bad",
"""            picked = self._pick_ladder_minimap(ladders, px, py, +1, side_sign)""",
"""            _bad_ids = {cid for cid, _exp in getattr(self, '_ladder_mm_bad', {}).items() if _exp > now_ms}
            picked = self._pick_ladder_minimap(ladders, px, py, +1, side_sign, bad_ids=_bad_ids)"""))

# 锚6: 锁后Y复核改统一判定 + 否决拉黑
anchors.append(("锁后复核",
"""        # 上行合格=梯底贴光点(容差GOTO_END_TOL,比选梯略宽抗量化)且梯身上通;连续GOTO_UNLOCK_FRAMES帧不合格才解锁,
        # 用最新光点重新过X+Y门选当前够得着的梯(选不到走NOPICK超时回主线);不足连续帧本帧不起跳/不走向,松键等下一帧复核。
        _goto_yb = float(ld['y_bottom']); _goto_yt = float(ld['y_top']); _goto_py = float(py)
        if (abs(_goto_yb - _goto_py) <= LADDER_MM_GOTO_END_TOL
                and _goto_yt <= _goto_py - LADDER_MM_GOTO_END_TOL):
            self._ladder_mm_ybad_streak = 0
        else:
            self._ladder_mm_ybad_streak = getattr(self, '_ladder_mm_ybad_streak', 0) + 1
            if self._ladder_mm_ybad_streak >= LADDER_MM_GOTO_UNLOCK_FRAMES:
                _debug_log("[选梯·小地图] 锁后Y不合格连续%d帧(梯底%.0f/梯顶%.0f/光点Y%.0f,|底-光|=%.0f 容差%d):这把已够不着底,解锁用最新光点重选" % (
                    LADDER_MM_GOTO_UNLOCK_FRAMES, _goto_yb, _goto_yt, _goto_py, abs(_goto_yb - _goto_py), LADDER_MM_GOTO_END_TOL))
                self._ladder_mm_lock_id = None
                self._ladder_mm_cand_id = None
                self._ladder_mm_cand_streak = 0
                self._ladder_mm_pick_t = 0
                self._ladder_mm_ybad_streak = 0
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            else:
                # 不足连续帧:松键停一拍等下一帧复核,绝不在错误Y上起跳
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return False""",
"""        # 合格判定与选梯共用_ladder_mm_height_ok同一套门(旧版选梯容差10/锁后容差14不一致,真机锁422解锁420、回主线0永振呆住)。
        # 连续GOTO_UNLOCK_FRAMES帧不合格:先把这把梯拉黑BAD_COOLDOWN_MS(本次上梯不再选,逼选别的合格梯或选空走NOPICK回主线),
        # 再解锁用最新光点重选;不足连续帧本帧不起跳/不走向,松键等下一帧复核。
        _goto_yb = float(ld['y_bottom']); _goto_yt = float(ld['y_top']); _goto_py = float(py); _goto_len = _goto_yb - _goto_yt
        if self._ladder_mm_height_ok(ld, _goto_py, +1):
            self._ladder_mm_ybad_streak = 0
        else:
            self._ladder_mm_ybad_streak = getattr(self, '_ladder_mm_ybad_streak', 0) + 1
            if self._ladder_mm_ybad_streak >= LADDER_MM_GOTO_UNLOCK_FRAMES:
                _debug_log("[选梯·小地图] 锁后Y不合格连续%d帧(梯底%.0f/梯顶%.0f/梯长%.0f/光点Y%.0f,|底-光|=%.0f 容差%d 最小梯长%d):这把够不着,拉黑%.0fs后用最新光点重选" % (
                    LADDER_MM_GOTO_UNLOCK_FRAMES, _goto_yb, _goto_yt, _goto_len, _goto_py, abs(_goto_yb - _goto_py),
                    LADDER_MM_END_TOL, LADDER_MM_MIN_LEN, LADDER_MM_BAD_COOLDOWN_MS / 1000.0))
                self._ladder_mm_bad[lock_id] = now_ms + LADDER_MM_BAD_COOLDOWN_MS
                self._ladder_mm_lock_id = None
                self._ladder_mm_cand_id = None
                self._ladder_mm_cand_streak = 0
                self._ladder_mm_pick_t = 0
                self._ladder_mm_ybad_streak = 0
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            else:
                # 不足连续帧:松键停一拍等下一帧复核,绝不在错误Y上起跳
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                self._ladder_mm_prev_px = px; self._ladder_mm_prev_ad = ad
            return False"""))

# 锚7: 字段初始化加拉黑表
anchors.append(("字段初始化bad",
"""        self._ladder_mm_ybad_streak = 0    # 锁后梯底Y不合格连续帧(出梯/换梯清零,用户2026-09-22)""",
"""        self._ladder_mm_ybad_streak = 0    # 锁后梯底Y不合格连续帧(出梯/换梯清零,用户2026-09-22)
        self._ladder_mm_bad = {}          # 锁后Y否决梯拉黑表{梯id:拉黑到期ms}(仅本次上梯有效,进上梯清空;治锁-解永振呆住,2026-09-22)"""))

# 锚8: 进上梯 mm 重置段补齐锁/候选/拉黑干净进场
anchors.append(("进上梯重置",
"""        self._ladder_mm_fine_phase = ''
        self._ladder_mm_fine_t = 0
        self._ladder_mm_fine_round = 0
        self._ladder_mm_no_pick_t = 0
        self._ladder_realign_round = 0""",
"""        self._ladder_mm_fine_phase = ''
        self._ladder_mm_fine_t = 0
        self._ladder_mm_fine_round = 0
        self._ladder_mm_no_pick_t = 0
        self._ladder_mm_lock_id = None    # 每次上梯重新选梯,不带入上一把锁(进场干净,2026-09-22)
        self._ladder_mm_cand_id = None
        self._ladder_mm_cand_streak = 0
        self._ladder_mm_pick_t = 0
        self._ladder_mm_ybad_streak = 0
        self._ladder_mm_bad = {}          # 清空上一把拉黑表
        self._ladder_realign_round = 0"""))

for name, old, new in anchors:
    c = s.count(old)
    assert c == 1, "锚点[%s]命中%d次(应为1),终止不写盘" % (name, c)
    s = s.replace(old, new)
    print("OK 锚点", name)

# 写回(utf-8-sig BOM + CRLF)
io.open(p,'w',encoding='utf-8-sig',newline='').write(s.replace('\n','\r\n'))
print("已写盘")
# 残留检查
for bad in ['LADDER_MM_GOTO_END_TOL','tt <= dy - LADDER_MM_END_TOL','tt<=dy-END_TOL']:
    print("残留", bad, ":", s.count(bad))
