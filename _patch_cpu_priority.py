# -*- coding: utf-8 -*-
# 根因修复: 主循环(战斗唯一司机)帧率优先
#  A) 忙档截图周期接主循环实测帧率闭环: 主循环连续挨饿→放慢截图总闸(人物/B由截图帧驱动,同步降帧让路)
#  B) 战斗运行中cv2控制面板降帧到10fps、不重画帧waitKey(5), 把主循环从 draw17ms+waitKey25ms 解放
# 不碰锁怪/爬梯/血条/速度闸; 闲档/上梯高帧/录制/校准/输入框/准星拖拽路径不变
import io, sys
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
src0 = io.open(P,'rb').read().decode('utf-8-sig')
src = src0.replace('\r\n','\n')

def rep(s, old, new, tag):
    c = s.count(old)
    assert c == 1, "锚点[%s] count=%d (应为1), 中止不写盘" % (tag, c)
    return s.replace(old, new), c

# ---- 锚点1: 常量(主循环帧率闭环) ----
a1_old = "PERSON_BUSY_STEP_MS = 3          # 忙档自适应每档退避/回升步长ms\n"
a1_new = a1_old + (
"# 忙档自适应最高准则(用户2026-09-22治\"打着打着不动\"):主循环=战斗/发键唯一司机,帧率必须优先。\n"
"# 截图线程自检只防自己吃满核,感知不到人物匹配/YOLO/绘制的总CPU压力;故再用主循环实测1秒帧率闭环——\n"
"# 主循环连续挨饿就强制放慢截图总闸(人物/B都由截图帧seq驱动,放慢它=后台整体降帧让路),富余再谨慎升回。\n"
"PERSON_BUSY_MAIN_FLOOR_FPS = 27.0  # 主循环实测帧率低于此=后台抢CPU,忙档降帧让路\n"
"PERSON_BUSY_MAIN_OK_FPS    = 29.5  # 连续高于此才认定有余量、可升回目标帧\n"
"PERSON_BUSY_MAIN_OV_N      = 2     # 连续2个1秒样本(约2s)低于floor即降一档\n"
"PERSON_BUSY_MAIN_RX_N      = 3     # 连续3个1秒样本(约3s)高于ok才升一档(防震荡)\n"
"PERSON_BUSY_MAIN_DOWN_STEP = 6     # 主循环挨饿时降档步长ms(比自检+3更快让出CPU,2~4s退到45~50ms)\n"
)
src,_ = rep(src, a1_old, a1_new, "常量")

# ---- 锚点2: 主循环每秒fps样本写出,供截图线程闭环 ----
a2_old = "                _fps = self._fps_count / (_now_fps - self._fps_last_time)\n"
a2_new = a2_old + (
"                self._main_fps = float(_fps)    # 主循环(战斗司机)实测帧率1秒样本,供截图忙档自适应闭环让路\n"
"                self._main_fps_t = _now_fps\n")
src,_ = rep(src, a2_old, a2_new, "主循环fps样本")

# ---- 锚点3: 截图忙档分支——relax加挨饿门控 + 主循环帧率裁决 + 离忙档清零 ----
a3_old = (
"                    else:\n"
"                        self._busy_rx_n += 1; self._busy_ov_n = 0\n"
"                        if self._busy_rx_n >= PERSON_BUSY_RELAX_N and _ap > _btgt:\n"
"                            _ap = max(_btgt, _ap - PERSON_BUSY_STEP_MS)\n"
"                            self._busy_adapt_p, self._busy_rx_n = _ap, 0\n"
"                    _period = _ap\n"
"                else:\n"
"                    self._busy_adapt_p = None  # 离忙档重置自适应,下次进战斗从目标周期起步\n"
"                    self._busy_ov_n = self._busy_rx_n = 0\n"
"                    _period = min(self._perf_val('detect_idle_ms'), _PERSON_IDLE_MAX_MS)\n"
)
a3_new = (
"                    else:\n"
"                        self._busy_rx_n += 1; self._busy_ov_n = 0\n"
"                        # 主循环(战斗司机)正挨饿时禁止截图线程凭\"自己轻松\"升帧——它感知不到人物/YOLO/绘制的总CPU压力\n"
"                        if self._busy_rx_n >= PERSON_BUSY_RELAX_N and _ap > _btgt and getattr(self, '_busy_main_ov', 0) == 0:\n"
"                            _ap = max(_btgt, _ap - PERSON_BUSY_STEP_MS)\n"
"                            self._busy_adapt_p, self._busy_rx_n = _ap, 0\n"
"                    # === 主循环帧率闭环(最高准则):按1秒新样本裁决,主循环连续挨饿就放慢截图总闸给战斗司机让路 ===\n"
"                    _mft = getattr(self, '_main_fps_t', 0.0)\n"
"                    if _mft and _mft != getattr(self, '_busy_main_last_t', 0.0):\n"
"                        self._busy_main_last_t = _mft\n"
"                        _mfps = getattr(self, '_main_fps', 0.0)\n"
"                        if _mfps and _mfps < PERSON_BUSY_MAIN_FLOOR_FPS:\n"
"                            self._busy_main_ov = getattr(self, '_busy_main_ov', 0) + 1; self._busy_main_rx = 0\n"
"                            if self._busy_main_ov >= PERSON_BUSY_MAIN_OV_N and _ap < PERSON_BUSY_PERIOD_MAX:\n"
"                                _ap = min(PERSON_BUSY_PERIOD_MAX, _ap + PERSON_BUSY_MAIN_DOWN_STEP)\n"
"                                self._busy_adapt_p, self._busy_ov_n = _ap, 0\n"
"                                _debug_log(\"[忙帧监管] 主循环%.1ffps<%.0f战斗挨饿,后台让路到%.0fms保司机\" % (\n"
"                                    _mfps, PERSON_BUSY_MAIN_FLOOR_FPS, _ap))\n"
"                        elif _mfps and _mfps > PERSON_BUSY_MAIN_OK_FPS:\n"
"                            self._busy_main_rx = getattr(self, '_busy_main_rx', 0) + 1; self._busy_main_ov = 0\n"
"                            if self._busy_main_rx >= PERSON_BUSY_MAIN_RX_N and _ap > _btgt:\n"
"                                _ap = max(_btgt, _ap - PERSON_BUSY_STEP_MS)\n"
"                                self._busy_adapt_p, self._busy_main_rx = _ap, 0\n"
"                    _period = _ap\n"
"                else:\n"
"                    self._busy_adapt_p = None  # 离忙档重置自适应,下次进战斗从目标周期起步\n"
"                    self._busy_ov_n = self._busy_rx_n = 0\n"
"                    self._busy_main_ov = self._busy_main_rx = 0  # 离忙档清主循环闭环计数\n"
"                    self._busy_main_last_t = 0.0\n"
"                    _period = min(self._perf_val('detect_idle_ms'), _PERSON_IDLE_MAX_MS)\n"
)
src,_ = rep(src, a3_old, a3_new, "忙档主循环闭环")

