# -*- coding: utf-8 -*-
"""阶段一脚本B:maple_route_ui.py 接线
1) 字段初始化 _combat_intent_packet/_b_next_anchor/_show_next_candidate/_locked_box_cache
2) 关怪扫时一并清 intent/anchor
3) B线程发布怪包后调 _publish_combat_intent 算预备怪next
4) 新增 _publish_combat_intent(B算next+in-range锚点) / _compute_locked_rect(红框脱检补位)
5) 主线帧首取intent,combat_step传fallback_next
6) cast/pursue块:drop善后用旧坐标drop_pos(修误拉黑新怪)、promoted同帧接手、删drop后release+return(0等待)
7) 蒙板同步 locked_rect/next_target/show_next;停止态清
8) 渲染端:绿框跳过锁定、红框按locked_rect直画(脱检也在)、预备怪黄框"""
import os, py_compile

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maple_route_ui.py")
raw = open(P, "rb").read()
had_bom = raw.startswith(b"\xef\xbb\xbf")
src = raw.decode("utf-8-sig").replace("\r\n", "\n")

def rep1(old, new, tag):
    global src
    c = src.count(old)
    assert c == 1, "[%s] 期望唯一命中,实际 %d 处" % (tag, c)
    src = src.replace(old, new, 1)
    print("OK:", tag)

# ---------- 1) 字段初始化 ----------
rep1(
'''        self._monsters_metric = {}          # 主线程本帧怪几何表(与self._monsters同源), combat选怪直接读、不再现算距离
''',
'''        self._monsters_metric = {}          # 主线程本帧怪几何表(与self._monsters同源), combat选怪直接读、不再现算距离
        self._combat_intent_packet = None   # 【阶段一】B线程原子发布的预备怪next {next,next_tier,t,group,cross_candidates};current一死主线同帧晋升,0等待
        self._b_next_anchor = None          # B私有备胎锚点(cx,cy,tier):in-range钉身份、坐标每帧随框刷新,out/cross每帧可换;只B写主线只读
        self._show_next_candidate = True    # 蒙板是否画预备怪黄框(调试可见开关,默认开)
        self._locked_box_cache = None       # 锁定怪最近检测框宽高(w,h):脱检帧红框用它补位,锁定在红框就在、不因YOLO漏帧消失
''', "字段初始化")

# ---------- 2) 关怪扫清 intent/anchor ----------
rep1(
'''                    self._detect_recent = []
                    self._monster_static_track = {}
''',
'''                    self._detect_recent = []
                    self._monster_static_track = {}
                    self._combat_intent_packet = None   # 关怪扫(上梯/下跳)=无怪池,预备next一并清空,主线拿不到任何怪/备胎
                    self._b_next_anchor = None
''', "关扫清intent")

# ---------- 3) B线程发布 next ----------
rep1(
'''                    except Exception as _se:
                        _debug_log("[识别B] 怪/血条快照发布异常:%s" % _se)
                    _dt_rounds += 1''',
'''                    except Exception as _se:
                        _debug_log("[识别B] 怪/血条快照发布异常:%s" % _se)
                    # 【阶段一】B线程同帧算预备怪next(纯看和选、不发键),current一死主线同帧晋升,根治"打完一波发呆几秒"
                    try:
                        self._publish_combat_intent(_ch, _merged, _metric, _fc)
                    except Exception as _ie:
                        _debug_log("[识别B] 预选怪next异常:%s" % _ie)
                    _dt_rounds += 1''', "B发布next")

