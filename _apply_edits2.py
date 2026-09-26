# -*- coding: utf-8 -*-
"""补丁2:X倍率改"屏幕真在动"判据;Y不标定、紫点Y钉平台绿线;恢复倍率差按钮;修保存写0;清当前错误倍率。"""
import io, os, glob, sys, json

TARGET = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(TARGET, "r", encoding="utf-8", newline="") as f:
    _raw = f.read()
_crlf = "\r\n" in _raw
content = _raw.replace("\r\n", "\n")
edits = []

# 1. 常量:加单帧位移上下限
edits.append(("1常量",
'''CALIB_MIN_SCREEN_PX = 20.0     # 本次录制死区帧累计屏幕位移不足此值不更新(位移太小斜率被±1px像素噪声放大)
CALIB_VALID_MIN = 0.01         # 倍率(小地图px/屏幕px)合理护栏,超范围不更新、提示重录
CALIB_VALID_MAX = 1.0''',
'''CALIB_MIN_SCREEN_PX = 20.0     # 本次录制累计屏幕位移不足此值不更新(位移太小斜率被±1px像素噪声放大)
CALIB_SCREEN_MOVE_MIN = 2.0    # 单帧屏幕位移下限:>此值才算人物真在走(死区),避锚点1px抖动
CALIB_SCREEN_MOVE_MAX = 60.0   # 单帧屏幕位移上限:真实走路/跑步一帧<此值,超过=锚点重定位跳变,丢弃
CALIB_VALID_MIN = 0.01         # 倍率(小地图px/屏幕px)合理护栏,超范围不更新、提示重录
CALIB_VALID_MAX = 1.0'''))

# 2. _get_monster_map_pos_verified 增强:Y钉台
edits.append(("2 Y钉台",
'''        原理：
          X = 人物小地图X + (怪屏幕X - 人物屏幕X) * scale_x
          Y = 人物小地图Y + (怪屏幕Y - 人物屏幕Y) * scale_y
          绿线校准：只在怪物Y和人物Y相差<30px（同平台范围）时，才找X最接近的绿线点修正Y
          - 高处/低处平台的怪（Y差>30px）不强制拉到绿线上，保留线性转换Y
        参数：screen_x, screen_y = 怪物屏幕坐标（YOLO检测框的中心点X，底部Y）
        返回：(map_x, map_y) 小地图坐标；人物位置未知时返回None"""
        # 方法A：以人物为参考点线性转换
        pos_a = self._screen_to_map(screen_x, screen_y)
        if pos_a is None:
            return None
        map_x, map_y = pos_a
        # 绿线Y校准：只校准和人物Y相差<30px的怪（同平台），避免高处怪被拉到低层''',
'''        X = 人物小地图X + (怪屏幕X - 人物屏幕X) * 自动X倍率。
        Y：平台游戏里怪必站某台,X判到哪台就取该台绿线在怪X处的高度(真实台高,不受爬梯镜头半随动影响);
           判不到台(不在选中台)才退回同层绿线校准+线性Y近似。
        参数：screen_x, screen_y = 怪物屏幕坐标（YOLO检测框的中心点X，底部Y）
        返回：(map_x, map_y) 小地图坐标；人物位置未知时返回None"""
        # 线性换算(X用自动倍率;Y为取景框兜底近似)
        pos_a = self._screen_to_map(screen_x, screen_y)
        if pos_a is None:
            return None
        map_x, map_y = pos_a
        # X判到选中台:怪站该台,Y直接钉该台绿线在map_x处高度(最准,不依赖Y倍率)
        _pf = self._get_monster_platform(screen_x, screen_y)
        if _pf is not None:
            _pf_best_y = None; _pf_best_dx = 999
            for (px, py) in self._platform_points(_pf):
                _dx = abs(px - map_x)
                if _dx < _pf_best_dx:
                    _pf_best_dx = _dx; _pf_best_y = py
            if _pf_best_y is not None:
                return (map_x, _pf_best_y)
        # 判不到台:同层(Y差<30)仍按X最近绿线校准,避免高处怪被拉到低层'''))

# 3. _save_calib 写真实值
edits.append(("3保存",
'''                    # 【倍率功能·已停用 2026-09-24】字段保留(兼容旧json结构),值恒写0,不再落盘脏倍率;恢复倍率后改回 getattr 实时值
                    "calibrated_scale_x": 0,
                    "calibrated_scale_y": 0,''',
'''                    "calibrated_scale_x": getattr(self, '_calibrated_scale_x', 0.0),
                    "calibrated_scale_y": getattr(self, '_calibrated_scale_y', 0.0),'''))

