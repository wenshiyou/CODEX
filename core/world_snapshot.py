# -*- coding: utf-8 -*-
"""
世界快照 + 快照仓（多线程统一管控架构·第1块地基，用户2026-09-12定稿；
物理双识别线程拆分·步0扩展分项时间戳与部件合并发布，用户2026-09-12）

数据流（单向、清爽）：
- 识别线程是【唯一信息源】：截图、识别人/怪/梯子/血蓝、算位移差，把结果打成一份 WorldSnapshot，
  通过 SnapshotStore.publish 原子替换发布；识别线程永不发键。
- 物理拆分后识别层是两个线程：A=截图+人物(高频)、B=YOLO怪+模板+血条(低频)。人/怪/血条不再同帧，
  故每个部件带【自己的时间戳】(player_t/monsters_t/hp_bars_t)；A/B 用 SnapshotStore.update_parts
  只更新自己那部分，仓内在锁内基于上一份合并成新快照原子发布——任一方都不会把对方的数据覆盖没。
- 巡路/打怪/加药/边界线程【只读最新一份】：SnapshotStore.latest()，旧帧直接丢弃、不排队、不自己截图。
  用 age/part_age/is_stale 判断总帧或单个部件是否超龄，超龄(识别线程卡了)宁可停手也不拿旧坐标乱按。

本模块【纯逻辑】：不依赖 cv2/numpy/屏幕，坐标用普通元组/列表即可，可离线单测。
怪物/梯子的"候选清单"由识别线程填，"锁哪只怪/选哪个梯"由巡路决定（识别不替它锁，用户定稿锁怪归巡路）。
"""
import time
import threading


class WorldSnapshot(object):
    """一帧世界状态（只读数据袋）。字段缺省给安全空值，读取方不用反复判空。"""

    __slots__ = ("t", "player_screen", "player_map", "monsters", "locked",
                 "dx", "dy", "y_ok", "ladders", "hp", "mp", "climb_state", "extra",
                 "player_t", "monsters_t", "hp_bars_t")

    def __init__(self, t=None, player_screen=None, player_map=None, monsters=None,
                 locked=None, dx=None, dy=None, y_ok=None, ladders=None,
                 hp=None, mp=None, climb_state="none", extra=None,
                 player_t=None, monsters_t=None, hp_bars_t=None):
        self.t = time.time() if t is None else t
        self.player_screen = player_screen   # 人物在游戏窗口的坐标 (x,y)，识别线程A给
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
        self.extra = extra if extra is not None else {}  # 其它扩展，不固定结构(如 hp_bars 血条)
        # 分项时间戳：物理拆分后人/怪/血条来自不同线程、不同时刻，各自计时；None=与总t同刻(兼容单线程旧用法)
        self.player_t = player_t
        self.monsters_t = monsters_t
        self.hp_bars_t = hp_bars_t

    def age(self, now=None):
        """整帧年龄(秒)。"""
        return (time.time() if now is None else now) - self.t

    def part_timestamp(self, part):
        """某部件的时间戳，未单独记时回落到整帧 t。part: 'player'/'monsters'/'hp_bars'。"""
        if part == "player":
            return self.player_t if self.player_t is not None else self.t
        if part == "monsters":
            return self.monsters_t if self.monsters_t is not None else self.t
        if part == "hp_bars":
            return self.hp_bars_t if self.hp_bars_t is not None else self.t
        return self.t

    def part_age(self, part, now=None):
        """某部件数据的年龄(秒)：人物看player、怪表看monsters、血条看hp_bars。"""
        _n = time.time() if now is None else now
        return _n - self.part_timestamp(part)


# update_parts 允许覆盖的字段白名单（t 由仓内统一刷新，不在此列）
_PART_FIELDS = ("player_screen", "player_map", "monsters", "locked", "dx", "dy", "y_ok",
                "ladders", "hp", "mp", "climb_state", "extra",
                "player_t", "monsters_t", "hp_bars_t")


class SnapshotStore(object):
    """单/多生产者(识别A/B线程)、多消费者(动作线程)的最新值仓，原子替换、线程安全。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._snap = None

    def publish(self, snap):
        """整帧发布（整体替换，上一帧直接丢弃）。"""
        if not isinstance(snap, WorldSnapshot):
            raise TypeError("publish 需要 WorldSnapshot")
        with self._lock:
            self._snap = snap

    def update_parts(self, now=None, **parts):
        """部件合并发布（物理双识别线程用）：在锁内取上一份快照、只覆盖传入的字段，其余原样保留，
        再原子发一整份新快照，保证 A 更新人物时不会把 B 的怪表清空、反之亦然。
        extra 做浅合并（例如 B 写 extra['hp_bars'] 不冲掉别的键）；总时间戳 t 统一刷成 now。
        返回发布后的新快照。非法字段名直接报错（早暴露笔误，不静默吞）。"""
        bad = [k for k in parts if k not in _PART_FIELDS]
        if bad:
            raise KeyError("update_parts 非法字段: %s" % bad)
        with self._lock:
            old = self._snap
            kw = {f: (getattr(old, f) if old is not None else None) for f in _PART_FIELDS}
            # 缺省容器规整（旧快照为空时给安全空值，与 WorldSnapshot 默认一致）
            if old is None:
                kw["monsters"] = kw.get("monsters") or []
                kw["ladders"] = kw.get("ladders") or []
                kw["extra"] = dict(kw.get("extra") or {})
                kw["climb_state"] = kw.get("climb_state") or "none"
            # extra 浅合并：以旧 extra 为底，传入的 extra 覆盖同名键
            if "extra" in parts:
                _merged_extra = dict(getattr(old, "extra", {}) or {})
                _merged_extra.update(parts["extra"] or {})
                parts = dict(parts)
                parts["extra"] = _merged_extra
            kw.update(parts)
            new = WorldSnapshot(t=(time.time() if now is None else now), **kw)
            self._snap = new
            return new

    def latest(self):
        """取最新快照；从未发布返回 None（动作线程遇 None 应停手等待，不瞎动）。"""
        with self._lock:
            return self._snap

    def is_stale(self, max_age, now=None):
        """最新快照是否缺失或整帧超龄 max_age 秒。"""
        with self._lock:
            if self._snap is None:
                return True
            return self._snap.age(now) > max_age
