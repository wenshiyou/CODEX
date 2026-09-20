# -*- coding: utf-8 -*-
"""
2026-09-20 原子改动(用户拍板"1"):
改动2 黑框降级: _dot_fallback_pos 映射点不再顶替人物坐标, 只当搜索范围中心; 新增 _research_anchor_around_dot
       在黑框ROI(LOCK_BOX_RX/RY)内复用 _role_match_in 重搜真锚点, 命中才回真人基点, 搜不到返回None(本帧跳过/不冻结)。
改动4 蓝框=面板技能范围: 中心只认真实锚点; ch=None(黑框/全丢帧)蓝框不画、特征识别不全屏乱匹配。
改动5a 下跳即清锁: _enter_descend 一进来当场清主线锁/B锁/决策包/红框缓存/梯锁身份, 不等落地reset(其有500ms冷却)。
附带  伺服直跳对齐 gate 从"挡dot"收紧为"只认name"(用户定稿:直跳只用人名中心X,没人名等下一帧)。
maple_route_ui.py 为 UTF-8 带 BOM、LF; 本脚本 utf-8-sig 读、utf-8-sig 写、newline='' 保 LF。
每处替换 assert 全文唯一(count==1), 任一不符则抛错、不写回。
"""
import io, sys

PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"

with io.open(PATH, "r", encoding="utf-8-sig", newline="") as f:
    src = f.read()

reps = []

# ---------- 改动2-a: 新增黑框ROI重搜子步骤(插在 _get_player_screen_pos 之前) ----------
NEW_METHOD = '''    def _research_anchor_around_dot(self, frame, tr, thr):
        """人名/脸/后脑本帧全丢时, 黑框光点映射点只当【搜索范围中心】, 绝不顶替人物坐标(用户2026-09-20:
        黑框在跟随区/死区有几十px偏差, 一旦顶替会让同层怪被误判cross连环锁梯、框外怪被算成框内原地空打)。
        以黑框点为中心开 LOCK_BOX_RX/RY 局部ROI, 复用现成 _role_match_in 重搜真锚点: name优先, 其次 face_r/back
        (用已学到的 off_ 偏移映射回人名线; 冷启动没学到偏移则不采信), 最后 pet; 命中过阈才返回 (ax,ay,src,score), 否则 None。"""
        _dot = self._dot_fallback_pos()
        if _dot is None or frame is None:
            return None
        _brx = int(getattr(self, 'LOCK_BOX_RX', 40) or 40)
        _bry = int(getattr(self, 'LOCK_BOX_RY', 40) or 40)
        try:
            _H, _W = frame.shape[:2]
        except Exception:
            return None
        _dcx, _dcy = int(_dot[0]), int(_dot[1])
        _roi = (max(0, _dcx - _brx), max(0, _dcy - _bry),
                min(_W, _dcx + _brx), min(_H, _dcy + _bry))
        if _roi[2] <= _roi[0] or _roi[3] <= _roi[1]:
            return None
        self._role_search_box = _roi  # 蒙板可见: 此刻正在黑框ROI内重搜真锚点(黑框只圈范围、不当坐标)
        _best = None  # (优先级, -分, key, loc, score): name=0 脸/后脑=1 宠物=2, 同级取分高
        for _k in ("name", "face_r", "back", "pet1", "pet2", "pet3"):
            try:
                _s, _loc, _face = self._role_match_in(frame, _k, _roi)
            except Exception:
                continue
            if _loc is None or _s < thr:
                continue
            _pr = 0 if _k == "name" else (1 if _k in ("face_r", "back") else 2)
            _cand = (_pr, -float(_s), _k, _loc, float(_s))
            if _best is None or _cand[:2] < _best[:2]:
                _best = _cand
        if _best is None:
            return None
        _pr, _negs, _k, _loc, _s = _best
        _lx, _ly = float(_loc[0]), float(_loc[1])
        if _k == "name" or str(_k).startswith("pet"):
            _bx, _by = _lx, _ly
        else:
            _o = (tr or {}).get("off_" + _k)
            if not _o:  # 脸/后脑没学到->人名线偏移则不采信(冷启动), 绝不裸用其质心、更不用黑框点
                return None
            _bx, _by = _lx + float(_o[0]), _ly + float(_o[1])
        return int(round(_bx)), int(round(_by)), _k, float(_s)


    def _get_player_screen_pos(self, frame):'''