# 4. _auto_calib 简化为只X(无参)
edits.append(("4自动方法",
'''    def _auto_calib_from_recording(self, axis):
        """录制结束:用本次死区帧累计位移算倍率(小地图px/屏幕px),与历史值等权平均后锁定(用户2026-09-26定稿)。
        死区累计屏幕位移不足CALIB_MIN_SCREEN_PX(斜率噪声大)不更新;倍率超护栏不更新,均提示重录。"""
        if axis == 'X':
            _m = float(getattr(self, '_calib_x_m', 0.0)); _s = float(getattr(self, '_calib_x_s', 0.0))
        else:
            _m = float(getattr(self, '_calib_y_m', 0.0)); _s = float(getattr(self, '_calib_y_s', 0.0))
        if _s < CALIB_MIN_SCREEN_PX:
            self._add_log("%s倍率未更新:死区屏幕位移%.0fpx不足%.0f(录制时请在镜头静止段多走)" % (axis, _s, CALIB_MIN_SCREEN_PX))
            return
        _new = _m / _s
        if not (CALIB_VALID_MIN <= _new <= CALIB_VALID_MAX):
            self._add_log("%s倍率异常(%.4f)未更新,请重录" % (axis, _new))
            return
        _old = float(getattr(self, '_calibrated_scale_x' if axis == 'X' else '_calibrated_scale_y', 0.0))
        _val = ((_old + _new) / 2.0) if _old > 0 else _new   # 多台等权平均(用户定稿)
        if axis == 'X':
            self._calibrated_scale_x = _val
            self._map_screen_scale = _val
        else:
            self._calibrated_scale_y = _val
        self._manual_calib_done = True
        self._save_calib()
        self._add_log("%s倍率自动=%.4f(本次小地图%.0fpx/屏幕%.0fpx)%s" % (
            axis, _val, _m, _s, " 与历史平均" if _old > 0 else ""))''',
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
            _val, _m, _s, " 与历史平均" if _old > 0 else ""))'''))

# 5. F5 结束调用改无参
edits.append(("5 F5调用",
'''                    self._auto_calib_from_recording('X')''',
'''                    self._auto_calib_from_recording()'''))

# 6. F6 结束删Y调用
edits.append(("6 F6删Y",
'''                        (" 爬升%.1fs" % new_ld['duration_sec']) if new_ld.get('duration_sec') else ""), log='behavior')
                    self._auto_calib_from_recording('Y')
                else:''',
'''                        (" 爬升%.1fs" % new_ld['duration_sec']) if new_ld.get('duration_sec') else ""), log='behavior')
                else:'''))

# 7. F6 start 删Y累计初始化
edits.append(("7 F6开始",
'''                self._ladder_seg_t1 = None
                self._calib_y_m = 0.0   # Y倍率自动标定:死区帧光点Y位移累计(小地图px)
                self._calib_y_s = 0.0   # Y倍率自动标定:死区帧人物屏幕Y位移累计(屏幕px)
                self._calib_prev = None
                print("Ladder recording started...")''',
'''                self._ladder_seg_t1 = None
                print("Ladder recording started...")'''))

# 8. 采集段重写
edits.append(("8采集段",
'''            _cam_dead = (getattr(self, '_camera_state', 'deadzone') == 'deadzone')
            _cal_spos = getattr(self, '_player_screen_pos', None)
            _cal_mpos = player_pos
            if (self.recording_platform or self.recording_ladder) and _cal_spos and _cal_mpos:
                _prev = getattr(self, '_calib_prev', None)
                if _cam_dead and _prev is not None and _prev[4]:
                    _pmx, _pmy, _psx, _psy = _prev[0], _prev[1], _prev[2], _prev[3]
                    if self.recording_platform:
                        _dmx = _cal_mpos[0] - _pmx; _dsx = _cal_spos[0] - _psx
                        if _dmx * _dsx > 0:
                            self._calib_x_m += abs(_dmx)
                            self._calib_x_s += abs(_dsx)
                    if self.recording_ladder:
                        _dmy = _cal_mpos[1] - _pmy; _dsy = _cal_spos[1] - _psy
                        if _dmy * _dsy > 0:
                            self._calib_y_m += abs(_dmy)
                            self._calib_y_s += abs(_dsy)
                self._calib_prev = (_cal_mpos[0], _cal_mpos[1], _cal_spos[0], _cal_spos[1], _cam_dead)''',
'''            _cal_spos = getattr(self, '_player_screen_pos', None)
            _cal_mpos = player_pos
            if self.recording_platform and _cal_spos and _cal_mpos:
                _prev = getattr(self, '_calib_prev', None)
                if _prev is not None:
                    _dmx = _cal_mpos[0] - _prev[0]; _dsx = _cal_spos[0] - _prev[1]
                    if _dmx * _dsx > 0 and CALIB_SCREEN_MOVE_MIN <= abs(_dsx) <= CALIB_SCREEN_MOVE_MAX:
                        self._calib_x_m += abs(_dmx)
                        self._calib_x_s += abs(_dsx)
                self._calib_prev = (_cal_mpos[0], _cal_spos[0])'''))

# 9. 倍率差按钮恢复
edits.append(("9倍率差按钮",
'''        # 【倍率差弹窗】倍率功能已停用(2026-09-24):按钮不再打开弹窗。恢复:把下一行开头的 'False and ' 去掉
        if False and self._btn_scale_dialog and _in(self._btn_scale_dialog, x, y):''',
'''        # 倍率差弹窗(2026-09-26恢复):在自动标定X倍率基础上手动微调
        if self._btn_scale_dialog and _in(self._btn_scale_dialog, x, y):'''))

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

# 10. 清掉所有 calib json 里的错误倍率(只清倍率字段,平台/梯子不动),便于干净重录
nclr = 0
for cf in glob.glob(r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\data\route_*_calib.json"):
    try:
        d = json.load(io.open(cf, encoding="utf-8"))
        if d.get("calibrated_scale_x") or d.get("calibrated_scale_y"):
            d["calibrated_scale_x"] = 0; d["calibrated_scale_y"] = 0
            json.dump(d, io.open(cf, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
            nclr += 1
    except Exception as e:
        print("calib清理失败", cf, e)
print("\n已写回;清理错误倍率文件数=", nclr)