# ---- 锚点4: 战斗运行中主画面降帧 + waitKey缩短 ----
a4_old = (
"            try:\n"
"                _td0 = time.time()\n"
"                frame = self.draw(map_area, self._player_map_pos)\n"
"                self._fps_draw_time += time.time() - _td0\n"
"                _ti0 = time.time()\n"
"                cv2.imshow(win, frame)\n"
"                self._fps_imshow_time += time.time() - _ti0\n"
"            except Exception as e:\n"
"                print(\"draw error:\", e)\n"
"                cv2.imshow(win, self._ui_bg)\n"
"\n"
"            key = cv2.waitKey(int(self._perf_val('ui_wait_ms'))) & 0xFF  # UI帧间隔按CPU性能档(快15/普通25/慢40ms);挂机面板无需高刷,战斗按键靠内部时间戳节流不受影响\n"
)
a4_new = (
"            # 战斗运行中主画面降帧(用户2026-09-22治\"打着打着不动\":cv2控制面板draw≈17ms/帧+waitKey25ms把战斗主循环压到20fps):\n"
"            # 自动打怪且非录制/校准/输入框/下拉/准星拖拽时,控制面板每100ms才重画一次(10fps看状态足够),其余帧只waitKey(5)泵事件;\n"
"            # 真正打怪看的红/绿框在独立GDI蒙板窗口、不受影响;录制/校准/编辑面板时恢复全帧跟手。\n"
"            _ui_throttle = bool(getattr(self, '_running', False)) and not (\n"
"                getattr(self, 'recording_platform', False) or getattr(self, 'recording_ladder', False)\n"
"                or getattr(self, '_auto_calib_stage', 0) or (getattr(self, '_focused_field', None) is not None)\n"
"                or getattr(self, '_drag_crosshair', False) or getattr(self, '_dropdown', None)\n"
"                or getattr(self, '_bound_dropdown', False))\n"
"            _ui_now = time.time()\n"
"            _need_ui_draw = (not _ui_throttle) or (_ui_now - getattr(self, '_last_ui_draw_t', 0.0) >= 0.10)\n"
"            if _need_ui_draw:\n"
"                try:\n"
"                    _td0 = _ui_now\n"
"                    frame = self.draw(map_area, self._player_map_pos)\n"
"                    self._fps_draw_time += time.time() - _td0\n"
"                    _ti0 = time.time()\n"
"                    cv2.imshow(win, frame)\n"
"                    self._fps_imshow_time += time.time() - _ti0\n"
"                    self._last_ui_draw_t = _ui_now\n"
"                except Exception as e:\n"
"                    print(\"draw error:\", e)\n"
"                    cv2.imshow(win, self._ui_bg)\n"
"            # 战斗降帧且本帧不重画:waitKey(5)只泵事件不节流,主循环(战斗tick)跑到高帧率;重画帧/非战斗仍按CPU档UI间隔\n"
"            _ui_wait_ms = 5 if (_ui_throttle and not _need_ui_draw) else int(self._perf_val('ui_wait_ms'))\n"
"            key = cv2.waitKey(_ui_wait_ms) & 0xFF  # 战斗中降帧帧waitKey(5)不拖战斗;按键靠内部时间戳节流、不受帧率影响\n"
)
src,_ = rep(src, a4_old, a4_new, "主画面战斗降帧")

if src == src0:
    print("无改动"); sys.exit(3)
io.open(P,'w',encoding='utf-8-sig',newline='').write(src.replace('\n','\r\n'))
print("落盘完成, 新增字符数:", len(src)-len(src0))
