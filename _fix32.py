# -*- coding: utf-8 -*-
# _fix32: 小地图录制梯子记录每把"从下到上爬升耗时"duration_sec;上/下行爬梯总超时=该耗时+2s,无有效录制耗时回退写死12s。
# A记录: F6段首末光点时间戳; B兜底: 抓住梯_pin绑定duration,到顶/下行超时用动态阈值。旧梯子无字段=.get None=回退12s。
import io
p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(p, "r", encoding="utf-8") as f:
    text = f.read()

def rep(old, new, tag):
    global text
    n = text.count(old)
    assert n == 1, "[%s] 命中%d(应为1)" % (tag, n)
    text = text.replace(old, new)
    print("OK:", tag)

# 1) __init__ 新增4个状态属性(锚: _climb_action_time=0 带注释那行,唯一)
rep(
    "        self._climb_action_time = 0  # 跳跃/瞬移动作开始时间\n",
    "        self._climb_action_time = 0  # 跳跃/瞬移动作开始时间\n"
    "        self._climb_ladder_duration = None  # 当前爬的录制梯爬升耗时(秒),抓住梯后绑定;爬梯总超时=它+2s,无有效则回退12s(用户2026-09-17)\n"
    "        self._ladder_seg_t0 = None  # 小地图梯子录制段:首点时间戳\n"
    "        self._ladder_seg_t1 = None  # 小地图梯子录制段:末点时间戳\n",
    "1.init属性")

# 2) 录制中每个光点: 记首/末时间
rep(
    "                # 直接收集光点画面坐标，不做任何背景滚动/相对位移修正(此前scroll_y修正造出第二坐标空间导致梯子分层,已废弃)\n"
    "                self.ladder_points.append(player_pos)\n",
    "                # 直接收集光点画面坐标，不做任何背景滚动/相对位移修正(此前scroll_y修正造出第二坐标空间导致梯子分层,已废弃)\n"
    "                self.ladder_points.append(player_pos)\n"
    "                _lseg_t = time.time()  # 本段首/末光点时间,算这把梯子从下到上爬升耗时(用户2026-09-17)\n"
    "                if getattr(self, '_ladder_seg_t0', None) is None:\n"
    "                    self._ladder_seg_t0 = _lseg_t\n"
    "                self._ladder_seg_t1 = _lseg_t\n",
    "2.录制点记时间")

# 3) F6停止提取: 给new_ld写duration_sec
rep(
    "                    new_ld = nl[0]\n"
    "                    replaced = False\n",
    "                    new_ld = nl[0]\n"
    "                    # 记录本把梯子录制爬升耗时(首末光点时间差),供爬梯总超时=耗时+2s兜底(用户2026-09-17)\n"
    "                    if getattr(self, '_ladder_seg_t0', None) is not None and getattr(self, '_ladder_seg_t1', None) is not None and self._ladder_seg_t1 >= self._ladder_seg_t0:\n"
    "                        new_ld['duration_sec'] = round(self._ladder_seg_t1 - self._ladder_seg_t0, 2)\n"
    "                    replaced = False\n",
    "3.提取写duration")

# 4) F6停止: 清首末时间
rep(
    "                self.ladder_points = []\n"
    "                self.recording_ladder = False\n",
    "                self.ladder_points = []\n"
    "                self.recording_ladder = False\n"
    "                self._ladder_seg_t0 = None  # 一段录完清首末时间,下把F6重新计(用户2026-09-17)\n"
    "                self._ladder_seg_t1 = None\n",
    "4.停止清时间")

# 5) F6开始: 重置首末时间(双保险)
rep(
    "            else:\n"
    "                self.recording_ladder = True\n"
    "                self.ladder_points = []\n"
    "                print(\"Ladder recording started...\")\n",
    "            else:\n"
    "                self.recording_ladder = True\n"
    "                self.ladder_points = []\n"
    "                self._ladder_seg_t0 = None  # 新录制段重置首末时间(用户2026-09-17)\n"
    "                self._ladder_seg_t1 = None\n"
    "                print(\"Ladder recording started...\")\n",
    "5.开始重置时间")

