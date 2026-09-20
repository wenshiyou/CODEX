# -*- coding: utf-8 -*-
"""
2026-09-20 原子修复(用户定稿, 治"到顶后脑误匹配把人物坐标拽飞→B误判下层→无锁空跳下台/锁451px远梯"):
1 偏移学习姿势门控: back只在真爬梯climbing学、face只在平地none学(根治off_back从240被平地误匹配污染成~14)
2 恢复role_recognize.json被污染的back固化偏移(37,138)->(13,240)
3 兜底锚点(脸/后脑/宠物)跳变门收紧到80px且全图帧也生效(name仍250/强匹配0.75豁免)
4 爬梯硬态(to_ladder/climbing)+跨层结束800ms窗 定位只认人名, 脸/后脑/宠物不兜底(后脑到顶检测独立不受影响)
5 发起跨层(上梯/下跳/选台/walk)必须坐标源=name, 否则本帧不跨层(普通打/追同层不受影响)
6 上行建锁选梯 x_half 从寻怪范围_far_x(1300)收紧到LADDER_DIR_X_HALF(300): 锁梯必须人梯|X差|<=300
7 锁定梯子后备选白框清空、只留红框, 出梯/掉锁自动恢复(只改显示层, 内部跟踪读全量缓存不受影响)
8 上/下cross决策 print->_debug_log 进文件(带人物怪坐标+坐标源), 杜绝静默下跳
每处 assert 命中唯一, 全过才写回; maple 保 BOM/LF, json 保留原BOM。
"""
import os, json

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(ROOT, "maple_route_ui.py")
JSP = os.path.join(ROOT, "data", "role_recognize", "role_recognize.json")

# ---------- maple_route_ui.py ----------
raw = open(PY, "rb").read()
bom = raw.startswith(b"\xef\xbb\xbf")
s = raw.decode("utf-8-sig")
orig = s
def rep(old, new, tag):
    global s
    n = s.count(old)
    assert n == 1, "[%s] 命中%d次(应为1), 中止" % (tag, n)
    s = s.replace(old, new)
    print("[OK]", tag)

# 常量1: 兜底锚点合法跳变阈值
rep(
    'ROLE_OFF_LEARN_THR = 0.45  # 脸/后脑学"→人名基点"偏移的最低分(用户2026-09-18):同帧人名已过阈锚定真人,脸/后脑有0.45以上可信命中即可量几何差,不必也过定位阈值0.62(实测脸分常0.56~0.62)',
    'ROLE_OFF_LEARN_THR = 0.45  # 脸/后脑学"→人名基点"偏移的最低分(用户2026-09-18):同帧人名已过阈锚定真人,脸/后脑有0.45以上可信命中即可量几何差,不必也过定位阈值0.62(实测脸分常0.56~0.62)\n'
    'AUX_ANCHOR_MAX_MOVE = 80   # 脸/后脑/宠物这些【兜底锚点】映射点相对上一可信基点的最大合法跳变px(用户2026-09-20):兜底锚点误匹配多,不能像人名那样允许maxmove=250的瞬移,>80且弱匹配(<0.75)即当误匹配丢弃,全图重搜帧也生效',
    "常量AUX_ANCHOR_MAX_MOVE")

# 常量2: 跨层结束后只认人名短窗
rep(
    'BACK_ON_LADDER_THR = 0.55       # 后脑勺"在梯子上"分数阈(定位thr约0.62,在梯判定单独0.55;真机看[爬梯·后脑]日志分数再微调)',
    'BACK_ON_LADDER_THR = 0.55       # 后脑勺"在梯子上"分数阈(定位thr约0.62,在梯判定单独0.55;真机看[爬梯·后脑]日志分数再微调)\n'
    'NAME_ONLY_AFTER_CLIMB_MS = 800  # 跨层结束(到顶/落地/失败回主线)后多少ms内人物定位只认人名(用户2026-09-20):翻台瞬间脸/后脑/宠物最易误匹配把坐标拽飞,短窗只认最稳的人名',
    "常量NAME_ONLY_AFTER_CLIMB_MS")

# _reset_climb: 跨层结束开 name-only 短窗
rep(
    '        self._climb_state = "none"\n'
    '        self._ladder_precise_mode = False   # 退出上梯:检测线程恢复正常120ms全检测档(用户2026-09-10方案B)',
    '        self._climb_state = "none"\n'
    '        self._name_only_until = time.time() * 1000 + NAME_ONLY_AFTER_CLIMB_MS  # 跨层结束短窗只认人名,防翻台锚点误匹配拽飞坐标(用户2026-09-20)\n'
    '        self._ladder_precise_mode = False   # 退出上梯:检测线程恢复正常120ms全检测档(用户2026-09-10方案B)',
    "reset_climb设name-only窗")

