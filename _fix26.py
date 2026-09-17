# -*- coding: utf-8 -*-
# 阶段1: 怪物几何距离搬到B识别线程 + 怪物识别百分百总开关(行为等价)
import io

BASE = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"

def must_replace(text, old, new, tag, count=1):
    c = text.count(old)
    assert c == count, "[%s] 锚点命中 %d 次(期望%d), 未替换" % (tag, c, count)
    return text.replace(old, new, count)

# ================= combat_logic.py =================
CL = BASE + r"\combat_logic.py"
with io.open(CL, "r", encoding="utf-8") as f:
    cl = f.read()

# H) select 签名加 metric=None
cl = must_replace(cl,
"                         aoe_y_up=None, aoe_y_down=None, aoe_dual=False,\n"
"                         same_platform_fn=None):",
"                         aoe_y_up=None, aoe_y_down=None, aoe_dual=False,\n"
"                         same_platform_fn=None, metric=None):",
"select-sig")

# I) select 循环: 几何优先读B的metric, 读不到兜底现算; 平台过滤保留
cl = must_replace(cl,
"    for (x1, y1, x2, y2, _score) in monsters:\n"
"        cx = (x1 + x2) // 2\n"
"        cy = y2  # 脚位置\n"
"        # 平台过滤：只打选中平台上的怪（空列表=全图模式）\n"
"        if selected_platforms:\n"
"            pf = get_monster_platform(cx, cy)\n"
"            if pf:\n"
"                if (pf.get('id', 0) + 1) not in selected_platforms:\n"
"                    continue\n"
"            else:\n"
"                continue\n"
"        # X差和Y差分开算\n"
"        x_gap = abs(cx - px)\n"
"        dy = cy - py  # 怪脚Y - 人物脚Y（负=怪在人物上方，正=怪在人物下方）\n",
"    for (x1, y1, x2, y2, _score) in monsters:\n"
"        # 几何(中心cx/脚cy/X差/Y差)优先用B识别线程同帧算好的metric(与怪框同帧原子包),主线程不再重复算距离;读不到(人物点丢失/兜底)才现算\n"
"        _mt = metric.get((x1, y1, x2, y2)) if metric else None\n"
"        if _mt is not None:\n"
"            cx, cy, x_gap, dy = _mt\n"
"        else:\n"
"            cx = (x1 + x2) // 2\n"
"            cy = y2  # 脚位置\n"
"            x_gap = abs(cx - px)\n"
"            dy = cy - py  # 怪脚Y - 人物脚Y（负=怪在人物上方，正=怪在人物下方）\n"
"        # 平台过滤：只打选中平台上的怪（空列表=全图模式）\n"
"        if selected_platforms:\n"
"            pf = get_monster_platform(cx, cy)\n"
"            if pf:\n"
"                if (pf.get('id', 0) + 1) not in selected_platforms:\n"
"                    continue\n"
"            else:\n"
"                continue\n",
"select-loop")

# J) combat_step 签名加 metric=None
cl = must_replace(cl,
"                aoe_y_up=None, aoe_y_down=None, aoe_dual=False, can_strike=True, lock_tier=None,\n"
"                same_platform_fn=None):",
"                aoe_y_up=None, aoe_y_down=None, aoe_dual=False, can_strike=True, lock_tier=None,\n"
"                same_platform_fn=None, metric=None):",
"step-sig")

# K) combat_step 内 select 调用透传 metric
cl = must_replace(cl,
"                            aoe_y_up, aoe_y_down, aoe_dual, same_platform_fn=same_platform_fn)",
"                            aoe_y_up, aoe_y_down, aoe_dual, same_platform_fn=same_platform_fn, metric=metric)",
"step-call")

with io.open(CL, "w", encoding="utf-8", newline="") as f:
    f.write(cl)
print("combat_logic.py 阶段1替换完成(H/I/J/K)")

# ================= maple_route_ui.py =================
MP = BASE + r"\maple_route_ui.py"
with io.open(MP, "r", encoding="utf-8") as f:
    mp = f.read()

