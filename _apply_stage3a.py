# -*- coding: utf-8 -*-
"""阶段1(纯新增,不改逻辑): 上梯站定二帧建锁/挪位冷却 所需常量+状态+reset复位。
二进制读写保留 UTF-8 BOM 与 LF;每个锚点断言唯一命中,任一不符则不写回。"""
import io, sys, py_compile

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
raw = open(P, "rb").read().decode("utf-8-sig")
s = raw
log = []

def rep(old, new, n=1, tag=""):
    global s
    c = s.count(old)
    assert c == n, "[%s] 命中%d次(期望%d) old=%r" % (tag, c, n, old[:70])
    s = s.replace(old, new)
    log.append("OK " + tag)

# 1) 常量(锚点: LADDER_MERGE_WAIT_MS 行 + 冻结像素块注释行)
rep(
    "LADDER_MERGE_WAIT_MS = 1500      # 红框(倍率)白框(特征)吸附合并等待上限(用户2026-09-10:必须合并才起跳):进屏幕对位后超过这么久仍没合并=白框没扫到/模板问题,放弃回主线,既不没合并硬跳、也不死等\n"
    "# === 冻结像素块跟踪(用户2026-09-15:锁像素块身份、不锁坐标) ===",
    "LADDER_MERGE_WAIT_MS = 1500      # 红框(倍率)白框(特征)吸附合并等待上限(下行方式二仍用;上行2026-09-19已改为站定二帧建锁+3扫描节拍失败,不再用固定1500)\n"
    "# === 上梯选梯·走到怪下方自然站定→二帧稳梯才建锁→找不到稳梯挪位1次+10秒冷却(用户2026-09-19定稿) ===\n"
    "LADDER_SETTLE_DPX = 3.0          # 进上梯先自然站定:相邻人物识别帧人名X位移≤此值=横向停了(不为锁梯半路刹停,走到怪X±300内松键自然停)\n"
    "LADDER_SETTLE_FRAMES = 2         # 连续几个人物识别帧横移≤SETTLE_DPX=站定完成,才进入稳梯观察\n"
    "LADDER_PICK_STABLE_DX = 12       # 二帧稳梯:相邻扫描节拍同一把梯中心X差≤此值\n"
    "LADDER_PICK_STABLE_DY = 8        # 二帧稳梯:相邻扫描节拍同一把梯中心Y差≤此值\n"
    "LADDER_PICK_STABLE_BEATS = 2     # 连续几个扫描节拍候选都落在容差内=梯子稳定,才建锁(治跑动中锁到边缘/漂移峰)\n"
    "LADDER_PICK_FAIL_BEATS = 3       # 连续几个扫描节拍仍建不出稳梯=找不到稳梯,进挪位/冷却(非precise档250ms≈750ms)\n"
    "LADDER_REPOS_MS = 130            # 找梯挪位:朝目标怪X方向单次按住左右键时长(≥120ms铁律),挪完回主线自然重锁\n"
    "LADDER_REPOS_COOLDOWN_MS = 10000 # 挪1次后10秒冷却:只禁\"找梯挪位\",扫怪/锁梯/上梯/打怪全程正常,稳梯二帧稳定立即可上\n"
    "# === 冻结像素块跟踪(用户2026-09-15:锁像素块身份、不锁坐标) ===",
    tag="常量",
)

# 2) __init__ 状态(锚点: 初始化块里 _lad_marks_recent 那行,注释含'最近约两帧白框累积池')
rep(
    "        self._lad_marks_recent = []          # 最近约两帧白框累积池[(cx,cy,t)],抗单帧闪烁(用户2026-09-15)\n",
    "        self._lad_marks_recent = []          # 最近约两帧白框累积池[(cx,cy,t)],抗单帧闪烁(用户2026-09-15)\n"
    "        # === 上梯approach:走到怪下方站定→二帧稳梯建锁→找不到稳梯挪位(用户2026-09-19) ===\n"
    "        self._ladder_approach_phase = 'none'  # none/settle站定/pick二帧建锁/repos挪位/align已建锁对位\n"
    "        self._ladder_settle_last_x = None     # 站定判据:上一人物识别帧人名屏幕X\n"
    "        self._ladder_settle_last_char_t = 0   # 站定判据:上一人物识别帧时间戳(_raw_char_t)\n"
    "        self._ladder_settle_frames = 0        # 连续横移≤SETTLE_DPX的人物识别帧数\n"
    "        self._ladder_pick_beat_scan_t = 0.0   # 二帧建锁:已计数的梯子扫描节拍时间戳(_lad_marks_scan_t,秒)\n"
    "        self._ladder_pick_stable = None       # 二帧建锁候选:(x,y,连续稳定节拍数)\n"
    "        self._ladder_pick_fail_beats = 0      # 连续建不出稳梯的扫描节拍数\n"
    "        self._ladder_lost_beat_scan_t = 0.0   # 已锁跟丢:已计数的扫描节拍\n"
    "        self._ladder_lost_beats = 0           # 已锁后实时白框+冻结块连续补不回的扫描节拍数\n"
    "        self._ladder_repos_cd_until = 0       # 找梯挪位冷却截止ms(跨本次上梯保留10s,_reset_climb有意不清)\n"
    "        self._ladder_repos_until = 0          # 本次挪位按住方向截止ms\n"
    "        self._ladder_repos_dir = 0            # 挪位方向 +1右/-1左\n",
    tag="__init__状态",
)

# 3) _reset_climb 复位(锚点: reset内 _lad_marks_recent 行,注释含'出梯清两帧累积候选池')
rep(
    "        self._lad_marks_recent = []         # 出梯清两帧累积候选池\n",
    "        self._lad_marks_recent = []         # 出梯清两帧累积候选池\n"
    "        # 上梯approach相位复位(用户2026-09-19):站定/二帧建锁/挪位每把梯重来;挪位冷却_ladder_repos_cd_until有意保留\n"
    "        self._ladder_approach_phase = 'none'\n"
    "        self._ladder_settle_last_x = None\n"
    "        self._ladder_settle_last_char_t = 0\n"
    "        self._ladder_settle_frames = 0\n"
    "        self._ladder_pick_beat_scan_t = 0.0\n"
    "        self._ladder_pick_stable = None\n"
    "        self._ladder_pick_fail_beats = 0\n"
    "        self._ladder_lost_beat_scan_t = 0.0\n"
    "        self._ladder_lost_beats = 0\n"
    "        self._ladder_repos_until = 0\n"
    "        self._ladder_repos_dir = 0\n",
    tag="reset复位",
)

assert s != raw, "内容未变化?"
open(P, "wb").write(s.encode("utf-8-sig"))
py_compile.compile(P, doraise=True)
print("\n".join(log))
print("阶段1写回并编译通过")