# 改动4: 仲裁只认name(爬梯硬态/到顶窗)
rep(
    '        # 定位仲裁:人名优先;人名丢了用脸/后脑里分高者兜底(谁分高谁更可能是真角色),不让定位框丢\n'
    '        _nv = got.get("name")\n'
    '        if _nv is not None and _nv[0] >= thr:\n'
    '            _cand = [("name", _nv)]\n'
    '        else:\n'
    '            # 人名丢→脸/后脑/宠物名里谁过阈且分最高谁兜底(宠物是最后一道,人名脸后脑都没时顶上)\n'
    '            _cand = sorted(((kk, got[kk]) for kk in _AUX if kk in got and got[kk][0] >= thr),\n'
    '                           key=lambda kv: -kv[1][0])',
    '        # 定位仲裁:人名优先;人名丢了用脸/后脑里分高者兜底(谁分高谁更可能是真角色),不让定位框丢\n'
    '        _nv = got.get("name")\n'
    '        # 爬梯硬态(to_ladder对位/climbing在爬)及跨层结束短窗只认人名(用户2026-09-20):这些姿势脸/后脑/宠物最易误匹配,\n'
    '        # 一旦兜底会把坐标拽飞(实测到顶后脑误命中把人X 953拽到1184→B误判下层、无锁空跳下台)。人名丢本帧_cand留空→返回None等下一帧;\n'
    '        # 后脑到顶检测_back_head_visible独立读_role_last_scores(照常写),不受此影响。\n'
    '        _name_only = (getattr(self, \'_climb_state\', \'none\') in (\'to_ladder\', \'climbing\')) \\\n'
    '            or (now < getattr(self, \'_name_only_until\', 0))\n'
    '        if _nv is not None and _nv[0] >= thr:\n'
    '            _cand = [("name", _nv)]\n'
    '        elif _name_only:\n'
    '            _cand = []\n'
    '        else:\n'
    '            # 人名丢→脸/后脑/宠物名里谁过阈且分最高谁兜底(宠物是最后一道,人名脸后脑都没时顶上)\n'
    '            _cand = sorted(((kk, got[kk]) for kk in _AUX if kk in got and got[kk][0] >= thr),\n'
    '                           key=lambda kv: -kv[1][0])',
    "仲裁硬态只认name")

# 改动1: 偏移学习姿势门控
rep(
    '        _nloc = _nv[1] if (_nv is not None and _nv[0] >= thr) else None\n'
    '        for _kk in ("face_r", "back"):\n'
    '            _g = got.get(_kk)\n'
    '            # 人名在(已锚定真人)时,脸/后脑只要有≥学习门限的可信命中(低于定位阈值0.62也可,实测脸分常0.56~0.62)就量"→人名"几何偏移,同帧人名兜底不怕量错\n'
    '            if _nloc is not None and _g is not None and _g[0] >= ROLE_OFF_LEARN_THR and _g[1] is not None:\n'
    '                _dx, _dy = _nloc[0] - _g[1][0], _nloc[1] - _g[1][1]\n'
    '                _o = tr.get("off_" + _kk)\n'
    '                if _o is None:\n'
    '                    tr["off_" + _kk] = [float(_dx), float(_dy)]; tr["off_n_" + _kk] = 1\n'
    '                else:  # EMA平滑,避免单帧抖动让基点飘\n'
    '                    _o[0] = _o[0] * 0.7 + _dx * 0.3; _o[1] = _o[1] * 0.7 + _dy * 0.3\n'
    '                    tr["off_n_" + _kk] = tr.get("off_n_" + _kk, 0) + 1',
    '        _nloc = _nv[1] if (_nv is not None and _nv[0] >= thr) else None\n'
    '        # 偏移学习姿势门控(用户2026-09-20,根治off_back被平地误匹配从固化240污染成~14、到顶坐标飞到1184):\n'
    '        # 后脑back只在人物真在梯子上爬(_climb_state==climbing,后脑姿势真实)才学"→人名"偏移;平地/到顶/特效帧后脑在别处误匹配绝不学。\n'
    '        # 脸face_r只在非爬梯硬态(climb_state==none,平地打怪脸几何稳定)学;爬梯/下跳姿势脸会变形不学。\n'
    '        _climb_st_learn = getattr(self, \'_climb_state\', \'none\')\n'
    '        _learn_anchor_on = {"face_r": (_climb_st_learn == "none"),\n'
    '                            "back": (_climb_st_learn == "climbing")}\n'
    '        for _kk in ("face_r", "back"):\n'
    '            _g = got.get(_kk)\n'
    '            # 人名在(已锚定真人)+姿势门控通过时,锚点有≥学习门限可信命中才量"→人名"几何偏移\n'
    '            if (_nloc is not None and _g is not None and _g[0] >= ROLE_OFF_LEARN_THR and _g[1] is not None\n'
    '                    and _learn_anchor_on.get(_kk, False)):\n'
    '                _dx, _dy = _nloc[0] - _g[1][0], _nloc[1] - _g[1][1]\n'
    '                _o = tr.get("off_" + _kk)\n'
    '                if _o is None:\n'
    '                    tr["off_" + _kk] = [float(_dx), float(_dy)]; tr["off_n_" + _kk] = 1\n'
    '                else:  # EMA平滑,避免单帧抖动让基点飘\n'
    '                    _o[0] = _o[0] * 0.7 + _dx * 0.3; _o[1] = _o[1] * 0.7 + _dy * 0.3\n'
    '                    tr["off_n_" + _kk] = tr.get("off_n_" + _kk, 0) + 1',
    "偏移学习姿势门控")

