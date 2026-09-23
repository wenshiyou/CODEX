# -*- coding: utf-8 -*-
# 配套: 主循环战斗升帧后, 原"每30帧"的重活(小地图重定位/窗口看门狗)会被意外加速到0.3~0.6秒一次,
# 抵消主画面降帧收益。改成与帧率解耦的1.5秒时间闸(=原20fps*30帧节奏),功能语义不变。
import io, sys
P=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s0=io.open(P,'rb').read().decode('utf-8-sig'); s=s0.replace('\r\n','\n')
old=(
"            if self._auto_refresh and self.frame_count % 30 == 0:\n"
"                # [健壮性2026-09-07] 三模板重定位内部截图失败/匹配异常都不得冒泡到主入口导致闪退\n"
"                try:\n"
"                    self._detect_minimap(debug=False)\n"
"                except Exception as _e:\n"
"                    _debug_log(\"[小地图] 定时重定位异常已跳过: %s\" % _e)\n"
"            # 窗口大小固定：每30帧检测一次，变动则拉回\n"
"            if self.frame_count % 30 == 0:\n"
"                self._ensure_game_hwnd()   # 句柄看门狗:游戏重启/换频道句柄变更时自动重绑(仅自动绑定),先于尺寸校正\n"
"                self._ensure_window_size()\n"
)
new=(
"            # 周期性维护改时间闸(用户2026-09-22):战斗主画面降帧后帧率升高,\"每30帧\"会被意外加速、重定位反而拖慢战斗;\n"
"            # 统一1.5秒一次(=原20fps*30帧节奏),与帧率解耦。三模板重定位内部异常不冒泡到主入口。\n"
"            _maint_now = time.time()\n"
"            if _maint_now - getattr(self, '_maint_periodic_t', 0.0) >= 1.5:\n"
"                self._maint_periodic_t = _maint_now\n"
"                if self._auto_refresh:\n"
"                    try:\n"
"                        self._detect_minimap(debug=False)\n"
"                    except Exception as _e:\n"
"                        _debug_log(\"[小地图] 定时重定位异常已跳过: %s\" % _e)\n"
"                self._ensure_game_hwnd()   # 句柄看门狗:游戏重启/换频道句柄变更时自动重绑(仅自动绑定),先于尺寸校正\n"
"                self._ensure_window_size()  # 窗口大小固定:变动则拉回\n"
)
assert s.count(old)==1, "锚点 count=%d 中止"%s.count(old)
s=s.replace(old,new)
io.open(P,'w',encoding='utf-8-sig',newline='').write(s.replace('\n','\r\n'))
print("配套时间闸落盘完成")
