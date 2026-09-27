# -*- coding: utf-8 -*-
"""补丁4:X标定改死区段端点法——背景帧差判死区、连续帧挑端点、段长门槛滤随动、段倍率取中位数。"""
import io, sys

TARGET = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(TARGET, "r", encoding="utf-8", newline="") as f:
    _raw = f.read()
_crlf = "\r\n" in _raw
content = _raw.replace("\r\n", "\n")
edits = []

# 1. 常量
edits.append(("1常量",
'''CALIB_MIN_SCREEN_PX = 20.0     # 本次录制累计屏幕位移不足此值不更新(位移太小斜率被±1px像素噪声放大)
CALIB_SCREEN_MOVE_MIN = 2.0    # 单帧屏幕位移下限:>此值才算人物真在走(死区),避锚点1px抖动
CALIB_SCREEN_MOVE_MAX = 60.0   # 单帧屏幕位移上限:真实走路/跑步一帧<此值,超过=锚点重定位跳变,丢弃
CALIB_VALID_MIN = 0.01         # 倍率(小地图px/屏幕px)合理护栏,超范围不更新、提示重录
CALIB_VALID_MAX = 1.0''',
'''CALIB_BG_DEAD_PCT = 20.0       # 死区判据:背景三区域帧差%最大值<此值=镜头没动(实测死区0、随动80+,阈值20安全)
CALIB_CONT_DSX_MIN = 2.0       # 连续跟踪帧:屏幕X位移下限,避锚点1px抖动
CALIB_CONT_DSX_MAX = 25.0      # 连续跟踪帧:屏幕X位移上限,真实走路/跑步一帧<25,超过=全图重定位跳变、不作端点
CALIB_SEG_MIN_SCREEN = 80.0    # 一个死区段屏幕位移不足此值丢弃(随动段屏幕走得短,由此滤掉)
CALIB_VALID_MIN = 0.01         # 段倍率(小地图px/屏幕px)护栏,超范围段丢弃
CALIB_VALID_MAX = 1.0'''))

# 2. F5 start 初始化
edits.append(("2 F5初始化",
'''                self._calib_x_m = 0.0   # X倍率自动标定:死区帧光点X位移累计(小地图px)
                self._calib_x_s = 0.0   # X倍率自动标定:死区帧人物屏幕X位移累计(屏幕px)
                self._calib_prev = None # 上一采集帧(mx,my,psx,psy,是否死区),跨随动段不累计''',
'''                self._calib_prev = None        # 上一采集帧(mx,sx),判连续用
                self._calib_seg_start = None   # 当前死区段起点(mx,sx)
                self._calib_seg_end = None     # 当前死区段终点(mx,sx)
                self._calib_seg_ratios = []    # 各死区段倍率(小地图px/屏幕px)'''))

# 3. 采集段
edits.append(("3采集段",
'''            # === 倍率自动标定·只采死区帧(用户2026-09-26):死区=镜头不动,人物屏幕位移真实,Δ光点/Δ屏幕=纯倍率;
            # 随动段镜头跟随、人物屏幕坐标不动,帧差污染倍率,整段不采。只在连续死区帧内累计,跨随动段(镜头滚过)
            # 的首尾帧不累计,避免镜头回中跳变计入;光点与屏幕必须同向变化(人物真走),镜头单滚/锚点切换跳变帧丢弃。===
            _cal_spos = getattr(self, '_player_screen_pos', None)
            _cal_mpos = player_pos
            if self.recording_platform and _cal_spos and _cal_mpos:
                _prev = getattr(self, '_calib_prev', None)
                if _prev is not None:
                    _dmx = _cal_mpos[0] - _prev[0]; _dsx = _cal_spos[0] - _prev[1]
                    if _dmx * _dsx > 0 and CALIB_SCREEN_MOVE_MIN <= abs(_dsx) <= CALIB_SCREEN_MOVE_MAX:
                        self._calib_x_m += abs(_dmx)
                        self._calib_x_s += abs(_dsx)
                self._calib_prev = (_cal_mpos[0], _cal_spos[0])''',
'''            # === X倍率自动标定·死区段端点法(用户2026-09-26定稿):不逐帧累计(人物锚点全图重定位会跳变),
            # 也不用滞后的镜头状态标签。每帧直接用背景三区域帧差判死区(都<阈值=镜头没动),用屏幕帧位移连续性
            # (2~25px、光点同向)挑稳定帧;一个连续死区段只留首尾端点,段长<80屏幕px丢弃(随动段屏幕走得短),
            # 段倍率=端点光点X差/屏幕X差;录完取各段倍率中位数(纯死区段一致~0.08)。===
            _cal_spos = getattr(self, '_player_screen_pos', None)
            _cal_mpos = player_pos
            if self.recording_platform and _cal_spos and _cal_mpos:
                _prev = getattr(self, '_calib_prev', None)
                _continuous = False
                if _prev is not None:
                    _dmx = _cal_mpos[0] - _prev[0]; _dsx = _cal_spos[0] - _prev[1]
                    # 连续跟踪:屏幕帧位移合理且光点同向(全图重定位跳变/随动静止帧都不连续)
                    _continuous = (_dmx * _dsx > 0 and CALIB_CONT_DSX_MIN <= abs(_dsx) <= CALIB_CONT_DSX_MAX)
                # 背景帧差判死区:三区域都没怎么变=镜头静止
                _dead = max(getattr(self, '_bg_diff_values', [0.0, 0.0, 0.0])) < CALIB_BG_DEAD_PCT
                if _dead and _continuous:
                    if getattr(self, '_calib_seg_start', None) is None:
                        self._calib_seg_start = (_prev[0], _prev[1])   # 段起点=首个连续帧的上一帧
                    self._calib_seg_end = (_cal_mpos[0], _cal_spos[0])
                else:
                    self._close_calib_segment()   # 离开死区/连续性中断:闭合当前段
                self._calib_prev = (_cal_mpos[0], _cal_spos[0])
            else:
                self._close_calib_segment()       # 坐标丢失:闭合段
                self._calib_prev = None'''))

