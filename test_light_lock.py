"""光点锁定函数单元测试 - 验证 lock_screen_from_dot 和 monster_to_map 逻辑"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 模拟一个简单的测试对象
class TestBot:
    def __init__(self):
        self.map_area_rect = None
        self._player_map_pos = None
        self._target_window_size = None
        self._player_screen_pos = None
        self.frame_count = 0

    def lock_screen_from_dot(self):
        r = getattr(self, 'map_area_rect', None)
        if not r or r.get("width", 0) <= 0 or r.get("height", 0) <= 0:
            return None
        if not self._player_map_pos:
            return None
        mx, my = self._player_map_pos
        rw = r["width"]
        rh = r["height"]
        rx = mx / float(rw)
        ry = my / float(rh)
        win_w, win_h = getattr(self, '_target_window_size', None) or (0, 0)
        if win_w <= 0 or win_h <= 0:
            return None
        sx = int(win_w * rx)
        sy = int(win_h * ry)
        return (sx, sy)

    def monster_to_map(self, monster_sx, monster_sy):
        r = getattr(self, 'map_area_rect', None)
        if not r or r.get("width", 0) <= 0 or r.get("height", 0) <= 0:
            return None
        pos = self._player_screen_pos
        if not pos:
            return None
        psx, psy = pos
        win_w, win_h = getattr(self, '_target_window_size', None) or (0, 0)
        if win_w <= 0 or win_h <= 0:
            return None
        dx_ratio = (monster_sx - psx) / float(win_w)
        dy_ratio = (monster_sy - psy) / float(win_h)
        p_rx = psx / float(win_w)
        p_ry = psy / float(win_h)
        rx = p_rx + dx_ratio
        ry = p_ry + dy_ratio
        map_x = int(r["left"] + rx * r["width"])
        map_y = int(r["top"] + ry * r["height"])
        return (map_x, map_y)


def test_lock_screen_from_dot():
    print("=== 测试 lock_screen_from_dot ===")
    bot = TestBot()
    
    # 测试1: 无map_area_rect → None
    assert bot.lock_screen_from_dot() is None, "无map_area_rect应返回None"
    print("PASS: 无map_area_rect返回None")
    
    # 测试2: 无_player_map_pos → None
    bot.map_area_rect = {"left": 10, "top": 20, "width": 100, "height": 80}
    assert bot.lock_screen_from_dot() is None, "无_player_map_pos应返回None"
    print("PASS: 无_player_map_pos返回None")
    
    # 测试3: 无_target_window_size → None
    bot._player_map_pos = (50, 40)
    assert bot.lock_screen_from_dot() is None, "无_target_window_size应返回None"
    print("PASS: 无_target_window_size返回None")
    
    # 测试4: 正常情况 - 光点在小地图中心 → 屏幕中心
    bot._target_window_size = (1382, 807)
    result = bot.lock_screen_from_dot()
    expected = (int(1382 * 50/100), int(807 * 40/80))
    assert result == expected, f"期望{expected}, 实际{result}"
    print(f"PASS: 光点(50,40)→屏幕{result} (期望{expected})")
    
    # 测试5: 光点在小地图左上角 → 屏幕左上角
    bot._player_map_pos = (0, 0)
    result = bot.lock_screen_from_dot()
    assert result == (0, 0), f"期望(0,0), 实际{result}"
    print(f"PASS: 光点(0,0)→屏幕{result}")
    
    # 测试6: 光点在小地图右下角 → 屏幕右下角
    bot._player_map_pos = (100, 80)
    result = bot.lock_screen_from_dot()
    assert result == (1382, 807), f"期望(1382,807), 实际{result}"
    print(f"PASS: 光点(100,80)→屏幕{result}")
    
    print("lock_screen_from_dot 全部通过!\n")


def test_monster_to_map():
    print("=== 测试 monster_to_map ===")
    bot = TestBot()
    bot.map_area_rect = {"left": 10, "top": 20, "width": 100, "height": 80}
    bot._target_window_size = (1382, 807)
    bot._player_screen_pos = (691, 403)  # 屏幕中心
    
    # 测试1: 怪物在人物位置 → 小地图人物位置
    result = bot.monster_to_map(691, 403)
    # 人物归一化位置 = (691/1382, 403/807) ≈ (0.5, 0.5)
    # map_x = 10 + 0.5*100 = 60, map_y = 20 + 0.5*80 = 60
    assert result == (60, 60), f"期望(60,60), 实际{result}"
    print(f"PASS: 怪物在人物位置→小地图{result}")
    
    # 测试2: 怪物在人物右边 → 小地图右边
    result = bot.monster_to_map(1000, 403)
    dx_ratio = (1000-691)/1382
    p_rx = 691/1382
    rx = p_rx + dx_ratio
    expected_x = int(10 + rx * 100)
    assert result[0] == expected_x, f"期望x={expected_x}, 实际{result[0]}"
    print(f"PASS: 怪物在人物右边→小地图{result}")
    
    # 测试3: 无_player_screen_pos → None
    bot._player_screen_pos = None
    assert bot.monster_to_map(100, 200) is None, "无_player_screen_pos应返回None"
    print("PASS: 无_player_screen_pos返回None")
    
    print("monster_to_map 全部通过!\n")


if __name__ == "__main__":
    test_lock_screen_from_dot()
    test_monster_to_map()
    print("=== 所有测试通过! ===")