# ---------- 4) 新增两个方法(插在 _combat_tick 前) ----------
methods = '''    def _publish_combat_intent(self, ch, merged, metric, fc):
        """【阶段一·B识别线程】算预备怪 next=假设当前怪没了下一只打谁,原子写 _combat_intent_packet。
        纯看和选:不发键、不读出手/爬梯状态;分桶口径与主线 combat_step 完全一致(同fight_cfg/跳高带/群攻带)。
        锚点规则(用户2026-09-18):next一旦是in(技能范围内)就钉死身份、坐标每帧随检测框刷新(镜头动也不陈旧),
        它从怪表消失或转正成current才重选;out/cross的next在current没死前每帧可刷新到更近的;始终排除current。"""
        if ch is None or not merged:
            self._combat_intent_packet = None
            self._b_next_anchor = None
            return
        px, py = ch
        _skr = int(fc.get("atk1_distance", 150) or 150)
        _yup = abs(int(fc.get("attack_y_up", -ATTACK_Y_UP)))
        _ydn = abs(int(fc.get("attack_y_down", ATTACK_Y_DOWN)))
        _ayv_up = fc.get("aoe_y_up")
        _ayv_dn = fc.get("aoe_y_down")
        _ayup = abs(int(_ayv_up)) if _ayv_up is not None else None
        _aydn = abs(int(_ayv_dn)) if _ayv_dn is not None else None
        _sjmv = fc.get("slope_jump_y_min")
        _sjxv = fc.get("slope_jump_y_max")
        try:
            _sjmin = abs(int(_sjmv)) if _sjmv is not None else None
            _sjmax = abs(int(_sjxv)) if _sjxv is not None else None
        except (TypeError, ValueError):
            _sjmin = _sjmax = None
        _slope_on = (_sjmin is not None and _sjmax is not None and _sjmax >= _sjmin)
        _eff_up = _sjmax if (_slope_on and not getattr(self, '_slope_high_blocked', False)) else _yup
        _gp = bool(fc.get("group_priority"))
        _gr = int(fc.get("aoe_distance", 200) or 200)
        _dual = bool(fc.get("aoe_dual"))
        _cur = getattr(self, '_combat_locked_target', None)
        _d = combat_logic.pick_next(
            px, py, list(merged), self._selected_platforms, _skr,
            self._get_monster_platform, _eff_up, _ydn, _gp, _gr,
            _ayup, _aydn, _dual, True, metric=metric, same_platform_fn=None,
            exclude=_cur, cur_cross=_cur)
        _raw, _raw_tier = _d.get('target'), _d.get('tier')
        _anch = getattr(self, '_b_next_anchor', None)
        _nxt, _ntier = None, None
        if _raw is not None:
            _used_anchor = False
            # in-range 备胎钉身份:上一帧锚点是in、且本帧仍在怪表同位置(±40/±50)、且没转正成current → 沿用,坐标刷新到新框
            if _anch is not None and len(_anch) >= 3 and _anch[2] == 'in':
                _ax, _ay = _anch[0], _anch[1]
                _anch_is_cur = (_cur is not None and abs(_ax - _cur[0]) <= 40 and abs(_ay - _cur[1]) <= 50)
                if not _anch_is_cur:
                    for (x1, y1, x2, y2, _s) in merged:
                        _mcx, _mcy = (x1 + x2) // 2, y2
                        if abs(_mcx - _ax) <= 40 and abs(_mcy - _ay) <= 50:
                            _nxt, _ntier, _used_anchor = (_mcx, _mcy), 'in', True
                            break
            if not _used_anchor:
                _nxt, _ntier = _raw, _raw_tier
        if _nxt is not None:
            self._b_next_anchor = (_nxt[0], _nxt[1], _ntier if _ntier == 'in' else (_ntier or 'out'))
        else:
            self._b_next_anchor = None
        self._combat_intent_packet = {'next': _nxt, 'next_tier': _ntier, 't': time.time(),
                                      'group': _d.get('group'), 'cross_candidates': _d.get('cross_candidates')}

    def _compute_locked_rect(self, lt):
        """【阶段一·蒙板红框】锁定怪在当帧怪表→用它的检测框并缓存宽高;脱检(YOLO漏帧/特效遮挡)→用锁定脚点+
        缓存宽高补位构造矩形。保证"锁定在、红框就在",修旧渲染反查当帧列表、脱检帧红框消失(打怪却正常)。"""
        if not lt:
            return None
        lcx, lcy = lt
        for (x1, y1, x2, y2, _s) in getattr(self, '_monsters', []):
            mx, my = (x1 + x2) // 2, y2
            if abs(mx - lcx) <= 60 and abs(my - lcy) <= 70:
                self._locked_box_cache = (x2 - x1, y2 - y1)
                return (int(x1), int(y1), int(x2), int(y2))
        _w, _h = self._locked_box_cache or (56, 96)
        return (int(lcx - _w / 2), int(lcy - _h), int(lcx + _w / 2), int(lcy))

    def _combat_tick(self):'''
rep1("    def _combat_tick(self):", methods, "新增两个方法")

# ---------- 5) 主线取 intent + combat_step 传 fallback_next ----------
rep1(
'''        _combat_mons = self._monsters
        _dl = combat_logic.combat_step(''',
'''        _combat_mons = self._monsters
        _intent_pkt = getattr(self, '_combat_intent_packet', None)
        _fallback_next = _intent_pkt['next'] if (_intent_pkt and _intent_pkt.get('next')) else None
        _dl = combat_logic.combat_step(''', "主线取intent")