# A) __init__ 加3个变量
mp = must_replace(mp,
"        self._raw_monsters = []             # 后台线程算出的原始合并怪列表 [(x1,y1,x2,y2,score)]\n"
"        self._raw_hp_bars = []              # 后台线程算出的血条 [(x,y,w,h)]\n"
"        self._raw_char_pos = None           # 后台线程算出的人物脚位置\n",
"        self._raw_monsters = []             # 后台线程算出的原始合并怪列表 [(x1,y1,x2,y2,score)]\n"
"        self._raw_hp_bars = []              # 后台线程算出的血条 [(x,y,w,h)]\n"
"        self._raw_char_pos = None           # 后台线程算出的人物脚位置\n"
"        self._monster_scan_enabled = True   # 怪物识别B线程百分百总开关(锁梯/上梯/下跳关,回打怪开):关=主线程当帧拿不到任何怪数据\n"
"        self._raw_monster_packet = ([], {}) # B线程原子发布(怪框列表, metric几何表)同帧配对; metric={框四角:(cx,cy,x_gap,dy)}\n"
"        self._monsters_metric = {}          # 主线程本帧怪几何表(与self._monsters同源), combat选怪直接读、不再现算距离\n",
"init-vars")

# B) 硬重置块清 packet
mp = must_replace(mp,
"                    self._monster_static_track = {}\n"
"                    self._raw_monsters = []\n"
"                    _debug_log(\"[识别B] 硬重置seq=%d,清怪/血条缓存并全量重扫\" % _seen_reset_seq)\n",
"                    self._monster_static_track = {}\n"
"                    self._raw_monsters = []\n"
"                    self._raw_monster_packet = ([], {})\n"
"                    _debug_log(\"[识别B] 硬重置seq=%d,清怪/血条缓存并全量重扫\" % _seen_reset_seq)\n",
"hard-reset")

# C) _precise 块改为总闸统一清空
mp = must_replace(mp,
"                if _precise:\n"
"                    # 只清怪物位置/检测缓存,不碰任何血条;【不再continue】——落到本循环尾部做梯子白框高频扫描。\n"
"                    # (旧写法continue把尾部梯子扫描也跳过→选梯/爬梯时_lad_marks_cache冻结不更新=选梯反而不实时,已修)\n"
"                    self._raw_monsters = []\n"
"                    self._raw_cached_feature_monsters = []\n"
"                    self._yolo_cache, self._feat_cache = [], []\n"
"                    self._detect_last_monsters = None\n"
"                if not _precise:\n",
"                # 怪物识别百分百总闸:_monster_scan_enabled(锁梯/上梯/下跳由set_monster_scan关) 或 上梯精准模式,任一关=当帧清空全部怪输出\n"
"                # (含2秒宽限/时序平滑/怪物血条/几何包这些'旧怪复活'漏口),主线程当帧拿不到任何怪→不打怪不巡路;不continue,落到尾部仍扫梯子白框\n"
"                _scan_mon = (not _precise) and bool(getattr(self, '_monster_scan_enabled', True))\n"
"                if not _scan_mon:\n"
"                    self._raw_monsters = []\n"
"                    self._raw_hp_bars = []\n"
"                    self._raw_cached_feature_monsters = []\n"
"                    self._raw_monster_packet = ([], {})\n"
"                    self._yolo_cache, self._feat_cache, self._bars_cache = [], [], []\n"
"                    self._detect_last_monsters = None\n"
"                    self._detect_last_monsters_time = 0\n"
"                    self._detect_recent = []\n"
"                    self._monster_static_track = {}\n"
"                if _scan_mon:\n",
"scan-gate")