OLD_DEF = '    def _get_player_screen_pos(self, frame):'
reps.append((OLD_DEF, NEW_METHOD, "2a 新增_research_anchor_around_dot"))

# ---------- 改动2-b: 冷启动无锚点分支(原直接return黑框点) ----------
OLD_COLD = '''        # 一个已采锚点都没有→新链无数据:黑框光点基点先顶替;黑框也缺=本帧无人返回None(不停旧点,用户2026-09-19)
        if not any(self._role_has_anchor(_k) for _k in ROLE_ANCHOR_KEYS):
            _dot = self._dot_fallback_pos()
            if _dot is not None:
                self._role_pos_src = 'dot'
                return _dot
            return None'''
NEW_COLD = '''        # 一个已采锚点都没有→冷启动:黑框只当搜索范围, 在其ROI内重搜真锚点; 搜到才定位, 搜不到返回None
        # (用户2026-09-20: 黑框永不当坐标; 坐标不冻结/不停旧点)
        if not any(self._role_has_anchor(_k) for _k in ROLE_ANCHOR_KEYS):
            _P0 = self._role_rec.get("params", ROLE_TRACK_DEFAULT) if self._role_rec else ROLE_TRACK_DEFAULT
            _r0 = self._research_anchor_around_dot(frame, tr, float(_P0.get("thr", 0.62)))
            if _r0 is not None:
                _ax0, _ay0, _src0, _sc0 = _r0
                tr["last"] = (_ax0, _ay0); tr["foot"] = (_ax0, _ay0); tr["miss"] = 0; tr["score"] = _sc0
                self._role_pos_src = _src0
                self._last_char_match_pos = tr["foot"]; self._last_char_match_time = time.time() * 1000
                return tr["foot"]
            self._role_pos_src = 'none'
            return None'''
reps.append((OLD_COLD, NEW_COLD, "2b 冷启动黑框降级"))

# ---------- 改动2-c: 本帧锚点全丢分支(原return黑框点) ----------
OLD_MISS = '''        _dot = self._dot_fallback_pos()   # 人名/脸/后脑全丢:黑框光点基点无缝顶替全部下游(用户2026-09-19 B方案),比hold拍旧foot点更新
        if _dot is not None:
            self._role_pos_src = 'dot'
            tr["last"] = _dot
            return _dot'''
NEW_MISS = '''        # 人名/脸/后脑本帧全丢: 黑框只当搜索范围, 在其ROI内重搜真锚点(同一套off偏移映射), 命中才回真人基点;
        # 黑框点永不当坐标, 搜不到返回None本帧跳过、不冻结(用户2026-09-20: 治黑框顶替→同层怪误判cross连环锁梯/框外空打)
        _r2 = self._research_anchor_around_dot(frame, tr, thr)
        if _r2 is not None:
            _ax2, _ay2, _src2, _sc2 = _r2
            tr["last"] = (_ax2, _ay2); tr["foot"] = (_ax2, _ay2); tr["miss"] = 0; tr["score"] = _sc2
            self._role_pos_src = _src2
            self._last_char_match_pos = tr["foot"]; self._last_char_match_time = now
            return tr["foot"]'''
reps.append((OLD_MISS, NEW_MISS, "2c 本帧全丢黑框降级"))

# ---------- 改动4-a: 蓝框 ch=None 不全屏、置None不画 ----------
OLD_FEAT = '''                    else:
                        _ftx1, _ftx2, _fty1, _fty2 = _px1, _px2, _band_y1, _band_y2
                    _feat_crop = (_ftx1, _fty1, _ftx2, _fty2)
                    if _feat_crop[2] <= _feat_crop[0] or _feat_crop[3] <= _feat_crop[1]:
                        _feat_crop = (_px1, _band_y1, _px2, _band_y2)
                    self._disp_feat_crop = _feat_crop  # 人物技能(攻击射程atk1_distance+Y上下)范围,供蒙板紫框'''
NEW_FEAT = '''                    else:
                        # 无真实人物基点(黑框帧/人名脸后脑全丢): 蓝框=面板技能范围必须以真人为中心, 宁可不画; 特征也不全屏乱匹配
                        # (用户2026-09-20: 黑框不当坐标, 不能把框外怪算成框内)
                        _ftx1 = _ftx2 = _fty1 = _fty2 = None
                    if _ftx1 is None:
                        _feat_crop = None
                    else:
                        _feat_crop = (_ftx1, _fty1, _ftx2, _fty2)
                        if _feat_crop[2] <= _feat_crop[0] or _feat_crop[3] <= _feat_crop[1]:
                            _feat_crop = None
                    self._disp_feat_crop = _feat_crop  # 人物技能(面板atk1+Y上下)范围,供蒙板蓝框;None=真人丢失本帧不画'''
