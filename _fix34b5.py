# -*- coding: utf-8 -*-
"""
_fix34b5.py  块3 手动操作记入【行为】栏(停止态也记,_rlog不依赖_running)
F5平台录制开始/结束、F6梯子录制开始/结束(含爬升耗时)、F7清空录制点、F8保存方案;
梯子/人物/怪物特征的保存/清空/删除;角色黑名单框选。
只在现有成功反馈(_add_log/print)旁并列一条 _rlog(log='behavior'),不改任何控制流。
"""
import io
PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    text = f.read()
def rep(old, new, n):
    global text
    c = text.count(old); assert c == n, "命中=%d 期望%d %r" % (c, n, old[:60])
    text = text.replace(old, new)

# F5 开始录制平台
rep(
'''                self.recording_platform = True
                self.platform_points = []
                print("Platform recording started...")''',
'''                self.recording_platform = True
                self.platform_points = []
                print("Platform recording started...")
                self._rlog("开始录制平台(F5)", log='behavior')''', 1)

# F5 结束提取平台
rep(
'''                self.platform_points = []
                self.recording_platform = False''',
'''                self.platform_points = []
                self.recording_platform = False
                self._rlog("平台录制结束(F5):本次提取%d段,累计%d段" % (len(np_) if np_ else 0, len(self.platforms)), log='behavior')''', 1)

# F6 开始录制梯子
rep(
'''                self.recording_ladder = True
                self.ladder_points = []
                self._ladder_seg_t0 = None  # 新录制段重置首末时间(用户2026-09-17)
                self._ladder_seg_t1 = None
                print("Ladder recording started...")''',
'''                self.recording_ladder = True
                self.ladder_points = []
                self._ladder_seg_t0 = None  # 新录制段重置首末时间(用户2026-09-17)
                self._ladder_seg_t1 = None
                print("Ladder recording started...")
                self._rlog("开始录制梯子(F6)", log='behavior')''', 1)

# F6 成功提取梯子
rep(
'''                    print("Extracted 1 ladder,", len(self.ladder_points), "points,", "覆盖旧梯" if replaced else "新增", "ladders总数=", len(self.ladders))''',
'''                    print("Extracted 1 ladder,", len(self.ladder_points), "points,", "覆盖旧梯" if replaced else "新增", "ladders总数=", len(self.ladders))
                    self._rlog("梯子录制结束(F6):%s,共%d把%s" % (
                        "覆盖旧梯" if replaced else "新增", len(self.ladders),
                        (" 爬升%.1fs" % new_ld['duration_sec']) if new_ld.get('duration_sec') else ""), log='behavior')''', 1)

# F7 清空录制点
rep(
'''            self.platform_points = []
            self.ladder_points = []
            self.platforms = []
            self.ladders = []
            print("Cleared all (points + saved platforms/ladders)")''',
'''            self.platform_points = []
            self.ladder_points = []
            self.platforms = []
            self.ladders = []
            print("Cleared all (points + saved platforms/ladders)")
            self._rlog("清空本次平台/梯子录制点(F7,不删已存特征)", log='behavior')''', 1)

# F8 保存方案
rep(
'''        elif vk == VK_F8:
            self._save()''',
'''        elif vk == VK_F8:
            self._save()
            self._rlog("手动保存方案(F8)", log='behavior')''', 1)

# 梯子特征 捕获保存
rep(
'''        print("[梯子特征] #%d 已存 %dx%d，共%d套" % (_new_no, cw, ch, _new_no))''',
'''        print("[梯子特征] #%d 已存 %dx%d，共%d套" % (_new_no, cw, ch, _new_no))
        self._rlog("梯子特征#%d已保存(%dx%d),共%d套" % (_new_no, cw, ch, _new_no), log='behavior')''', 1)

# 梯子特征 删除
rep(
'''            self._add_log("已删除梯子特征#%d" % _del_no)''',
'''            self._add_log("已删除梯子特征#%d" % _del_no)
            self._rlog("删除梯子特征#%d" % _del_no, log='behavior')''', 1)

# 梯子特征 清空
rep(
'''        self._add_log("已清除 %d 套梯子特征" % n)''',
'''        self._add_log("已清除 %d 套梯子特征" % n)
        self._rlog("清空全部梯子特征(%d套)" % n, log='behavior')''', 1)

# 人物特征 保存
rep(
'''        msg = "人物特征#%d已保存(%s) (%dx%d) 共%d套" % (new_id, dir_name, cw, ch, len(self._char_templates))
        self._add_log(msg)
        print("[人物特征]", msg)''',
'''        msg = "人物特征#%d已保存(%s) (%dx%d) 共%d套" % (new_id, dir_name, cw, ch, len(self._char_templates))
        self._add_log(msg)
        print("[人物特征]", msg)
        self._rlog(msg, log='behavior')''', 1)

# 人物特征 清空
rep(
'''        self._add_log("已清除 %d 套人物特征" % count)''',
'''        self._add_log("已清除 %d 套人物特征" % count)
        self._rlog("清空全部人物特征(%d套)" % count, log='behavior')''', 1)

# 怪物特征 保存
rep(
'''        msg = "怪物特征#%d已保存(%s) (%dx%d) 共%d套" % (new_id, dir_name, cw, ch, len(self._monster_templates))
        self._add_log(msg)
        print("[怪物特征]", msg)''',
'''        msg = "怪物特征#%d已保存(%s) (%dx%d) 共%d套" % (new_id, dir_name, cw, ch, len(self._monster_templates))
        self._add_log(msg)
        print("[怪物特征]", msg)
        self._rlog(msg, log='behavior')''', 1)

# 怪物特征 清空
rep(
'''        self._add_log("已清除 %d 套怪物特征" % count)''',
'''        self._add_log("已清除 %d 套怪物特征" % count)
        self._rlog("清空全部怪物特征(%d套)" % count, log='behavior')''', 1)

# 怪物特征 删除
rep(
'''        self._add_log("已删除怪物特征#%d" % t["id"])''',
'''        self._add_log("已删除怪物特征#%d" % t["id"])
        self._rlog("删除怪物特征#%d" % t["id"], log='behavior')''', 1)

# 角色黑名单框选
rep(
'''            self._add_log("已加角色黑名单 %s" % added)''',
'''            self._add_log("已加角色黑名单 %s" % added)
            self._rlog("新增角色识别黑名单 %s" % added, log='behavior')''', 1)

with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(text)
print("B5 WRITTEN")