rep1(
'''            same_platform_fn=None, metric=getattr(self, '_monsters_metric', None))''',
'''            same_platform_fn=None, metric=getattr(self, '_monsters_metric', None),
            fallback_next=_fallback_next)''', "combat_step传fallback_next")

# ---------- 6a) cast/pursue 块开头:drop善后用drop_pos + promoted并入新目标判定 ----------
rep1(
'''            t_cx, t_cy = _dl['target']
            target = (_dl['dist'], t_cx, t_cy)
            # 是否"真的换了目标"：用与select维持锁定一致的容差(±40X/±50Y)。
            # 旧代码用精确坐标相等，可怪检测框每帧抖几px→每帧误判换新目标→首次出手计时/已出手标记反复清零，
            # 130ms空怪判定永远攒不够,空怪一直打不停(用户2026-09-07)。同一只怪抖动不再重置。
            _oldlk = self._combat_locked_target
            _is_new_target = (_oldlk is None) or (abs(_oldlk[0]-t_cx) > 40 or abs(_oldlk[1]-t_cy) > 50)
            if _is_new_target:''',
'''            t_cx, t_cy = _dl['target']
            target = (_dl['dist'], t_cx, t_cy)
            _oldlk = self._combat_locked_target
            # 【阶段一·同帧晋升】旧current本帧被判死:先用【旧怪坐标drop_pos】善后(跳高降级/空怪拉黑)。
            # 旧bug:此刻_dl['target']已是重选/晋升出的新怪,旧代码却把它当空怪塞进黑名单=误拉黑新怪(发呆/锁不稳隐患)。
            if _dl.get('drop'):
                _dpos = _dl.get('drop_pos') or _oldlk
                _dpx, _dpy = (_dpos if _dpos else (t_cx, t_cy))
                if getattr(self, '_slope_high_mode', False):
                    # 跳高打出手一次仍无血条无伤害=当前位置够不着这只上层怪。它是真怪、只是要换层:不拉黑位置,
                    # 置降级标记→下帧上方分界收回攻击Y范围、让它落cross走梯子/瞬移(对接正常跨层流程)。
                    self._slope_high_blocked = True
                    self._slope_high_mode = False
                    _debug_log("[跳高打] 出手无血条无伤害=当前位置够不着，放弃跳打改走梯子/瞬移 目标(%d,%d)" % (_dpx, _dpy))
                    self._rlog("跳高打打空:无血条无伤害=这位置够不着(怪在上%dpx),改走梯子/瞬移" % (py_layer - _dpy), LOG_RED)
                    self._note_phantom_drop('跳高打空')
                else:
                    # 普通空怪(假怪/刚打死):用【旧坐标】记录位置,短时间不再重锁;新晋升的next绝不进这个黑名单
                    self._combat_dropped_phantoms.append((_dpx, _dpy, now))
                    self._rlog("怪无血条/无伤害(已死或假怪,在上%+dpx),放弃并重新锁怪" % (py_layer - _dpy), LOG_RED)
                    self._note_phantom_drop('普通空怪')
                # 异步催B下一检测帧立刻全图YOLO+血条(不等节流),但不阻塞、不return:本帧next已顶替,直接接着打/追
                self._yolo_last_t = 0.0
                self._bars_last_t = 0.0
            # 是否"真的换了目标":同帧晋升promoted / 原来没锁 / 坐标超select维持容差(±40X/±50Y)。
            # 旧代码用精确坐标相等,怪检测框每帧抖几px→每帧误判换新→首次出手/已出手标记反复清零、空怪判定攒不够(用户2026-09-07)。
            _is_new_target = bool(_dl.get('promoted')) or (_oldlk is None) or \\
                (abs(_oldlk[0] - t_cx) > 40 or abs(_oldlk[1] - t_cy) > 50)
            if _is_new_target:''', "6a drop善后+promoted")

# ---------- 6b) 新目标重置块补 gone 清零 ----------
rep1(
'''                self._combat_target_hp_confirmed = False
                self._slope_high_blocked = False        # 换新目标：清除"上一只跳打打空"降级，新目标重新按用户区间判定''',
'''                self._combat_target_hp_confirmed = False
                self._combat_gone_frames = 0            # 【阶段一】换新目标:连续无血条计数清零(新current重新判生死)
                self._slope_high_blocked = False        # 换新目标：清除"上一只跳打打空"降级，新目标重新按用户区间判定''', "6b gone清零")