reps.append((OLD_FEAT, NEW_FEAT, "4a 蓝框真人丢失不画"))

# ---------- 改动4-b: 特征匹配 None 保护(不全屏匹配) ----------
OLD_MATCH = "                        self._feat_cache = self._match_monster(_frame, _feat_crop) if self._monster_templates else []"
NEW_MATCH = "                        self._feat_cache = self._match_monster(_frame, _feat_crop) if (self._monster_templates and _feat_crop) else []"
reps.append((OLD_MATCH, NEW_MATCH, "4b 特征匹配None保护"))

# ---------- 改动5a: _enter_descend 一进来集中清旧锁 ----------
OLD_DESC = '''        self._release_move_conflicts()  # 进垂直动作前松攻击+左右
        self._climb_state = 'descend'
'''
NEW_DESC = '''        self._release_move_conflicts()  # 进垂直动作前松攻击+左右
        # 下跳一发起就当场清掉全部旧锁(用户2026-09-20): 旧实现只松键+清梯锁, 主线怪锁/红框要等落地reset(还隔500ms冷却),
        # 人都跳下来了旧怪红框还挂在旧屏幕坐标(像"锁没变")。这里同步清主线锁/B锁/决策包/红框缓存/梯锁身份,
        # 不依赖蒙板同步帧、也不靠落地reset; 落地reset只负责重扫重锁本层。
        self._combat_locked_target = None
        self._combat_last_target_pos = None
        self._locked_box_cache = None
        self._combat_had_target = False
        self._combat_target_attacked = False
        self._combat_first_strike_time = 0
        self._b_lock = None
        self._b_lock_tier = None
        self._b_hp_confirmed = False
        self._b_gone = 0
        self._b_lock_time = 0
        self._combat_decision_packet = None
        self._combat_exec_feedback = None
        self._ladder_lock = None
        if getattr(self, '_monster_overlay_data', None) is not None:
            self._monster_overlay_data["locked_target"] = None
            self._monster_overlay_data["locked_rect"] = None
        self._climb_state = 'descend'
'''
reps.append((OLD_DESC, NEW_DESC, "5a 下跳即清旧锁"))

# ---------- 附带: 伺服直跳对齐 gate 只认 name ----------
OLD_GATE = '''        if getattr(self, '_role_pos_src', None) == 'dot':
            # ≤10px原地直跳必须认人名/后脑特征点:黑框光点基点精度不足以保证抓梯。特征全丢时暂停伺服、
            # 不耗修正次数/轮次、不拿dot硬跳,原地等特征恢复(跑跳60-75不gate,用户2026-09-19)
            self._rlog_throttle('realign_dot_wait', '人名/后脑特征丢失(黑框光点顶替中),原地直跳暂停、等特征恢复', 500, log='behavior')
            return False'''
NEW_GATE = '''        if getattr(self, '_role_pos_src', None) != 'name':
            # ≤10px原地直跳只认人名中心X(用户定稿: 不用脸/后脑补、更不用黑框点; 该帧没找到人名就等下一帧,
            # 不耗修正次数/轮次、不硬跳; 跑跳60-75不gate)。黑框2026-09-20起已降级为搜索范围、不再产生坐标。
            self._rlog_throttle('realign_dot_wait', '原地直跳等人名特征(当前定位源=%s),没人名不跳' % getattr(self, '_role_pos_src', 'none'), 500, log='behavior')
            return False'''
reps.append((OLD_GATE, NEW_GATE, "附 直跳gate只认name"))

# ---------- 全部唯一性校验通过后一次性写回 ----------
for old, new, tag in reps:
    c = src.count(old)
    if c != 1:
        print("[ABORT] %s 命中次数=%d (应为1), 未写回任何改动" % (tag, c))
        sys.exit(1)
for old, new, tag in reps:
    src = src.replace(old, new)
    print("[OK] %s" % tag)

with io.open(PATH, "w", encoding="utf-8-sig", newline="") as f:
    f.write(src)
print("[DONE] 已写回", PATH)