# 改动3: 兜底锚点跳变门收紧+全图生效
rep(
    '            # 局部窗内离上一基点跳变>maxmove:弱匹配(<0.75)当误匹配丢弃;≥0.75强匹配=合法瞬移直接采信(背景假分到不了0.75)\n'
    '            if last is not None and not need_full \\\n'
    '                    and np.hypot(_bx - last[0], _by - last[1]) > maxmove and _pv[0] < 0.75:\n'
    '                continue\n'
    '            _pick = (_pk, _pv, _bx, _by); break',
    '            # 跳变门(用户2026-09-20收紧治兜底锚点拽飞):人名name保留原规则(局部窗跳变>maxmove且弱匹配<0.75才丢,全图重搜/强匹配=合法瞬移放行);\n'
    '            # 脸/后脑/宠物兜底锚点误匹配多,用独立小阈值AUX_ANCHOR_MAX_MOVE(80px)且【不分局部/全图帧都查】(全图重搜也不许兜底锚点一帧瞬移>80),仅≥0.75强匹配放行。\n'
    '            if last is not None and _pv[0] < 0.75:\n'
    '                _move_lim = maxmove if _pk == "name" else AUX_ANCHOR_MAX_MOVE\n'
    '                if np.hypot(_bx - last[0], _by - last[1]) > _move_lim and (_pk != "name" or not need_full):\n'
    '                    continue\n'
    '            _pick = (_pk, _pv, _bx, _by); break',
    "兜底锚点跳变门收紧")

# 改动7: 锁定后清备选白框
rep(
    '            # 全部梯子白框都下发显示(不隐藏/不禁任何候选);选中那把另由 ladder_sel 红框标出(用户2026-09-15:不能把别的梯禁掉)\n'
    '            self._monster_overlay_data["ladder_marks"] = [(c[0], c[1], (c[3] if len(c) > 3 else None)) for c in self._lad_marks_cache]  # 下发(cx,cy,模板序号)',
    '            # 白框显示(用户2026-09-20):未锁定/停止态下发全部候选(停止态靠全白框检查检测质量);一旦锁定某把梯(_ladder_lock非空),\n'
    '            # 备选白框全部清空、屏幕只留 ladder_sel 红框(避免多把白框干扰/像另一把还锁着);出梯/掉锁 _ladder_lock 回None即恢复全白框重选。\n'
    '            # 只改显示层:内部跟踪仍直接读 _lad_marks_cache 全量数据,不受影响。\n'
    '            if self._running and getattr(self, \'_ladder_lock\', None) is not None:\n'
    '                self._monster_overlay_data["ladder_marks"] = []\n'
    '            else:\n'
    '                self._monster_overlay_data["ladder_marks"] = [(c[0], c[1], (c[3] if len(c) > 3 else None)) for c in self._lad_marks_cache]  # 下发(cx,cy,模板序号)',
    "锁定后清备选白框")

# 改动6: 上行建锁X半宽收紧到300
rep(
    '                                    else:\n'
    '                                        _pick_l, _pick_reason, _db_band = self._dir_band_pick_ladder(\n'
    '                                            _half, _psx, _psy, _cdir, _tmox,\n'
    '                                            x_half=_far_x, y_far=_far_yu, y_near=0)',
    '                                    else:\n'
    '                                        _pick_l, _pick_reason, _db_band = self._dir_band_pick_ladder(\n'
    '                                            _half, _psx, _psy, _cdir, _tmox,\n'
    '                                            x_half=LADDER_DIR_X_HALF, y_far=_far_yu, y_near=0)  # 锁梯必须人梯|X差|<=300(用户2026-09-20);原_far_x=1300会锁到离人451够不着的远梯',
    "上行建锁X硬门300")