# ---------- 6c) 删除旧 drop 块(release+return),善后已在块开头、同帧落执行段 ----------
rep1(
'''            # A2修复：不再把monster_dists覆盖成只剩锁定目标(原覆盖导致下方群攻永远数不到3只、群攻放不出)；群攻计数改为直接数self._monsters
            if _dl['drop']:
                # 真怪已死/假怪/打空：放弃锁定，重选
                if getattr(self, '_slope_high_mode', False):
                    # 【跳高打打空·用户2026-09-09】高坡走-跳-打出手一次仍无血条无伤害=当前位置够不着这只上层怪。
                    # 它是真怪、只是要换层：不做位置拉黑(否则走梯子也没目标)，只置降级标记→下帧上方分界收回到攻击Y范围、
                    # 让它落 cross 走梯子/瞬移上去打（对接正常跨层流程）。
                    self._slope_high_blocked = True
                    self._slope_high_mode = False
                    _debug_log("[跳高打] 出手无血条无伤害=当前位置够不着，放弃跳打改走梯子/瞬移 目标(%d,%d)" % (t_cx, t_cy))
                    self._rlog("跳高打打空:无血条无伤害=这位置够不着(怪在上%dpx),改走梯子/瞬移" % (py_layer - t_cy), LOG_RED)
                    self._note_phantom_drop('跳高打空')
                else:
                    # 普通空怪(假怪/刚打死)：记录位置，短时间不再重锁（防空怪"drop后又选同一只"死循环空打）
                    self._combat_dropped_phantoms.append((t_cx, t_cy, now))
                    self._rlog("怪无血条/无伤害(已死或假怪,在上%+dpx),放弃并重新锁怪" % (py_layer - t_cy), LOG_RED)
                    self._note_phantom_drop('普通空怪')
                self._combat_locked_target = None
                self._combat_target_attacked = False  # 放弃后重置"已出手"，避免下帧误判同一空怪
                self._combat_first_strike_time = 0    # 放弃后清零首次出手计时
                # 怪死瞬间强制下一检测周期立刻全图YOLO+血条(不等节流间隔)，打完一只秒锁下一只(用户2026-09-07换锁慢)
                self._yolo_last_t = 0.0
                self._bars_last_t = 0.0
                self._release_combat_move()
                return
        elif _dl['state'] == 'cross':''',
'''            # A2修复：不再把monster_dists覆盖成只剩锁定目标(原覆盖导致下方群攻永远数不到3只、群攻放不出)；群攻计数改为直接数self._monsters
            # 【阶段一】drop善后(跳高降级/空怪拉黑/催B刷新)已在本块开头用【旧坐标drop_pos】完成;不再release+return等下一帧——
            # 新current(原预备next)本帧直接落到下方面向/移动/出手执行段,0等待接手(根治"打完一波发呆三四秒才锁下一只")。
        elif _dl['state'] == 'cross':''', "6c 删旧drop块")

# ---------- 7a) 停止态清 next/locked_rect ----------
rep1(
'''            if not self._running:
                self._monster_overlay_data["ladder_sel"] = None
                self._monster_overlay_data["ladder_rect"] = None''',
'''            if not self._running:
                self._monster_overlay_data["ladder_sel"] = None
                self._monster_overlay_data["ladder_rect"] = None
                self._monster_overlay_data["next_target"] = None
                self._monster_overlay_data["locked_rect"] = None''', "7a 停止态清")

# ---------- 7b) 运行态下发 locked_rect/next ----------
rep1(
'''                    self._monster_overlay_data["locked_target"] = getattr(self, '_combat_locked_target', None)
''',
'''                    self._monster_overlay_data["locked_target"] = getattr(self, '_combat_locked_target', None)
                    # 【阶段一】红框按锁定坐标直画(脱检也在,修"打怪正常但红框经常不显示");预备怪next下发黄框
                    self._monster_overlay_data["locked_rect"] = self._compute_locked_rect(
                        self._monster_overlay_data["locked_target"])
                    _intent_pkt_o = getattr(self, '_combat_intent_packet', None)
                    self._monster_overlay_data["next_target"] = (_intent_pkt_o['next'] if _intent_pkt_o else None)
                    self._monster_overlay_data["show_next"] = bool(getattr(self, '_show_next_candidate', True))
''', "7b 下发locked_rect/next")