# D) 发布 packet(几何metric)
mp = must_replace(mp,
"                    self._raw_cached_feature_monsters = _feat\n"
"                    self._raw_monsters = _merged\n"
"                    self._raw_hp_bars = _bars\n",
"                    self._raw_cached_feature_monsters = _feat\n"
"                    # 几何距离在B线程算(同帧人物点_ch):cx中心/cy脚/x_gap水平差/dy垂直差(负=怪在上),与怪框打包原子发布;\n"
"                    # 主线程整包取,phantom过滤只删怪不改坐标,剩余怪四角key必命中;_ch丢失(人物没识别到)则metric空、主线程兜底现算\n"
"                    _metric = {}\n"
"                    if _ch is not None:\n"
"                        for (_bx1, _by1, _bx2, _by2, _bs) in _merged:\n"
"                            _bcx = (_bx1 + _bx2) // 2\n"
"                            _bcy = _by2\n"
"                            _metric[(_bx1, _by1, _bx2, _by2)] = (_bcx, _bcy, abs(_bcx - _ch[0]), _bcy - _ch[1])\n"
"                    self._raw_monsters = _merged\n"
"                    self._raw_monster_packet = (list(_merged), _metric)\n"
"                    self._raw_hp_bars = _bars\n",
"publish-packet")

# E) 新增 set_monster_scan 方法(插到 _check_auto_potion 前)
mp = must_replace(mp,
"    def _check_auto_potion(self):\n",
"    def set_monster_scan(self, on, reason=''):\n"
"        \"\"\"怪物识别B线程百分百总开关(用户2026-09-17)。关=当帧清空全部怪输出与跨帧缓存(2秒宽限/时序平滑/怪物血条/几何包),\n"
"        主线程self._monsters当帧为空、metric为空→算不到人怪距离→百分百不打怪/不巡路/不锁梯;开=下一帧恢复检测。\n"
"        上梯/下跳另有_ladder_precise_mode自动关怪(B循环_scan_mon已OR),本开关供需要彻底停怪的环节统一调用,关得干净、没有后门能偷偷重开。\"\"\"\n"
"        on = bool(on)\n"
"        if on == bool(getattr(self, '_monster_scan_enabled', True)):\n"
"            return\n"
"        self._monster_scan_enabled = on\n"
"        _debug_log(\"[怪物识别开关] -> %s (%s)\" % ('开' if on else '关', reason))\n"
"        if not on:\n"
"            self._raw_monsters = []\n"
"            self._raw_hp_bars = []\n"
"            self._raw_cached_feature_monsters = []\n"
"            self._raw_monster_packet = ([], {})\n"
"            self._yolo_cache, self._feat_cache, self._bars_cache = [], [], []\n"
"            self._detect_last_monsters = None\n"
"            self._detect_last_monsters_time = 0\n"
"            self._detect_recent = []\n"
"            self._monster_static_track = {}\n"
"\n"
"    def _check_auto_potion(self):\n",
"set-monster-scan")

# F) 主循环整包读 packet
mp = must_replace(mp,
"                        self._monsters = list(self._raw_monsters)\n"
"                        self._monsters = self._filter_dropped_phantoms(self._monsters)\n",
"                        _mpkt = getattr(self, '_raw_monster_packet', None)\n"
"                        if _mpkt is not None:\n"
"                            _rmons, _rmetric = _mpkt\n"
"                            self._monsters_metric = _rmetric\n"
"                            self._monsters = self._filter_dropped_phantoms(list(_rmons))\n"
"                        else:\n"
"                            self._monsters_metric = {}\n"
"                            self._monsters = self._filter_dropped_phantoms(list(self._raw_monsters))\n",
"main-read-packet")

# G) combat_step 调用传 metric
mp = must_replace(mp,
"            # 规则=先水平走到X射程内,再纯判Y:Y在主攻/高跳带=能打,仍超=cross找梯子/下台。(跨层寻路_try_platform_transition仍用绿线)\n"
"            same_platform_fn=None)\n",
"            # 规则=先水平走到X射程内,再纯判Y:Y在主攻/高跳带=能打,仍超=cross找梯子/下台。(跨层寻路_try_platform_transition仍用绿线)\n"
"            same_platform_fn=None, metric=getattr(self, '_monsters_metric', None))\n",
"step-call-metric")

with io.open(MP, "w", encoding="utf-8", newline="") as f:
    f.write(mp)
print("maple_route_ui.py 阶段1替换完成(A/B/C/D/E/F/G)")
print("ALL_DONE")
