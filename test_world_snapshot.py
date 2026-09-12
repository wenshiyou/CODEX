# -*- coding: utf-8 -*-
"""
世界快照 物理双识别线程·部件合并发布 离线单测（步0）。
纯Python、不依赖cv2/numpy/游戏： python test_world_snapshot.py
覆盖：缺省安全值、分项时间戳与回落、A/B部件合并不互相覆盖、extra浅合并、非法字段、过期判定、交替并发不丢部件。
"""
import time
import threading
from core.world_snapshot import WorldSnapshot, SnapshotStore

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s" % name)


print("== 1. 缺省安全值 ==")
s = WorldSnapshot(t=100.0)
check("monsters默认空列表", s.monsters == [])
check("ladders默认空列表", s.ladders == [])
check("extra默认空dict", s.extra == {})
check("分项时间戳缺省None", s.player_t is None and s.monsters_t is None and s.hp_bars_t is None)

print("== 2. 分项时间戳与part_age回落 ==")
s2 = WorldSnapshot(t=100.0, player_screen=(10, 20), player_t=99.0)
check("player部件用自己的时间戳", abs(s2.part_timestamp("player") - 99.0) < 1e-9)
check("monsters部件回落总t", abs(s2.part_timestamp("monsters") - 100.0) < 1e-9)
check("hp_bars部件回落总t", abs(s2.part_timestamp("hp_bars") - 100.0) < 1e-9)
check("未知部件回落总t", abs(s2.part_timestamp("xxx") - 100.0) < 1e-9)
check("player年龄=now-player_t", abs(s2.part_age("player", now=100.5) - 1.5) < 1e-9)
check("monsters年龄=now-t", abs(s2.part_age("monsters", now=100.5) - 0.5) < 1e-9)

print("== 3. 整帧publish/latest ==")
store = SnapshotStore()
check("从未发布=过期", store.is_stale(0.5) is True)
check("从未发布latest为None", store.latest() is None)
store.publish(WorldSnapshot(t=time.time(), player_screen=(1, 2)))
check("发布后能取到", store.latest().player_screen == (1, 2))
try:
    store.publish({"not": "snap"})
    check("非WorldSnapshot应报TypeError", False)
except TypeError:
    check("非WorldSnapshot报TypeError", True)

print("== 4. A/B部件合并不互相覆盖（核心） ==")
st = SnapshotStore()
# A线程先出人物
sa = st.update_parts(now=100.0, player_screen=(300, 500), player_t=100.0)
check("A发人物后人物在", sa.player_screen == (300, 500))
check("A发人物时怪默认空", sa.monsters == [])
# B线程出怪表+血条，不能把人物清掉
sb = st.update_parts(now=100.2, monsters=[(1, 2, 3, 4, 0.9)], monsters_t=100.2,
                     extra={"hp_bars": [(5, 6, 7, 8)]}, hp_bars_t=100.2)
check("B发怪后怪在", sb.monsters == [(1, 2, 3, 4, 0.9)])
check("B发怪后A的人物仍在(不被覆盖)", sb.player_screen == (300, 500))
check("B发怪后人物时间戳保留", abs(sb.player_t - 100.0) < 1e-9)
check("血条进extra", sb.extra.get("hp_bars") == [(5, 6, 7, 8)])
check("血条分项时间戳在", abs(sb.hp_bars_t - 100.2) < 1e-9)
# A再次高频更新人物，不能把B的怪清掉
sc = st.update_parts(now=100.3, player_screen=(305, 500), player_t=100.3)
check("A再更新人物后怪表仍在", sc.monsters == [(1, 2, 3, 4, 0.9)])
check("A人物刷新到新值", sc.player_screen == (305, 500))
check("总t刷成最新", abs(sc.t - 100.3) < 1e-9)

print("== 5. extra浅合并不冲掉别的键 ==")
st2 = SnapshotStore()
st2.update_parts(now=1.0, extra={"a": 1, "b": 2})
sx = st2.update_parts(now=2.0, extra={"b": 20, "c": 3})
check("旧键a保留", sx.extra.get("a") == 1)
check("同名键b被新值覆盖", sx.extra.get("b") == 20)
check("新键c加入", sx.extra.get("c") == 3)

print("== 6. 非法字段早报错 ==")
try:
    st2.update_parts(foo=1)
    check("非法字段应抛KeyError", False)
except KeyError:
    check("非法字段抛KeyError", True)

print("== 7. 过期判定 ==")
st3 = SnapshotStore()
st3.publish(WorldSnapshot(t=time.time() - 1.0))
check("整帧1秒前、阈值0.5=过期", st3.is_stale(0.5) is True)
check("整帧1秒前、阈值2.0=未过期", st3.is_stale(2.0) is False)

print("== 8. 两线程高频交替update不丢部件 ==")
st4 = SnapshotStore()
stop = threading.Event()


def writer_a():
    i = 0
    while not stop.is_set():
        st4.update_parts(player_screen=(i, 0), player_t=time.time())
        i += 1


def writer_b():
    j = 0
    while not stop.is_set():
        st4.update_parts(monsters=[(0, 0, 1, 1, 0.9 * j + 0.01)], monsters_t=time.time())
        j += 1


ta = threading.Thread(target=writer_a)
tb = threading.Thread(target=writer_b)
ta.start(); tb.start()
time.sleep(0.3)
stop.set(); ta.join(); tb.join()
final = st4.latest()
check("交替后人物部件在", final.player_screen is not None)
check("交替后怪表部件在", bool(final.monsters))
check("交替后两部件时间戳都有", final.player_t is not None and final.monsters_t is not None)

print("\n==== 结果: %d 通过, %d 失败 ====" % (PASS, FAIL))
raise SystemExit(1 if FAIL else 0)
