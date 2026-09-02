"""测试技能随机时间是否生效
模拟 _combat_tick 中的 BUFF/药品随机冷却逻辑，统计实际释放间隔
"""
import random
import time

def simulate_casting(cd_ms, rand_ms, ticks_per_sec=60, duration_sec=30):
    """模拟战斗循环，返回每次释放的时间间隔列表"""
    intervals = []
    last_cast = 0
    now = 0
    tick_ms = 1000.0 / ticks_per_sec
    total_ticks = int(duration_sec * ticks_per_sec)

    for _ in range(total_ticks):
        now += tick_ms
        # 这就是 _combat_tick 里的逻辑：每tick重新roll随机值
        actual_cd = cd_ms + random.randint(-rand_ms, rand_ms)
        if now - last_cast > actual_cd:
            if last_cast > 0:
                intervals.append(now - last_cast)
            last_cast = now
    return intervals

def test(name, cd_ms, rand_ms):
    print("\n" + "=" * 60)
    print(f"测试: {name}")
    print(f"  设定冷却: {cd_ms}ms, 随机范围: ±{rand_ms}ms")
    print(f"  理论间隔范围: [{cd_ms - rand_ms}, {cd_ms + rand_ms}]ms")

    intervals = simulate_casting(cd_ms, rand_ms, ticks_per_sec=60, duration_sec=60)

    if not intervals:
        print("  ❌ 没有触发任何释放！")
        return

    intervals.sort()
    avg = sum(intervals) / len(intervals)
    print(f"  实际触发次数: {len(intervals)} 次 (60秒)")
    print(f"  实际间隔: 最小={intervals[0]:.0f}ms  最大={intervals[-1]:.0f}ms  平均={avg:.0f}ms")
    print(f"  中位数: {intervals[len(intervals)//2]:.0f}ms")

    # 检查是否有随机性（如果所有间隔都一样，说明随机没生效）
    unique = len(set(round(x) for x in intervals))
    if unique <= 1:
        print(f"  ❌ 随机未生效！所有间隔几乎相同 ({unique}种)")
    elif rand_ms == 0:
        print(f"  ✅ 随机范围为0，间隔固定，符合预期")
    else:
        variance = max(intervals) - min(intervals)
        if variance > rand_ms * 0.5:
            print(f"  ✅ 随机已生效！间隔波动 {variance:.0f}ms")
        else:
            print(f"  ⚠️  随机效果较弱，波动仅 {variance:.0f}ms")

    # 打印前10个间隔
    print(f"  前10次间隔: {[f'{x:.0f}' for x in intervals[:10]]}")

if __name__ == "__main__":
    random.seed(42)

    # 测试1: BUFF随机（默认buff_random=100, cd=60000）
    test("BUFF技能 (cd=60000ms, rand=±100ms)", 60000, 100)

    # 测试2: 药品随机（默认potion_random=50）
    test("药品1-5 (cd=5000ms, rand=±50ms)", 5000, 50)

    # 测试3: 技能随机（skill_random默认50，但未接入逻辑）
    test("主攻技能 (cd=300ms, rand=±50ms) — 注意: 实际代码中未接入", 300, 50)

    # 测试4: 随机=0（对照组）
    test("对照组 (cd=3000ms, rand=0ms)", 3000, 0)

    # 测试5: 大随机范围
    test("大随机 (cd=2000ms, rand=±500ms)", 2000, 500)

    print("\n" + "=" * 60)
    print("代码审查结论:")
    print("  buff_random  -> _combat_tick 中 BUFF 循环 ✅ 已生效")
    print("  potion_random -> _combat_tick 中 药品1-5 循环 ✅ 已生效")
    print("  skill_random  -> 仅在 _get_fight_config 读取，_combat_tick 中未使用 ❌")
    print("  原因: 主攻/群攻技能(atk1/aoe)的释放逻辑还没写入 _combat_tick")
    print("        (代码注释: 主攻/群攻技能等YOLO模型到位后接入)")