# 改动5: 跨层发起必须name坐标
rep(
    '        if not self._player_map_pos or not self._player_screen_pos:\n'
    '            self._trans_stall_diag(\'no_pos(人物小地图/屏幕坐标缺失,多为人物特征没匹配上)\', now,\n'
    '                                   map_pos=self._player_map_pos, screen_pos=self._player_screen_pos)\n'
    '            return False',
    '        if not self._player_map_pos or not self._player_screen_pos:\n'
    '            self._trans_stall_diag(\'no_pos(人物小地图/屏幕坐标缺失,多为人物特征没匹配上)\', now,\n'
    '                                   map_pos=self._player_map_pos, screen_pos=self._player_screen_pos)\n'
    '            return False\n'
    '        # 跨层(上梯/下跳/选台/walk)是不可逆大动作,只准人名name坐标驱动(用户2026-09-20):脸/后脑/宠物兜底坐标可能误匹配偏几十~几百px,\n'
    '        # 会把同层怪dy算反→误判下层、无锁空跳下台。坐标源不是name本帧不跨层(普通打/追同层怪不受影响),松手等下一帧人名。\n'
    '        if getattr(self, \'_role_pos_src\', \'name\') != \'name\':\n'
    '            self._trans_stall_diag(\'cross_wait_name(坐标源=%s非人名,本帧不跨层防误跳)\' % getattr(self, \'_role_pos_src\', \'?\'), now)\n'
    '            self._release_move_conflicts()\n'
    '            return False',
    "跨层必须name坐标")

# 改动8: 上下cross决策 print->_debug_log
rep(
    '            if going_up:\n'
    '                self._enter_to_ladder_up(mpx, mpy, now, fx, fy)  # fx,fy=目标怪屏幕坐标,冻结作"怪→梯→人两段总距离最短"选梯固定参照\n'
    '                print("[跨层] 上层怪(屏幕人Y%.0f 怪Y%.0f),进纯屏幕上梯段" % (spy, fy))\n'
    '            else:\n'
    '                self._reset_climb()\n'
    '                self._enter_descend(mpx, mpy + 1, mpx, mpy, now)  # 横跳下台;方式一不用target值,仅表方向向下\n'
    '                print("[跨层] 下层怪(屏幕人Y%.0f 怪Y%.0f),进descend横跳段" % (spy, fy))',
    '            if going_up:\n'
    '                self._enter_to_ladder_up(mpx, mpy, now, fx, fy)  # fx,fy=目标怪屏幕坐标,冻结作"怪→梯→人两段总距离最短"选梯固定参照\n'
    '                _debug_log("[跨层] 上层怪 人=(%.0f,%.0f) 怪=(%.0f,%.0f) 源=%s,进纯屏幕上梯段" % (spx, spy, fx, fy, getattr(self, \'_role_pos_src\', \'?\')))\n'
    '            else:\n'
    '                self._reset_climb()\n'
    '                self._enter_descend(mpx, mpy + 1, mpx, mpy, now)  # 横跳下台;方式一不用target值,仅表方向向下\n'
    '                _debug_log("[跨层] 下层怪 人=(%.0f,%.0f) 怪=(%.0f,%.0f) 源=%s,进descend横跳段" % (spx, spy, fx, fy, getattr(self, \'_role_pos_src\', \'?\')))',
    "cross决策print改日志")

assert s != orig
out = (b"\xef\xbb\xbf" if bom else b"") + s.replace("\r\n", "\n").encode("utf-8")
open(PY, "wb").write(out)
print("[DONE] maple 已写回, BOM=%s" % bom)

# ---------- role_recognize.json: 恢复被污染的 back 固化偏移 ----------
jraw = open(JSP, "rb").read()
jbom = jraw.startswith(b"\xef\xbb\xbf")
data = json.loads(jraw.decode("utf-8-sig"))
active = data.get("active", "c0")
ch = None
for c in data.get("characters", []):
    if c.get("id") == active:
        ch = c; break
if ch is None and data.get("characters"):
    ch = data["characters"][0]
ba = ch["anchors"]["back"]
before = (ba.get("off_x"), ba.get("off_y"))
ba["off_x"], ba["off_y"] = 13, 240   # 用户定稿固化值(被EMA平地误匹配污染成37,138;后脑只在爬梯学后会在240附近自校正)
jout = json.dumps(data, ensure_ascii=False, indent=2)
open(JSP, "wb").write((b"\xef\xbb\xbf" if jbom else b"") + jout.encode("utf-8"))
print("[DONE] role_recognize back off %s -> (13,240), json BOM=%s" % (before, jbom))
