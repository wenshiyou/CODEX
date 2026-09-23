# -*- coding: utf-8 -*-
# 诊断+减负: 1)[draw分段]写debug.log并带每秒实际画帧数  2)战斗中面板重画100ms->250ms(4fps)
import io
P=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
s0=io.open(P,'rb').read().decode('utf-8-sig'); s=s0.replace('\r\n','\n')
def rep(s,old,new,tag):
    assert s.count(old)==1,"锚点[%s] count=%d 中止"%(tag,s.count(old))
    return s.replace(old,new)

# a) draw分段写日志 + 带画帧数
a_old=(
"                    if _seg_s:\n"
"                        print(\"[draw分段] \" + _seg_s)\n"
"                    self._seg_sum = {}\n")
a_new=(
"                    if _seg_s:\n"
"                        print(\"[draw分段] \" + _seg_s)\n"
"                        _debug_log(\"[draw分段] 画帧%d/秒 %s\" % (getattr(self, '_fps_draw_n', 0), _seg_s))\n"
"                    self._seg_sum = {}\n")
s=rep(s,a_old,a_new,"draw分段日志")

# b) 每秒重置画帧计数(接在 draw/imshow/match 计时清零后)
b_old=(
"                self._fps_draw_time = 0\n"
"                self._fps_imshow_time = 0\n"
"                self._fps_match_time = 0\n")
b_new=b_old+"                self._fps_draw_n = 0\n"
s=rep(s,b_old,b_new,"画帧计数重置")

# c) draw成功后计数
c_old="                    self._last_ui_draw_t = _ui_now\n"
c_new=c_old+"                    self._fps_draw_n = getattr(self, '_fps_draw_n', 0) + 1\n"
s=rep(s,c_old,c_new,"画帧计数自增")

# d) 战斗中重画间隔 0.10 -> 0.25
d_old="            _need_ui_draw = (not _ui_throttle) or (_ui_now - getattr(self, '_last_ui_draw_t', 0.0) >= 0.10)\n"
d_new="            _need_ui_draw = (not _ui_throttle) or (_ui_now - getattr(self, '_last_ui_draw_t', 0.0) >= 0.25)\n"
s=rep(s,d_old,d_new,"重画间隔250ms")
d2_old="            # 自动打怪且非录制/校准/输入框/下拉/准星拖拽时,控制面板每100ms才重画一次(10fps看状态足够),其余帧只waitKey(5)泵事件;\n"
d2_new="            # 自动打怪且非录制/校准/输入框/下拉/准星拖拽时,控制面板每250ms才重画一次(4fps):draw单帧~43ms(日志PIL中文重绘)是主线程最大自耗,\n            # 战斗中用户看游戏画面+独立GDI红绿框、不看cv2面板,4fps看状态足够、把主线程自耗让给战斗tick;其余帧只waitKey(5)泵事件保窗口响应;\n"
s=rep(s,d2_old,d2_new,"重画注释")

io.open(P,'w',encoding='utf-8-sig',newline='').write(s.replace('\n','\r\n'))
print("落盘完成 delta=",len(s)-len(s0)+s.count('\r\n'))
