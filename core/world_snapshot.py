# -*- coding: utf-8 -*-
"""
世界快照 + 快照仓（多线程统一管控架构·第1块地基，用户2026-09-12定稿）

数据流（单向、清爽）：
- 识别线程是【唯一信息源】：截图、识别人/怪/梯子/血蓝、算位移差，把结果打成一份 WorldSnapshot，
  通过 SnapshotStore.publish 原子替换发布；识别线程永不发键。
- 巡路/打怪/加药/边界线程【只读最新一份】：SnapshotStore.latest()，旧帧直接丢弃、不排队、不互相调用、不自己截图。
- 每份快照带时间戳；读取方用 is_stale 判断是否过期，过期(如识别线程卡了)宁可停手也不拿旧坐标乱按(治特征点漂移/空打)。

本模块【纯逻辑】：不依赖 cv2/numpy/屏幕，坐标用普通元组/列表即可，可离线单测。
怪物/梯子的"候选清单"由识别线程填，"锁哪只怪/选哪个梯"由巡路决定（识别不替它锁，用户定稿锁怪归巡路）。
"""
import time
import threading


class WorldSnapshot(object):
    """一帧世界状态（只读数据袋）。字段缺省给安全空值，读取方不用反复判空。"""

    __slots__ = ("t", "player_screen", "player_map", "monsters", "locked",
                 "dx", "dy", "y_ok", "ladders", "hp", "mp", "climb_state", "extra")

    def __init__(self, t=None, player_screen=None, player_map=None, monsters=None,
                 locked=None, dx=None, dy=None, y_ok=None, ladders=None,
                 hp=None, mp=None, climb_state="none", extra=None):
        self.t = time.time() if t is None else t
        self.player_screen = player_screen   # 人物在游戏窗口的坐标 (x,y)，识别线程给
        self.player_map = player_map         # 人物在小地图的黄光点坐标 (x,y)，边界/巡路用
        self.monsters = monsters if monsters is not None else []  # 待选怪清单:[(x1,y1,x2,y2,score)...]，识别只供清单
        self.locked = locked                 # 巡路锁定的目标 (x,y)/None（锁怪归巡路，快照只回传当前锁）
        self.dx = dx                         # 人-锁定怪 X差(带符号或绝对值由上层定)
        self.dy = dy                         # 人-锁定怪 Y差
        self.y_ok = y_ok                     # 锁定怪Y是否落在方向Y带内
        self.ladders = ladders if ladders is not None else []     # 梯子候选清单
        self.hp = hp                         # 血量比例0~1/None
        self.mp = mp
        self.climb_state = climb_state       # 巡路上梯阶段(none/to_ladder/climbing/...，动作权判route用)
        self.extra = extra if extra is not None else {}  # 其它扩展，不固定结构

    def age(self, now=None):
        """快照年龄(秒)。"""
        return (time.time() if now is None else now) - self.t


class SnapshotStore(object):
    """单生产者(识别线程)、多消费者(动作线程)的最新值仓，原子替换、线程安全。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._snap = None

    def publish(self, snap):
        """识别线程发布新一帧（整体替换，上一帧直接丢弃）。"""
        if not isinstance(snap, WorldSnapshot):
            raise TypeError("publish 需要 WorldSnapshot")
        with self._lock:
            self._snap = snap

    def latest(self):
        """取最新快照；从未发布返回 None（动作线程遇 None 应停手等待，不瞎动）。"""
        with self._lock:
            return self._snap

    def is_stale(self, max_age, now=None):
        """最新快照是否缺失或超龄 max_age 秒。"""
        with self._lock:
            if self._snap is None:
                return True
            return self._snap.age(now) > max_age