# 4. _auto_calib 重写 + 新增 _close_calib_segment
edits.append(("4自动方法",
'''    def _auto_calib_from_recording(self):
        """录台子结束:用本次"屏幕真在动"帧的累计位移算X倍率(小地图px/屏幕px),与历史值等权平均后锁定。
        不依赖镜头状态机(其进死区有约10帧滞后、会漏掉纯死区长段);屏幕单帧位移落入[2,60]px且光点同向才累计,
        随动帧屏幕不动自动排除。累计屏幕位移不足CALIB_MIN_SCREEN_PX/倍率超护栏均不更新、提示重录。
        Y不标定(爬梯镜头半随动、无纯死区帧),紫点Y由X判台后钉该台绿线高度。"""
        _m = float(getattr(self, '_calib_x_m', 0.0)); _s = float(getattr(self, '_calib_x_s', 0.0))
        if _s < CALIB_MIN_SCREEN_PX:
            self._add_log("X倍率未更新:屏幕位移%.0fpx不足%.0f(录制时请在人物能于屏幕上走动的段多走)" % (_s, CALIB_MIN_SCREEN_PX))
            return
        _new = _m / _s
        if not (CALIB_VALID_MIN <= _new <= CALIB_VALID_MAX):
            self._add_log("X倍率异常(%.4f)未更新,请重录" % _new)
            return
        _old = float(getattr(self, '_calibrated_scale_x', 0.0))
        _val = ((_old + _new) / 2.0) if _old > 0 else _new   # 多台等权平均(用户定稿)
        self._calibrated_scale_x = _val
        self._map_screen_scale = _val
        self._manual_calib_done = True
        self._save_calib()
        _debug_log("[倍率] X自动=%.4f(本次小地图%.0fpx/屏幕%.0fpx)%s" % (
            _val, _m, _s, " 与历史平均" if _old > 0 else ""))
        self._add_log("X倍率自动=%.4f(小地图%.0fpx/屏幕%.0fpx)%s" % (
            _val, _m, _s, " 与历史平均" if _old > 0 else ""))''',
'''    def _close_calib_segment(self):
        """闭合当前死区段:端点(光点X差/屏幕X差)算段倍率;屏幕段长不足/超护栏段丢弃(随动短段由此滤除)。"""
        _st = getattr(self, '_calib_seg_start', None)
        _en = getattr(self, '_calib_seg_end', None)
        if _st is not None and _en is not None:
            _dm = _en[0] - _st[0]; _ds = _en[1] - _st[1]
            if abs(_ds) >= CALIB_SEG_MIN_SCREEN:
                _r = abs(_dm) / abs(_ds)
                if CALIB_VALID_MIN <= _r <= CALIB_VALID_MAX:
                    self._calib_seg_ratios.append(_r)
        self._calib_seg_start = None
        self._calib_seg_end = None

    def _auto_calib_from_recording(self):
        """录台子结束:闭合最后死区段,从各死区段倍率取中位数(纯死区段占多数且一致~0.08;随动/半随动段
        屏幕短、被段长门槛滤掉或偏大、被中位数抗掉),再与历史值等权平均锁定;无合格段提示重录。
        Y不标定(爬梯半随动、无纯死区帧),紫点Y由X判台后钉该台绿线高度。"""
        self._close_calib_segment()
        _ratios = list(getattr(self, '_calib_seg_ratios', []))
        if not _ratios:
            self._add_log("X倍率未更新:未采到镜头静止的死区长段(录制时请在人物能于屏幕中间连续走动的段多走)")
            return
        _ratios.sort()
        _mid = _ratios[len(_ratios) // 2]   # 中位数:抗个别污染段
        _old = float(getattr(self, '_calibrated_scale_x', 0.0))
        _val = ((_old + _mid) / 2.0) if _old > 0 else _mid   # 多次录制等权平均(用户定稿)
        self._calibrated_scale_x = _val
        self._map_screen_scale = _val
        self._manual_calib_done = True
        self._save_calib()
        _debug_log("[倍率] X自动=%.4f(死区段%d段:%s)%s" % (
            _val, len(_ratios), ','.join('%.3f' % r for r in _ratios), " 与历史平均" if _old > 0 else ""))
        self._add_log("X倍率自动=%.4f(死区段%d段)%s" % (_val, len(_ratios), " 与历史平均" if _old > 0 else ""))'''))

fails = []
for name, old, new in edits:
    c = content.count(old)
    if c == 1:
        content = content.replace(old, new); print("OK  ", name)
    else:
        fails.append((name, c)); print("FAIL", name, "count=", c)
if fails:
    print("\n有失败项,未写回。"); sys.exit(1)
if _crlf:
    content = content.replace("\n", "\r\n")
with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("\n补丁4已写回")