# 6) 抓住梯后绑定录制梯端点时, 同步duration
rep(
    "        self._climb_ladder_y_bottom = float(ld['y_bottom'])\n",
    "        self._climb_ladder_y_bottom = float(ld['y_bottom'])\n"
    "        _ld_dur = ld.get('duration_sec')  # 绑定录制梯时同步这把梯的录制爬升耗时(用户2026-09-17)\n"
    "        self._climb_ladder_duration = float(_ld_dur) if isinstance(_ld_dur, (int, float)) and float(_ld_dur) >= 1.0 else None\n",
    "6.抓梯绑定duration")

# 7) _reset_climb出梯清duration
rep(
    "        self._climb_ladder_y_bottom = 0   # 当前爬的梯子底端Y（小地图，到底验证用）\n",
    "        self._climb_ladder_y_bottom = 0   # 当前爬的梯子底端Y（小地图，到底验证用）\n"
    "        self._climb_ladder_duration = None  # 出梯清录制爬升耗时,下把重新绑定(用户2026-09-17)\n",
    "7.reset清duration")

# 8) 进下行descend: 清上把上行duration(下行不爬录制梯,超时回退默认)
rep(
    "        self._ladder_lock_patch = None\n"
    "        self._monster_overlay_data[\"ladder_sel\"] = None\n",
    "        self._ladder_lock_patch = None\n"
    "        self._climb_ladder_duration = None  # 下行不爬录制梯,清上把上行耗时,下行超时回退默认12s(用户2026-09-17)\n"
    "        self._monster_overlay_data[\"ladder_sel\"] = None\n",
    "8.下行清duration")

# 9) 上行到顶段: 总超时=duration+2s
rep(
    "            # 总超时保命(没录到梯端/异常防永久卡梯);已进hold(200ms内必收尾)不再被超时打断\n"
    "            if not _arrived and not self._climb_top_hold and self._climb_action_time and now_ms - self._climb_action_time > CLIMB_TOTAL_TIMEOUT_MS:\n"
    "                _arrived = True\n"
    "                _arrive_why = \"总超时%dms保命收尾\" % CLIMB_TOTAL_TIMEOUT_MS\n",
    "            # 总超时保命(没录到梯端/异常防永久卡梯);已进hold(200ms内必收尾)不再被超时打断\n"
    "            # 阈值=这把梯录制爬升耗时+2s(用户2026-09-17);取不到有效录制耗时(旧梯/录坏<1s)才回退写死12s\n"
    "            _cdur = getattr(self, '_climb_ladder_duration', None)\n"
    "            _climb_to = int((float(_cdur) + 2.0) * 1000) if isinstance(_cdur, (int, float)) and float(_cdur) >= 1.0 else CLIMB_TOTAL_TIMEOUT_MS\n"
    "            if not _arrived and not self._climb_top_hold and self._climb_action_time and now_ms - self._climb_action_time > _climb_to:\n"
    "                _arrived = True\n"
    "                _arrive_why = \"总超时%dms保命收尾(录制爬升%s+2s)\" % (_climb_to, (\"%.1fs\" % float(_cdur)) if isinstance(_cdur, (int, float)) and float(_cdur) >= 1.0 else \"无录制默认12s\")\n",
    "9.上行动态超时")

# 10) 下行段: 总超时(正常无duration→回退12s)
rep(
    "            if not _arrived and self._climb_action_time and now_ms - self._climb_action_time > CLIMB_TOTAL_TIMEOUT_MS:\n"
    "                _arrived = True\n"
    "                _why = \"下行总超时%dms兜底\" % CLIMB_TOTAL_TIMEOUT_MS\n",
    "            _cdur_d = getattr(self, '_climb_ladder_duration', None)  # 下行不爬录制梯,正常None→回退12s;万一有值也按+2s\n"
    "            _climb_to_d = int((float(_cdur_d) + 2.0) * 1000) if isinstance(_cdur_d, (int, float)) and float(_cdur_d) >= 1.0 else CLIMB_TOTAL_TIMEOUT_MS\n"
    "            if not _arrived and self._climb_action_time and now_ms - self._climb_action_time > _climb_to_d:\n"
    "                _arrived = True\n"
    "                _why = \"下行总超时%dms兜底\" % _climb_to_d\n",
    "10.下行动态超时")

with io.open(p, "w", encoding="utf-8", newline="") as f:
    f.write(text)
print("_fix32 全部10处替换完成")