# ---------- 8) 渲染端:绿框跳过锁定 + 红框直画 + 黄框 ----------
rep1(
'''                            if char_pos:
                                # 锁定怪用红框(宽3px)，其他怪用绿框——方便看清当前在打哪只(用户2026-09-05)
                                _locked_t = data.get('locked_target')
                                green_pen = gdi32.CreatePen(0, 2, 0x00FF00)
                                red_pen = gdi32.CreatePen(0, 3, 0x0000FF)
                                if green_pen:
                                    gdi_objs.append(green_pen)
                                if red_pen:
                                    gdi_objs.append(red_pen)
                                old_pen = gdi32.SelectObject(hdc, green_pen)
                                null_brush = gdi32.GetStockObject(5)
                                old_brush = gdi32.SelectObject(hdc, null_brush)
                                for (x1, y1, x2, y2, score) in data.get('monsters', []):
                                    mx, my = (x1 + x2) // 2, (y1 + y2) // 2
                                    _is_locked = (_locked_t is not None and
                                                  abs(mx - _locked_t[0]) <= 60 and abs(my - _locked_t[1]) <= 60)
                                    if _is_locked:
                                        gdi32.SelectObject(hdc, red_pen)
                                    else:
                                        gdi32.SelectObject(hdc, green_pen)
                                    gdi32.MoveToEx(hdc, cx, cy, None)
                                    gdi32.LineTo(hdc, mx, my)
                                    gdi32.Rectangle(hdc, x1, y1, x2, y2)
                                gdi32.SelectObject(hdc, old_pen)
                                gdi32.SelectObject(hdc, old_brush)''',
'''                            if char_pos:
                                # 锁定怪红框(3px)、其他怪绿框(用户2026-09-05)。【阶段一】红框不再反查当帧怪表:YOLO仅2~4Hz、
                                # 特效遮挡会让锁定怪某帧脱检,旧写法该帧就没红框(打怪却正常);改为按主线locked_rect直画(脱检用缓存
                                # 宽高补位),锁定在红框就在。预备怪next另画黄框。
                                _locked_t = data.get('locked_target')
                                _locked_rect = data.get('locked_rect')
                                _next_p = data.get('next_target')
                                green_pen = gdi32.CreatePen(0, 2, 0x00FF00)
                                red_pen = gdi32.CreatePen(0, 3, 0x0000FF)
                                yellow_pen = gdi32.CreatePen(0, 2, 0x00FFFF)
                                if green_pen:
                                    gdi_objs.append(green_pen)
                                if red_pen:
                                    gdi_objs.append(red_pen)
                                if yellow_pen:
                                    gdi_objs.append(yellow_pen)
                                null_brush = gdi32.GetStockObject(5)
                                old_brush = gdi32.SelectObject(hdc, null_brush)
                                # 绿框+连线:所有未锁定怪(锁定那只跳过留给红框,避免红绿重影)
                                old_pen = gdi32.SelectObject(hdc, green_pen)
                                for (x1, y1, x2, y2, score) in data.get('monsters', []):
                                    mx, my = (x1 + x2) // 2, (y1 + y2) // 2
                                    _is_locked = (_locked_t is not None and
                                                  abs(mx - _locked_t[0]) <= 60 and abs(my - _locked_t[1]) <= 70)
                                    if _is_locked:
                                        continue
                                    gdi32.MoveToEx(hdc, cx, cy, None)
                                    gdi32.LineTo(hdc, mx, my)
                                    gdi32.Rectangle(hdc, x1, y1, x2, y2)
                                # 红框:按主线locked_rect直画(脱检也在)+人物到锁定中心红线
                                if _locked_rect:
                                    gdi32.SelectObject(hdc, red_pen)
                                    _lcx = (_locked_rect[0] + _locked_rect[2]) // 2
                                    gdi32.MoveToEx(hdc, cx, cy, None)
                                    gdi32.LineTo(hdc, _lcx, _locked_rect[3])
                                    gdi32.Rectangle(hdc, int(_locked_rect[0]), int(_locked_rect[1]),
                                                    int(_locked_rect[2]), int(_locked_rect[3]))
                                # 预备怪next:黄色小空心框(调试可见、不连线);与current重合则不画
                                if data.get('show_next') and _next_p and not (
                                        _locked_t and abs(_next_p[0] - _locked_t[0]) <= 40
                                        and abs(_next_p[1] - _locked_t[1]) <= 50):
                                    gdi32.SelectObject(hdc, yellow_pen)
                                    gdi32.Rectangle(hdc, int(_next_p[0]) - 22, int(_next_p[1]) - 64,
                                                    int(_next_p[0]) + 22, int(_next_p[1]))
                                gdi32.SelectObject(hdc, old_pen)
                                gdi32.SelectObject(hdc, old_brush)''', "8 渲染端红框直画+黄框")

out = src.encode("utf-8")
if had_bom:
    out = b"\xef\xbb\xbf" + out
assert b"\r\n" not in out
with open(P, "wb") as f:
    f.write(out)
py_compile.compile(P, doraise=True)
print("py_compile OK; BOM=%s; 字节数=%d" % (had_bom, len(out)))
